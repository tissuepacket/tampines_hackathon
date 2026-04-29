from datetime import date
from enum import Enum
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from pathlib import Path
from uuid import uuid4
import csv
import os
import base64
import binascii
import json
import mimetypes
import sys
import urllib.error
import urllib.request
from collections import Counter

app = FastAPI(title="Bike Patrol Rewards", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class IssueType(str, Enum):
    illegal_parking = "illegal_parking"
    toppled = "toppled"
    faulty = "faulty"
    general = "general"
    others = "others"

class Report(BaseModel):
    report_id: Optional[str] = Field(None, title="Report identifier")
    reporter: str = Field(..., title="Reporter name or email")
    bike_id: str = Field(..., title="Bike identifier")
    issue_type: IssueType = Field(..., title="Type of issue")
    description: str = Field(..., title="What happened")
    location_text: Optional[str] = Field(None, title="Reported location")
    location_address: Optional[str] = Field(None, title="Resolved rough address")
    location_lat: Optional[float] = Field(None, title="Latitude")
    location_lng: Optional[float] = Field(None, title="Longitude")
    location_accuracy: Optional[float] = Field(None, title="Location accuracy in meters")
    outside_zone: Optional[bool] = Field(False, title="Outside designated parking zone")
    toppled: Optional[bool] = Field(False, title="Bike is toppled")
    faulty: Optional[bool] = Field(False, title="Bike appears faulty")
    image: Optional[str] = Field(None, title="Base64 encoded image data")
    ai_summary: Optional[str] = Field(None, title="AI assessment of the uploaded image")
    status: Optional[str] = Field("pending", title="Report review status")
    reviewed_by: Optional[str] = Field(None, title="Report reviewed by")
    review_notes: Optional[str] = Field(None, title="Review notes")
    review_action: Optional[str] = Field(None, title="Review action")

class RewardRequest(BaseModel):
    user: str = Field(..., title="User name or email")
    action: str = Field(..., title="Reward action requested")

class UseRewardRequest(BaseModel):
    reward: str = Field(..., title="Reward to use")

class HelpRequest(BaseModel):
    user: str = Field(..., title="User name or email")
    bike_id: str = Field(..., title="Bike identifier")
    notes: Optional[str] = Field(None, title="Optional notes")

class ParkingRedeemRequest(BaseModel):
    user: str = Field(..., title="User name or email")
    points: int = Field(1, ge=1, title="Points to redeem")
    reward_name: Optional[str] = Field("Parking Helper Reward", title="Reward name")

class LoginRequest(BaseModel):
    user: str = Field(..., title="User name or email")
    password: str = Field(..., title="Login password")

class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., title="Current password")
    new_password: str = Field(..., title="New password")

class PasswordResetRequest(BaseModel):
    user: str = Field(..., title="User name or email")
    new_password: str = Field(..., title="New password")

class RegisterRequest(BaseModel):
    user: str = Field(..., title="User name or email")
    password: str = Field(..., title="Account password")

class SettingsRequest(BaseModel):
    display_name: Optional[str] = Field(None, title="Display name")
    theme: Optional[str] = Field(None, title="Preferred theme")
    font_size: Optional[str] = Field(None, title="Preferred font size")

class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(None, title="Display name")
    email: Optional[str] = Field(None, title="Email address")
    phone_number: Optional[str] = Field(None, title="Phone number")

class ReportSummary(BaseModel):
    total_reports: int
    recent_reports: List[Report]
    all_reports: Optional[List[Report]] = None
    pending_reports: Optional[List[Report]] = None
    completed_reports: Optional[List[Report]] = None

REPORTS: List[Report] = []
USER_ACCOUNTS: Dict[str, dict] = {}
REWARD_LIMIT_PER_DAY = 3
reward_store = {}
SESSIONS: Dict[str, str] = {}
ROLE_PRIORITY = {"admin": 3, "maintenance": 2, "user": 1}
CSV_DIR = Path(__file__).resolve().parents[1] / "csv"
REPORT_IMAGES_DIR = CSV_DIR / "report-images"
REPORTS_CSV_PATH = CSV_DIR / "reports.csv"
REPORT_CSV_FIELDS = [
    "report_id",
    "reporter",
    "bike_id",
    "issue_type",
    "description",
    "location_text",
    "location_address",
    "location_lat",
    "location_lng",
    "location_accuracy",
    "outside_zone",
    "toppled",
    "faulty",
    "image",
    "ai_summary",
    "status",
    "reviewed_by",
    "review_notes",
    "review_action",
    "reward_granted",
    "reward_voucher",
    "image_file",
]


