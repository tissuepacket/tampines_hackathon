from datetime import date
from enum import Enum
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from pathlib import Path
from uuid import uuid4
import os
import base64
import json
import urllib.error
import urllib.request

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
    return {
        "user": account["user"],
        "display_name": account.get("display_name", account["user"]),
        "phone_number": account.get("phone_number", ""),
        "role": account["role"],
        "parking_points": account["parking_points"],
        "settings": account.get("settings", {"theme": "light", "font_size": "medium"}),
        "profile_photo": account.get("profile_photo"),
        "total_reports": len(account["reports"]),
        "total_help_events": len(account["help_events"]),
        "claimed_rewards": account["claimed_rewards"],
        "used_rewards": account.get("used_rewards", []),
        "recent_reports": account["reports"][-10:],
        "recent_help_events": account["help_events"][-10:],
    }

@app.get("/api/status")
def status():
    ensure_report_ids()
    pending_reports = [report for report in REPORTS if report.get("status", "pending") == "pending"]
    completed_reports = [report for report in REPORTS if report.get("status") == "completed"]
    return {
        "app_name": "Bike Patrol Rewards",
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
    account = get_user_account(current_user_key)
    return {"reports": account["reports"]}

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

    image_data = None
    if image:
        content = image.file.read()
        encoded_data = base64.b64encode(content).decode("utf-8")
        image_data = f"data:{image.content_type};base64,{encoded_data}"
    
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
    ensure_report_ids()
    report_id = f"RPT-{uuid4().hex[:8].upper()}"
    
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
        "ai_summary": ai_summary,
        "status": "pending",
        "reviewed_by": None,
        "review_notes": None,
        "review_action": None,
    }
    REPORTS.append(report_dict)
    account = get_user_account(submitted_by)
    account["reports"].append(report_dict)
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
    today = date.today().isoformat()
    record = reward_store.setdefault(request.user.lower(), {"date": today, "count": 0, "claimed": []})
    if record["date"] != today:
        record["date"] = today
        record["count"] = 0
        record["claimed"] = []

    if record["count"] >= REWARD_LIMIT_PER_DAY:
        raise HTTPException(status_code=429, detail=f"Daily reward limit reached ({REWARD_LIMIT_PER_DAY}).")

    voucher = AVAILABLE_VOUCHERS[record["count"] % len(AVAILABLE_VOUCHERS)]
    record["count"] += 1
    record["claimed"].append(voucher)
    account = get_user_account(request.user)
    account["claimed_rewards"].append(voucher)

    return {
        "message": "Reward claimed successfully.",
        "voucher": voucher,
        "claimed_today": record["count"],
        "limit": REWARD_LIMIT_PER_DAY,
        "parking_points": account["parking_points"],
    }

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
    record = reward_store.get(user.lower())
    account = get_user_account(user)
    return {
        "user": user,
        "claimed_today": record["count"] if record else 0,
        "limit": REWARD_LIMIT_PER_DAY,
        "claimed_vouchers": record["claimed"] if record else [],
        "parking_points": account["parking_points"],
        "help_events": account["help_events"],
        "claimed_rewards": account["claimed_rewards"],
        "used_rewards": account.get("used_rewards", []),
    }