def get_llm_token() -> Optional[str]:
    load_env_file()
    return os.getenv("LLM_TOKEN") or os.getenv("OPENAI_API_KEY")


def extract_response_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"].strip()

    for output_item in payload.get("output", []):
        for content_item in output_item.get("content", []):
            text = content_item.get("text")
            if text and isinstance(text, str):
                return text.strip()
    return ""


def analyze_report_image_with_llm(
    image_data_url: str,
    bike_id: str,
    issue_type: str,
    description: str,
    location_text: Optional[str] = None,
    location_address: Optional[str] = None,
) -> Optional[str]:
    token = get_llm_token()
    if not token:
        return None

    prompt = (
        "Review this bicycle report image and give a short assessment in 1-2 sentences. "
        "Mention whether the image appears consistent with the report details and note any obvious issue. "
        "If there is no clear problem, say so clearly. "
        f"Report details: bike_id={bike_id}, issue_type={issue_type}, description={description}."
        + (f" Report location: {location_text}." if location_text else "")
        + (f" Rough address: {location_address}." if location_address else "")
    )
    payload = {
        "model": "gpt-4.1-mini",
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_data_url, "detail": "low"},
                ],
            }
        ],
        "max_output_tokens": 200,
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None

    return extract_response_text(response_payload) or None


def format_location_text(lat: Optional[float], lng: Optional[float], accuracy: Optional[float]) -> Optional[str]:
    if lat is None or lng is None:
        return None
    base = f"{lat:.6f}, {lng:.6f}"
    if accuracy is not None:
        return f"{base} (±{accuracy:.0f}m)"
    return base


def reverse_geocode_location(lat: float, lng: float) -> Optional[str]:
    url = (
        "https://nominatim.openstreetmap.org/reverse"
        f"?format=jsonv2&lat={lat}&lon={lng}&zoom=18&addressdetails=1"
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "BikePatrolRewards/1.0 (+local-dev)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None

    address = payload.get("address", {})
    display_name = payload.get("display_name")
    road = address.get("road") or address.get("pedestrian") or address.get("footway")
    neighbourhood = address.get("neighbourhood") or address.get("suburb") or address.get("quarter")
    city = address.get("city") or address.get("town") or address.get("village") or address.get("municipality")
    postcode = address.get("postcode")

    parts = [part for part in [road, neighbourhood, city] if part]
    if parts:
        if postcode:
            parts[-1] = f"{parts[-1]} {postcode}"
        return ", ".join(parts)

    return display_name


def build_location_address(lat: Optional[float], lng: Optional[float], accuracy: Optional[float] = None) -> Optional[str]:
    if lat is None or lng is None:
        return None

    rough_address = reverse_geocode_location(lat, lng)
    if rough_address:
        return rough_address

    return format_location_text(lat, lng, accuracy)


def csv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def parse_csv_bool(value: Optional[str]) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_csv_float(value: Optional[str]) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def configure_csv_field_size_limit() -> None:
    try:
        csv.field_size_limit(sys.maxsize)
    except OverflowError:
        csv.field_size_limit(2**31 - 1)


def decode_data_url(image_data_url: str) -> tuple[Optional[str], Optional[bytes]]:
    if not image_data_url or not image_data_url.startswith("data:"):
        return None, None
    try:
        header, encoded = image_data_url.split(",", 1)
        mime_type = header.split(";", 1)[0][5:] or "application/octet-stream"
        return mime_type, base64.b64decode(encoded)
    except (ValueError, IndexError, binascii.Error):
        return None, None


def save_report_image(report_id: str, image_data_url: Optional[str], content_type: Optional[str] = None) -> Optional[str]:
    if not image_data_url:
        return None
    if image_data_url.startswith("data:"):
        mime_type, content = decode_data_url(image_data_url)
        if content is None:
            return None
        content_type = mime_type or content_type
    else:
        content = image_data_url.encode("utf-8")

    REPORT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    ext = mimetypes.guess_extension(content_type or "") or ".bin"
    image_file = f"{report_id}{ext}"
    (REPORT_IMAGES_DIR / image_file).write_bytes(content)
    return image_file


def load_report_image_data(image_file: Optional[str]) -> Optional[str]:
    if not image_file:
        return None
    image_path = REPORT_IMAGES_DIR / image_file
    if not image_path.exists():
        return None
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{content_type};base64,{encoded}"


def normalize_report_record(report: dict) -> dict:
    normalized = dict(report)
    normalized.setdefault("image_file", "")
    issue_type = str(normalized.get("issue_type") or "general").strip().lower().replace(" ", "_")
    if issue_type not in {item.value for item in IssueType}:
        issue_type = "general"
    normalized["issue_type"] = issue_type
    for key in ["location_text", "location_address", "reviewed_by", "review_notes", "review_action", "ai_summary", "image", "image_file", "status", "reporter", "bike_id", "description", "report_id"]:
        if normalized.get(key) == "":
            normalized[key] = None
    for key in ["outside_zone", "toppled", "faulty"]:
        normalized[key] = parse_csv_bool(normalized.get(key, False))
    for key in ["reward_granted"]:
        normalized[key] = parse_csv_bool(normalized.get(key, False))
    for key in ["location_lat", "location_lng", "location_accuracy"]:
        normalized[key] = parse_csv_float(normalized.get(key))
    if not normalized.get("status"):
        normalized["status"] = "pending"
    return normalized


def load_reports_from_csv() -> None:
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    configure_csv_field_size_limit()
    if not REPORTS_CSV_PATH.exists():
        return

    with REPORTS_CSV_PATH.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        reports = [normalize_report_record(row) for row in reader]

    migrated = False
    for report in reports:
        if report.get("image") and not report.get("image_file"):
            report_id = report.get("report_id") or f"RPT-{uuid4().hex[:8].upper()}"
            report["report_id"] = report_id
            image_file = save_report_image(report_id, report["image"])
            if image_file:
                report["image_file"] = image_file
                report["image"] = load_report_image_data(image_file)
                migrated = True
        elif report.get("image_file"):
            report["image"] = load_report_image_data(report["image_file"])

    REPORTS.clear()
    REPORTS.extend(reports)
    if migrated:
        save_reports_to_csv()


def save_reports_to_csv() -> None:
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    with REPORTS_CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_CSV_FIELDS)
        writer.writeheader()
        for report in REPORTS:
            row = {field: csv_value(report.get(field)) for field in REPORT_CSV_FIELDS}
            row["image"] = ""
            writer.writerow(row)


load_reports_from_csv()


def is_dev_login_mode() -> bool:
    load_env_file()
    return os.getenv("DEV_LOGIN_MODE", "0").strip() == "1"


def get_reward_vouchers_for_user(user: str) -> List[str]:
    user_key = user.lower().strip()
    return [
        str(report.get("reward_voucher"))
        for report in REPORTS
        if report.get("reporter", "").lower() == user_key and report.get("reward_granted") and report.get("reward_voucher")
    ]


def sync_user_reward_state(account: dict) -> None:
    user_key = account["user"].lower().strip()
    approved_rewards = get_reward_vouchers_for_user(user_key)
    used_rewards = list(account.get("used_rewards", []))
    used_counter = Counter(used_rewards)

    claimed_rewards: List[str] = []
    for voucher in approved_rewards:
        if used_counter[voucher] > 0:
            used_counter[voucher] -= 1
            continue
        claimed_rewards.append(voucher)

    account["claimed_rewards"] = claimed_rewards
    account["used_rewards"] = used_rewards


def next_reward_voucher_for_user(user: str) -> str:
    approved_count = len(get_reward_vouchers_for_user(user))
    return AVAILABLE_VOUCHERS[approved_count % len(AVAILABLE_VOUCHERS)]


def ensure_report_ids():
    for index, report in enumerate(REPORTS, start=1):
        if not report.get("report_id"):
            report["report_id"] = f"RPT-{index:06d}"


def load_env_file():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def build_proxy_users():
    load_env_file()
    users = {}
    for role in ["admin", "maintenance", "user"]:
        email = os.getenv(f"{role.upper()}_EMAIL")
        password = os.getenv(f"{role.upper()}_PASSWORD")
        if email and password:
            users[email.lower().strip()] = {"password": password, "role": role}

    if not users:
        users = {
            "admin@bikepatrol.test": {"password": "admin123", "role": "admin"},
            "maintenance@bikepatrol.test": {"password": "maint123", "role": "maintenance"},
            "user@bikepatrol.test": {"password": "user123", "role": "user"},
        }
    return users

PROXY_USERS = build_proxy_users()
AVAILABLE_VOUCHERS = [
    "CDC Food Voucher",
    "CDC Shopping Discount",
    "CDC Transport Subsidy",
    "CDC Bike Care Coupon"
]


def get_user_account(user: str):
    user_key = user.lower().strip()
    role = PROXY_USERS.get(user_key, {}).get("role", "user")
    account = USER_ACCOUNTS.setdefault(user_key, {
        "user": user,
        "display_name": user,
        "phone_number": "",
        "role": role,
        "reports": [],
        "parking_points": 0,
        "help_events": [],
        "claimed_rewards": [],
        "used_rewards": [],
        "profile_photo": None,
        "settings": {
            "theme": "light",
            "font_size": "medium",
        },
    })
    account.setdefault("display_name", user)
    account.setdefault("phone_number", "")
    account.setdefault("profile_photo", None)
    account.setdefault("settings", {"theme": "light", "font_size": "medium"})
    account["user"] = user
    account["role"] = role
    return account


def validate_session_token(token: Optional[str]):
    if not token:
        raise HTTPException(status_code=401, detail="Authorization token is required.")
    if token.startswith("Bearer "):
        token = token.split(" ", 1)[1]
    user_key = SESSIONS.get(token)
    if not user_key:
        raise HTTPException(status_code=401, detail="Invalid or expired session token.")
    return user_key


def get_current_user(authorization: Optional[str] = Header(None)):
    return validate_session_token(authorization)


def build_user_summary(user: str):
    account = get_user_account(user)
    user_reports = [report for report in REPORTS if report.get("reporter", "").lower() == user.lower()]
    sync_user_reward_state(account)
    return {
        "user": account["user"],
        "display_name": account.get("display_name", account["user"]),
        "phone_number": account.get("phone_number", ""),
        "role": account["role"],
        "parking_points": account["parking_points"],
        "settings": account.get("settings", {"theme": "light", "font_size": "medium"}),
        "profile_photo": account.get("profile_photo"),
        "total_reports": len(user_reports),
        "total_help_events": len(account["help_events"]),
        "claimed_rewards": account["claimed_rewards"],
        "used_rewards": account.get("used_rewards", []),
        "recent_reports": user_reports[-10:],
        "recent_help_events": account["help_events"][-10:],
    }

@app.get("/api/status")
def status():
    ensure_report_ids()
    pending_reports = [report for report in REPORTS if report.get("status", "pending") == "pending"]
    completed_reports = [report for report in REPORTS if report.get("status") == "completed"]
    return {
        "app_name": "Bike Patrol Rewards",
        "dev_login_mode": is_dev_login_mode(),
        "report_count": len(REPORTS),
        "total_reports": len(REPORTS),
        "pending_reports": pending_reports,
        "completed_reports": completed_reports,
        "reward_limit_per_day": REWARD_LIMIT_PER_DAY,
        "available_vouchers": AVAILABLE_VOUCHERS,
        "proxy_accounts": [
            {"user": user, "role": info["role"]}
            for user, info in PROXY_USERS.items()
        ],
    }

@app.get("/api/reports", response_model=ReportSummary)
def get_reports():
    ensure_report_ids()
    pending_reports = [report for report in REPORTS if report.get("status", "pending") == "pending"]
    completed_reports = [report for report in REPORTS if report.get("status") == "completed"]
    return {
        "total_reports": len(REPORTS),
        "recent_reports": REPORTS[-10:],
        "all_reports": REPORTS,
        "pending_reports": pending_reports,
        "completed_reports": completed_reports,
    }

@app.get("/api/user-reports")
def user_reports(authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    reports = [report for report in REPORTS if report.get("reporter", "").lower() == current_user_key.lower()]
    return {"reports": reports}

@app.post("/api/reports")
def submit_report(
    authorization: Optional[str] = Header(None),
    reporter: str = Form(...),
    bike_id: str = Form(...),
    issue_type: str = Form(...),
    description: str = Form(...),
    location_text: Optional[str] = Form(None),
    location_address: Optional[str] = Form(None),
    location_lat: Optional[float] = Form(None),
    location_lng: Optional[float] = Form(None),
    location_accuracy: Optional[float] = Form(None),
    outside_zone: bool = Form(False),
    toppled: bool = Form(False),
    faulty: bool = Form(False),
    image: UploadFile = File(...),
):
    submitted_by = reporter.strip()
    if authorization:
        current_user_key = validate_session_token(authorization)
        current_account = get_user_account(current_user_key)
        submitted_by = current_account["user"]

    ensure_report_ids()
    report_id = f"RPT-{uuid4().hex[:8].upper()}"

    image_data = None
    image_file = None
    if image:
        content = image.file.read()
        encoded_data = base64.b64encode(content).decode("utf-8")
        image_data = f"data:{image.content_type};base64,{encoded_data}"
        image_file = save_report_image(report_id, image_data, image.content_type)
    
    normalized_location_text = location_text or format_location_text(location_lat, location_lng, location_accuracy)
    normalized_location_address = location_address or build_location_address(location_lat, location_lng, location_accuracy)
    ai_summary = analyze_report_image_with_llm(
        image_data,
        bike_id,
        issue_type,
        description,
        normalized_location_text,
        normalized_location_address,
    )
    
    report_dict = {
        "report_id": report_id,
        "reporter": submitted_by,
        "bike_id": bike_id,
        "issue_type": issue_type,
        "description": description,
        "location_text": normalized_location_text,
        "location_address": normalized_location_address,
        "location_lat": location_lat,
        "location_lng": location_lng,
        "location_accuracy": location_accuracy,
        "outside_zone": outside_zone,
        "toppled": toppled,
        "faulty": faulty,
        "image": image_data,
        "image_file": image_file,
        "ai_summary": ai_summary,
        "status": "pending",
        "reviewed_by": None,
        "review_notes": None,
        "review_action": None,
        "reward_granted": False,
        "reward_voucher": None,
    }
    REPORTS.append(report_dict)
    save_reports_to_csv()
    return {
        "message": "Report received. Maintenance team alerted.",
        "report": report_dict,
        "user_summary": build_user_summary(submitted_by),
    }


@app.get("/api/reverse-geocode")
def reverse_geocode_api(lat: float, lng: float, accuracy: Optional[float] = None):
    location_address = build_location_address(lat, lng, accuracy)
    location_text = format_location_text(lat, lng, accuracy)
    return {
        "location_address": location_address,
        "location_text": location_text,
        "latitude": lat,
        "longitude": lng,
        "accuracy": accuracy,
    }


@app.post("/api/reports/{report_id}/review")
def review_report(
    report_id: str,
    action: str = Form(...),
    notes: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
):
    ensure_report_ids()
    current_user_key = validate_session_token(authorization)
    account = get_user_account(current_user_key)
    if account["role"] not in ["admin", "maintenance"]:
        raise HTTPException(status_code=403, detail="Only maintenance staff can review reports.")

    report = next((item for item in REPORTS if item.get("report_id") == report_id), None)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    normalized_action = action.strip().lower()
    if normalized_action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="Review action must be approve or reject.")

    report["status"] = "completed"
    report["reviewed_by"] = current_user_key
    report["review_notes"] = (notes or "").strip() or None
    report["review_action"] = normalized_action
    if normalized_action == "approve" and not report.get("reward_granted"):
        reporter_account = get_user_account(report["reporter"])
        reward_voucher = next_reward_voucher_for_user(report["reporter"])
        report["reward_granted"] = True
        report["reward_voucher"] = reward_voucher
        sync_user_reward_state(reporter_account)
    save_reports_to_csv()
    action_word = "approved" if normalized_action == "approve" else "rejected"

    return {
        "message": f"Report {action_word} successfully.",
        "report": report,
    }

@app.post("/api/parking-help")
def parking_help(help_request: HelpRequest):
    account = get_user_account(help_request.user)
    today = date.today().isoformat()
    event = {
        "bike_id": help_request.bike_id,
        "notes": help_request.notes or "Helped keep the bicycle inside the assigned parking spot.",
        "date": today,
    }
    account["help_events"].append(event)
    account["parking_points"] += 1
    return {
        "message": "Parking help logged. You earned a Parking Point.",
        "parking_points": account["parking_points"],
        "help_event": event,
    }

@app.post("/api/login")
def login(request: LoginRequest):
    user_key = request.user.lower().strip()
    proxy = PROXY_USERS.get(user_key)
    if not proxy or proxy["password"] != request.password:
        raise HTTPException(status_code=401, detail="Invalid credentials for proxy account.")
    token = str(uuid4())
    SESSIONS[token] = user_key
    account = get_user_account(request.user)
    return {
        "message": "Login successful.",
        "token": token,
        "user": request.user,
        "role": account["role"],
        "account": build_user_summary(request.user),
    }


@app.post("/api/dev-login/{role}")
def dev_login(role: str):
    if not is_dev_login_mode():
        raise HTTPException(status_code=403, detail="Dev login mode is disabled.")

    normalized_role = role.strip().lower()
    if normalized_role not in ["admin", "maintenance", "user"]:
        raise HTTPException(status_code=400, detail="Unknown dev login role.")

    account_entry = next((item for item in PROXY_USERS.items() if item[1]["role"] == normalized_role), None)
    if not account_entry:
        raise HTTPException(status_code=404, detail="Configured dev account not found.")

    user_key, proxy = account_entry
    token = str(uuid4())
    SESSIONS[token] = user_key
    account = get_user_account(user_key)
    return {
        "message": "Dev login successful.",
        "token": token,
        "user": account["user"],
        "role": account["role"],
        "account": build_user_summary(account["user"]),
    }

@app.post("/api/register")
def register(request: RegisterRequest):
    user_key = request.user.lower().strip()
    if user_key in PROXY_USERS:
        raise HTTPException(status_code=400, detail="Account already exists.")
    PROXY_USERS[user_key] = {
        "password": request.password,
        "role": "user",
    }
    account = get_user_account(request.user)
    token = str(uuid4())
    SESSIONS[token] = user_key
    return {
        "message": "Account created successfully.",
        "token": token,
        "user": request.user,
        "role": account["role"],
        "account": build_user_summary(request.user),
    }

@app.post("/api/logout")
def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        SESSIONS.pop(token, None)
    return {"message": "Logged out."}

@app.post("/api/change-password")
def change_password(request: PasswordChangeRequest, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    proxy = PROXY_USERS.get(current_user_key)
    if not proxy or proxy["password"] != request.current_password:
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    if not request.new_password.strip():
        raise HTTPException(status_code=400, detail="New password cannot be empty.")
    proxy["password"] = request.new_password
    return {"message": "Password changed successfully."}

@app.post("/api/reset-password")
def reset_password(request: PasswordResetRequest):
    user_key = request.user.lower().strip()
    proxy = PROXY_USERS.get(user_key)
    if not proxy:
        raise HTTPException(status_code=404, detail="User not found.")
    if not request.new_password.strip():
        raise HTTPException(status_code=400, detail="New password cannot be empty.")
    proxy["password"] = request.new_password
    return {"message": "Password reset successfully (demo mode)."}

@app.post("/api/account-profile")
def account_profile(request: ProfileUpdateRequest, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    account = get_user_account(current_user_key)
    next_email = (request.email or account["user"]).strip()
    next_phone = (request.phone_number or "").strip()
    next_display_name = (request.display_name or account.get("display_name") or account["user"]).strip()

    if not next_email:
        raise HTTPException(status_code=400, detail="Email cannot be empty.")

    new_user_key = next_email.lower()
    existing_proxy = PROXY_USERS.get(current_user_key)
    if not existing_proxy:
        raise HTTPException(status_code=404, detail="Current account could not be found.")

    if new_user_key != current_user_key and new_user_key in PROXY_USERS:
        raise HTTPException(status_code=400, detail="That email is already in use.")

    if new_user_key != current_user_key:
        PROXY_USERS[new_user_key] = PROXY_USERS.pop(current_user_key)
        account = USER_ACCOUNTS.pop(current_user_key, account)
        USER_ACCOUNTS[new_user_key] = account
        for token, user_key in list(SESSIONS.items()):
            if user_key == current_user_key:
                SESSIONS[token] = new_user_key

    account["user"] = next_email
    account["display_name"] = next_display_name
    account["phone_number"] = next_phone
    return {
        "message": "Profile updated successfully.",
        "account": build_user_summary(next_email),
    }

@app.post("/api/account-settings")
def account_settings(request: SettingsRequest, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    account = get_user_account(current_user_key)
    if request.display_name:
        account["display_name"] = request.display_name
    if request.theme:
        account["settings"]["theme"] = request.theme
    if request.font_size:
        account["settings"]["font_size"] = request.font_size
    return {"message": "Settings saved.", "settings": account["settings"], "display_name": account["display_name"]}

@app.post("/api/profile-photo")
def profile_photo(image: UploadFile = File(...), authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    account = get_user_account(current_user_key)
    content = image.file.read()
    encoded_data = base64.b64encode(content).decode("utf-8")
    encoded = f"data:{image.content_type};base64,{encoded_data}"
    account["profile_photo"] = encoded
    return {"message": "Profile photo updated.", "profile_photo": encoded}

@app.get("/api/me")
def current_user(authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    return build_user_summary(current_user_key)

@app.get("/api/proxy-accounts")
def proxy_accounts():
    return [{"user": user, "role": info["role"]} for user, info in PROXY_USERS.items()]

@app.get("/api/users/{user}")
def user_summary(user: str, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    requested_user_key = user.lower().strip()
    current_account = get_user_account(current_user_key)
    if current_user_key != requested_user_key and current_account["role"] not in ["admin", "maintenance"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to view this account.")
    return build_user_summary(user)

@app.post("/api/redeem-parking-reward")
def redeem_parking_reward(request: ParkingRedeemRequest):
    account = get_user_account(request.user)
    if account["parking_points"] < request.points:
        raise HTTPException(status_code=400, detail="Not enough parking points to redeem this reward.")

    account["parking_points"] -= request.points
    voucher = request.reward_name or "Parking Helper Reward"
    account["claimed_rewards"].append(voucher)
    return {
        "message": "Parking reward claimed outside the daily voucher limit.",
        "voucher": voucher,
        "parking_points": account["parking_points"],
        "claimed_rewards": account["claimed_rewards"],
    }

@app.post("/api/claim-reward")
def claim_reward(request: RewardRequest):
    raise HTTPException(status_code=403, detail="Rewards are only granted after maintenance approves a report.")

@app.post("/api/use-reward")
def use_reward(request: UseRewardRequest, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    account = get_user_account(current_user_key)
    reward = request.reward
    if reward not in account["claimed_rewards"]:
        raise HTTPException(status_code=400, detail="This reward has not been claimed or is already used.")
    account["claimed_rewards"].remove(reward)
    account.setdefault("used_rewards", []).append(reward)
    return {
        "message": f"Reward '{reward}' used successfully.",
        "used_rewards": account["used_rewards"],
        "claimed_rewards": account["claimed_rewards"],
    }

@app.get("/api/rewards/{user}")
def reward_status(user: str):
    account = get_user_account(user)
    sync_user_reward_state(account)
    return {
        "user": user,
        "claimed_today": len(get_reward_vouchers_for_user(user)),
        "limit": REWARD_LIMIT_PER_DAY,
        "claimed_vouchers": get_reward_vouchers_for_user(user),
        "parking_points": account["parking_points"],
        "help_events": account["help_events"],
        "claimed_rewards": account["claimed_rewards"],
        "used_rewards": account.get("used_rewards", []),
    }
