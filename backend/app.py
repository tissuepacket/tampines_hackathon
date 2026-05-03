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
    ai_alignment_status: Optional[str] = Field(None, title="Whether the image aligns with the submitted report")
    ai_issue_match: Optional[bool] = Field(None, title="Whether the submitted issue type matches the image")
    ai_detected_issue: Optional[str] = Field(None, title="Issue type most likely shown by the image")
    ai_confidence: Optional[float] = Field(None, title="Model confidence in the AI assessment")
    status: Optional[str] = Field("pending", title="Report review status")
    reviewed_by: Optional[str] = Field(None, title="Report reviewed by")
    review_notes: Optional[str] = Field(None, title="Review notes")
    review_action: Optional[str] = Field(None, title="Review action")

class RewardRequest(BaseModel):
    user: str = Field(..., title="User name or email")
    action: str = Field(..., title="Reward action requested")

class UseRewardRequest(BaseModel):
    reward: str = Field(..., title="Reward identifier to redeem")

class HelpRequest(BaseModel):
    user: str = Field(..., title="User name or email")
    bike_id: str = Field(..., title="Bike identifier")
    notes: Optional[str] = Field(None, title="Optional notes")
    mission_id: Optional[str] = Field(None, title="Optional return-and-earn mission identifier")
    location_lat: Optional[float] = Field(None, title="Latitude where the help was completed")
    location_lng: Optional[float] = Field(None, title="Longitude where the help was completed")
    location_address: Optional[str] = Field(None, title="Resolved location address")
    before_image: Optional[str] = Field(None, title="Optional before photo as a data URL")
    after_image: Optional[str] = Field(None, title="Optional after photo as a data URL")

class RideActivityRequest(BaseModel):
    bike_id: str = Field(..., title="Bike identifier")
    notes: Optional[str] = Field(None, title="Optional notes")
    location_lat: Optional[float] = Field(None, title="Latitude for this ride or parking event")
    location_lng: Optional[float] = Field(None, title="Longitude for this ride or parking event")
    location_accuracy: Optional[float] = Field(None, title="Location accuracy in meters")
    location_address: Optional[str] = Field(None, title="Resolved location address")

class ScanRentalRequest(BaseModel):
    bike_id: Optional[str] = Field(None, title="Bike identifier from the QR code")

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

class AdminAccountUpdateRequest(BaseModel):
    role: Optional[str] = Field(None, title="Updated role")
    password: Optional[str] = Field(None, title="Updated password")
    display_name: Optional[str] = Field(None, title="Updated display name")
    phone_number: Optional[str] = Field(None, title="Updated phone number")


class AdminAccountCreateRequest(BaseModel):
    user: str = Field(..., title="New account email")
    role: str = Field("user", title="Role for the new account")
    password: str = Field(..., title="Initial password")
    display_name: Optional[str] = Field(None, title="Display name")
    phone_number: Optional[str] = Field(None, title="Phone number")


class StreakResetRequest(BaseModel):
    reason: Optional[str] = Field("Illegal parking suspected", title="Reason for resetting the streak")

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
STREAK_STEP = 5
STREAK_BONUS = 0.25
DUMMY_BIKE_ID = "BK-101"
SPACE_RECOVERED_PER_BIKE = 1.8
CORRECTIVE_ACTION_BASE_POINTS = 70
MISSION_COMPLETION_BONUS = 40
RECOVERY_ACTION_BONUS = 35
HOTSPOT_GUIDANCE_RADIUS = 0.0026
HOTSPOT_CLUSTER_THRESHOLD = 0.0022
DEMO_LEADERBOARD_PLAYERS = [
    {"user": "kayla@bikepatrol.test", "display_name": "Kayla Drift", "score": 842, "good_action_streak": 17, "correction_missions_completed": 9, "help_events": 14},
    {"user": "nabil@bikepatrol.test", "display_name": "Nabil North", "score": 735, "good_action_streak": 13, "correction_missions_completed": 8, "help_events": 12},
    {"user": "clarice@bikepatrol.test", "display_name": "Clarice Cleanlane", "score": 648, "good_action_streak": 11, "correction_missions_completed": 7, "help_events": 11},
    {"user": "darren@bikepatrol.test", "display_name": "Darren Dock", "score": 582, "good_action_streak": 10, "correction_missions_completed": 6, "help_events": 10},
    {"user": "amira@bikepatrol.test", "display_name": "Amira Alley", "score": 503, "good_action_streak": 9, "correction_missions_completed": 5, "help_events": 9},
    {"user": "josh@bikepatrol.test", "display_name": "Josh Junction", "score": 446, "good_action_streak": 8, "correction_missions_completed": 5, "help_events": 8},
]
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
    "ai_alignment_status",
    "ai_issue_match",
    "ai_detected_issue",
    "ai_confidence",
    "status",
    "reviewed_by",
    "review_notes",
    "review_action",
    "reward_granted",
    "reward_voucher",
    "points_awarded",
    "image_file",
]


def get_llm_token() -> Optional[str]:
    load_env_file()
    return (os.getenv("API_KEY") or "").strip() or None


def get_llm_model() -> str:
    load_env_file()
    return (os.getenv("MODEL") or "").strip() or "gpt-4.1-mini"


def extract_response_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"].strip()

    for output_item in payload.get("output", []):
        for content_item in output_item.get("content", []):
            text = content_item.get("text")
            if text and isinstance(text, str):
                return text.strip()
    return ""


def normalize_issue_type(issue_type: Optional[str]) -> str:
    normalized = str(issue_type or "general").strip().lower().replace(" ", "_")
    if normalized not in {item.value for item in IssueType}:
        return "general"
    return normalized


def parse_ai_analysis(raw_text: str, submitted_issue_type: str) -> dict:
    fallback = {
        "summary": raw_text.strip() if raw_text else None,
        "alignment_status": "unclear",
        "issue_match": None,
        "detected_issue": normalize_issue_type(submitted_issue_type),
        "confidence": None,
    }
    if not raw_text:
        return fallback
    try:
        parsed = json.loads(raw_text)
    except ValueError:
        return fallback

    alignment_status = str(parsed.get("alignment_status") or "unclear").strip().lower()
    if alignment_status not in {"aligned", "issue_mismatch", "not_aligned", "unclear"}:
        alignment_status = "unclear"

    detected_issue = normalize_issue_type(parsed.get("detected_issue") or submitted_issue_type)
    issue_match = parsed.get("issue_match")
    if isinstance(issue_match, str):
        issue_match = issue_match.strip().lower() == "true"
    if not isinstance(issue_match, bool):
        issue_match = None

    confidence = parsed.get("confidence")
    try:
        confidence = round(float(confidence), 2) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None

    summary = str(parsed.get("summary") or "").strip() or fallback["summary"]
    return {
        "summary": summary,
        "alignment_status": alignment_status,
        "issue_match": issue_match,
        "detected_issue": detected_issue,
        "confidence": confidence,
    }


def analyze_report_image_with_llm(
    image_data_url: str,
    bike_id: str,
    issue_type: str,
    description: str,
    location_text: Optional[str] = None,
    location_address: Optional[str] = None,
) -> Optional[dict]:
    token = get_llm_token()
    if not token:
        return None
    model = get_llm_model()

    prompt = (
        "You are reviewing a bicycle issue report. "
        "Return ONLY valid JSON with these keys: "
        "summary, alignment_status, issue_match, detected_issue, confidence. "
        "alignment_status must be one of: aligned, issue_mismatch, not_aligned, unclear. "
        "issue_match must be true or false. "
        "detected_issue must be one of: illegal_parking, toppled, faulty, general, others. "
        "confidence must be a number from 0 to 1. "
        "Use aligned when the image matches the report and the issue type fits. "
        "Use issue_mismatch when the image shows a real bike problem but the submitted issue type is wrong. "
        "Use not_aligned when the image does not support the report or appears false. "
        "Use unclear when the image is too ambiguous. "
        f"Report details: bike_id={bike_id}, issue_type={issue_type}, description={description}."
        + (f" Report location: {location_text}." if location_text else "")
        + (f" Rough address: {location_address}." if location_address else "")
    )
    payload = {
        "model": model,
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

    raw_text = extract_response_text(response_payload)
    return parse_ai_analysis(raw_text, issue_type) if raw_text else None


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


def parse_csv_int(value: Optional[str]) -> int:
    if value is None or str(value).strip() == "":
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


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
    normalized["issue_type"] = normalize_issue_type(normalized.get("issue_type"))
    if normalized.get("ai_detected_issue") in (None, ""):
        normalized["ai_detected_issue"] = None
    else:
        normalized["ai_detected_issue"] = normalize_issue_type(normalized.get("ai_detected_issue"))
    if normalized.get("ai_alignment_status") not in {"aligned", "issue_mismatch", "not_aligned", "unclear"}:
        normalized["ai_alignment_status"] = None
    issue_match = normalized.get("ai_issue_match")
    if issue_match in ("", None):
        normalized["ai_issue_match"] = None
    else:
        normalized["ai_issue_match"] = parse_csv_bool(issue_match)
    for key in ["outside_zone", "toppled", "faulty"]:
        normalized[key] = parse_csv_bool(normalized.get(key, False))
    for key in ["reward_granted"]:
        normalized[key] = parse_csv_bool(normalized.get(key, False))
    for key in ["location_lat", "location_lng", "location_accuracy"]:
        normalized[key] = parse_csv_float(normalized.get(key))
    normalized["ai_confidence"] = parse_csv_float(normalized.get("ai_confidence"))
    normalized["points_awarded"] = parse_csv_int(normalized.get("points_awarded"))
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


def points_for_issue(issue_type: Optional[str]) -> int:
    points_table = {
        "illegal_parking": 80,
        "faulty": 110,
        "toppled": 140,
        "others": 60,
        "general": 60,
    }
    return points_table.get(str(issue_type or "general"), 60)


def reward_catalog() -> List[dict]:
    return [
        {"id": "mcd-fries", "name": "Fries Treat", "cost": 120, "category": "Food", "description": "A snack-sized reward for quick point redemptions."},
        {"id": "coffee-run", "name": "Coffee Run", "cost": 180, "category": "Drinks", "description": "Redeem a drink-style perk after a few successful reports."},
        {"id": "ride-credit", "name": "Ride Credit", "cost": 260, "category": "Transport", "description": "Convert points into transport credit for your next trip."},
        {"id": "community-bonus", "name": "Community Bonus Pack", "cost": 420, "category": "Featured", "description": "A bigger reward tier for regular contributors."},
    ]


def get_catalog_reward(reward_id: str) -> Optional[dict]:
    return next((item for item in reward_catalog() if item["id"] == reward_id), None)


def streak_multiplier_for_count(streak_count: int) -> float:
    return round(1 + (streak_count // STREAK_STEP) * STREAK_BONUS, 2)


def next_streak_target(streak_count: int) -> int:
    return ((streak_count // STREAK_STEP) + 1) * STREAK_STEP


def ensure_points_fields(account: dict) -> None:
    account.setdefault("report_points_earned", 0)
    account.setdefault("help_points_earned", 0)
    account.setdefault("points_balance", 0)
    account.setdefault("lifetime_points", 0)
    account.setdefault("points_spent", 0)
    account.setdefault("points_history", [])
    account.setdefault("good_action_streak", 0)
    account.setdefault("streak_multiplier", 1.0)
    account.setdefault("usage_points_earned", 0)
    account.setdefault("ride_history", [])
    account.setdefault("parking_history", [])
    account.setdefault("active_bike_id", None)
    account.setdefault("rental_history", [])
    account.setdefault("parking_incidents", [])
    account.setdefault("space_recovered_estimate", 0.0)
    account.setdefault("correction_missions_completed", 0)
    account.setdefault("recent_guidance_checks", [])
    account.setdefault("false_submission_offenses", 0)
    account.setdefault("false_submission_warning_issued", False)


def points_for_report(report: dict) -> int:
    awarded = parse_csv_int(report.get("points_awarded"))
    if awarded:
        return awarded
    if report.get("reward_granted"):
        return points_for_issue(report.get("issue_type"))
    return 0


def sync_user_points_state(account: dict) -> None:
    ensure_points_fields(account)
    user_key = account["user"].lower().strip()
    derived_report_points = sum(
        points_for_report(report)
        for report in REPORTS
        if report.get("reporter", "").lower() == user_key and report.get("status") == "completed"
    )
    if int(account.get("report_points_earned", 0)) < derived_report_points:
        account["report_points_earned"] = derived_report_points
    report_points = int(account.get("report_points_earned", 0))
    help_points = int(account.get("help_points_earned", 0))
    usage_points = int(account.get("usage_points_earned", 0))
    points_spent = int(account.get("points_spent", 0))
    lifetime_points = report_points + help_points + usage_points
    account["lifetime_points"] = lifetime_points
    account["points_balance"] = max(lifetime_points - points_spent, 0)
    account["streak_multiplier"] = streak_multiplier_for_count(int(account.get("good_action_streak", 0)))


def award_points_for_good_action(account: dict, base_points: int, label: str, action_date: str, bucket_key: str) -> tuple[int, float, int]:
    ensure_points_fields(account)
    account["good_action_streak"] = int(account.get("good_action_streak", 0)) + 1
    multiplier = streak_multiplier_for_count(account["good_action_streak"])
    awarded_points = int(round(base_points * multiplier))
    account[bucket_key] = int(account.get(bucket_key, 0)) + awarded_points
    account["streak_multiplier"] = multiplier
    sync_user_points_state(account)
    account["points_history"].append({
        "type": "earn",
        "label": label,
        "points": awarded_points,
        "base_points": base_points,
        "multiplier": multiplier,
        "streak": account["good_action_streak"],
        "date": action_date,
    })
    return awarded_points, multiplier, account["good_action_streak"]


def reset_streak(account: dict, reason: str, action_date: str) -> None:
    ensure_points_fields(account)
    account["good_action_streak"] = 0
    account["streak_multiplier"] = 1.0
    sync_user_points_state(account)
    account["points_history"].append({
        "type": "reset",
        "label": "Streak reset",
        "points": 0,
        "reason": reason,
        "date": action_date,
    })


def register_false_submission(account: dict, action_date: str) -> tuple[int, str]:
    ensure_points_fields(account)
    account["false_submission_offenses"] = int(account.get("false_submission_offenses", 0)) + 1
    offense_count = account["false_submission_offenses"]
    if offense_count == 1:
        account["false_submission_warning_issued"] = True
        account["points_history"].append({
            "type": "warning",
            "label": "False submission warning",
            "points": 0,
            "reason": "Image did not align with the submitted report.",
            "date": action_date,
        })
        return offense_count, "This is their first false-submission offense, so they were given a warning."

    reset_streak(account, "Repeated false submission", action_date)
    account["points_history"].append({
        "type": "incident",
        "label": "Repeated false submission",
        "points": 0,
        "reason": "Image did not align with the submitted report.",
        "date": action_date,
    })
    return offense_count, "This is a repeat false-submission offense, so their streak was reset."


def get_report_reward_base_points(report: dict) -> tuple[int, Optional[str]]:
    alignment_status = report.get("ai_alignment_status")
    detected_issue = normalize_issue_type(report.get("ai_detected_issue") or report.get("issue_type"))
    submitted_issue = normalize_issue_type(report.get("issue_type"))
    if alignment_status == "issue_mismatch" and detected_issue != submitted_issue:
        reduced_points = max(int(round(points_for_issue(detected_issue) * 0.65)), 35)
        return reduced_points, detected_issue
    return points_for_issue(submitted_issue), None


def award_usage_points(
    account: dict,
    base_points: int,
    label: str,
    action_date: str,
    history_bucket: str,
    bike_id: str,
    notes: Optional[str] = None,
    location_lat: Optional[float] = None,
    location_lng: Optional[float] = None,
    location_accuracy: Optional[float] = None,
    location_address: Optional[str] = None,
) -> int:
    ensure_points_fields(account)
    awarded_points = int(base_points)
    account["usage_points_earned"] = int(account.get("usage_points_earned", 0)) + awarded_points
    sync_user_points_state(account)
    event = {
        "bike_id": bike_id,
        "points": awarded_points,
        "notes": notes or "",
        "date": action_date,
        "label": label,
        "location_lat": location_lat,
        "location_lng": location_lng,
        "location_accuracy": location_accuracy,
        "location_address": location_address,
    }
    account.setdefault(history_bucket, []).append(event)
    account["points_history"].append({
        "type": "earn",
        "label": label,
        "points": awarded_points,
        "date": action_date,
        "reason": "Mobility usage reward",
    })
    return awarded_points


def find_active_renter_for_bike(bike_id: str) -> Optional[dict]:
    normalized_bike_id = bike_id.strip().upper()
    for account in USER_ACCOUNTS.values():
        ensure_points_fields(account)
        if str(account.get("active_bike_id") or "").strip().upper() == normalized_bike_id:
            return account
    return None


def flag_illegal_parking_for_bike(bike_id: str, reason: str, action_date: str) -> Optional[dict]:
    renter_account = find_active_renter_for_bike(bike_id)
    if not renter_account:
        return None
    reset_streak(renter_account, reason, action_date)
    incident = {
        "bike_id": bike_id,
        "reason": reason,
        "date": action_date,
    }
    renter_account.setdefault("parking_incidents", []).append(incident)
    renter_account["points_history"].append({
        "type": "incident",
        "label": "Illegal parking flag",
        "points": 0,
        "reason": reason,
        "date": action_date,
    })
    return renter_account


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


def get_user_account(user: str):
    user_key = user.lower().strip()
    role = PROXY_USERS.get(user_key, {}).get("role", "user")
    account = USER_ACCOUNTS.setdefault(user_key, {
        "user": user,
        "display_name": user,
        "phone_number": "",
        "role": role,
        "reports": [],
        "help_events": [],
        "report_points_earned": 0,
        "help_points_earned": 0,
        "usage_points_earned": 0,
        "points_balance": 0,
        "lifetime_points": 0,
        "points_spent": 0,
        "points_history": [],
        "good_action_streak": 0,
        "streak_multiplier": 1.0,
        "ride_history": [],
        "parking_history": [],
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
    ensure_points_fields(account)
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
    sync_user_points_state(account)
    return {
        "user": account["user"],
        "display_name": account.get("display_name", account["user"]),
        "phone_number": account.get("phone_number", ""),
        "role": account["role"],
        "points_balance": account["points_balance"],
        "lifetime_points": account["lifetime_points"],
        "good_action_streak": account.get("good_action_streak", 0),
        "streak_multiplier": account.get("streak_multiplier", 1.0),
        "points_to_next_streak": max(next_streak_target(account.get("good_action_streak", 0)) - account.get("good_action_streak", 0), 0),
        "settings": account.get("settings", {"theme": "light", "font_size": "medium"}),
        "profile_photo": account.get("profile_photo"),
        "total_reports": len(user_reports),
        "total_help_events": len(account["help_events"]),
        "points_history": account.get("points_history", [])[-10:],
        "recent_reports": user_reports[-10:],
        "recent_help_events": account["help_events"][-10:],
        "recent_ride_history": account.get("ride_history", [])[-10:],
        "recent_parking_history": account.get("parking_history", [])[-10:],
        "active_bike_id": account.get("active_bike_id"),
        "parking_incidents": account.get("parking_incidents", [])[-10:],
        "space_recovered_estimate": round(float(account.get("space_recovered_estimate", 0.0)), 1),
        "correction_missions_completed": int(account.get("correction_missions_completed", 0)),
        "false_submission_offenses": int(account.get("false_submission_offenses", 0)),
    }


def build_admin_overview() -> dict:
    accounts = [get_user_account(user_key) for user_key in PROXY_USERS.keys()]
    user_accounts = [account for account in accounts if account["role"] == "user"]
    maintenance_accounts = [account for account in accounts if account["role"] == "maintenance"]
    accounts_needing_attention = [
        account for account in user_accounts
        if int(account.get("false_submission_offenses", 0)) > 0
        or len(account.get("parking_incidents", [])) > 0
        or int(account.get("good_action_streak", 0)) == 0
    ]
    top_contributor = None
    if user_accounts:
        ranked_users = sorted(
            user_accounts,
            key=lambda account: (
                int(account.get("help_points_earned", 0)) + int(account.get("report_points_earned", 0)),
                int(account.get("good_action_streak", 0)),
            ),
            reverse=True,
        )
        leader = ranked_users[0]
        top_contributor = {
            "user": leader["user"],
            "display_name": leader.get("display_name") or leader["user"],
            "points_balance": int(leader.get("points_balance", 0)),
            "good_action_streak": int(leader.get("good_action_streak", 0)),
        }

    return {
        "total_accounts": len(accounts),
        "user_accounts": len(user_accounts),
        "maintenance_accounts": len(maintenance_accounts),
        "pending_reports": len([report for report in REPORTS if report.get("status", "pending") == "pending"]),
        "accounts_needing_attention": len(accounts_needing_attention),
        "top_contributor": top_contributor,
    }


def build_admin_account_snapshot(user_key: str) -> dict:
    account = get_user_account(user_key)
    sync_user_points_state(account)
    recent_reports = [report for report in REPORTS if report.get("reporter", "").lower() == user_key.lower()]
    parking_incidents = account.get("parking_incidents", [])
    false_submission_offenses = int(account.get("false_submission_offenses", 0))
    needs_attention = (
        false_submission_offenses > 0
        or len(parking_incidents) > 0
        or str(account.get("active_bike_id") or "").strip() != ""
    )
    return {
        "user": account.get("user", user_key),
        "role": account.get("role", "user"),
        "display_name": account.get("display_name", user_key),
        "phone_number": account.get("phone_number", ""),
        "points_balance": int(account.get("points_balance", 0)),
        "lifetime_points": int(account.get("lifetime_points", 0)),
        "good_action_streak": int(account.get("good_action_streak", 0)),
        "streak_multiplier": float(account.get("streak_multiplier", 1.0)),
        "helpful_actions": len(account.get("help_events", [])),
        "correction_missions_completed": int(account.get("correction_missions_completed", 0)),
        "false_submission_offenses": false_submission_offenses,
        "parking_incident_count": len(parking_incidents),
        "active_bike_id": account.get("active_bike_id"),
        "recent_report_count": len(recent_reports),
        "last_report_issue": recent_reports[-1].get("issue_type") if recent_reports else None,
        "needs_attention": needs_attention,
    }


def is_report_open_for_action(report: dict) -> bool:
    return report.get("status", "pending") != "completed"


def get_issue_weight(issue_type: Optional[str]) -> float:
    if issue_type == "toppled":
        return 3.0
    if issue_type == "faulty":
        return 2.6
    if issue_type == "illegal_parking":
        return 2.2
    return 1.6


def cluster_reports(reports: List[dict]) -> List[dict]:
    mapped_reports = [
        report for report in reports
        if isinstance(report.get("location_lat"), (int, float)) and isinstance(report.get("location_lng"), (int, float))
    ]
    clusters: List[dict] = []

    for report in mapped_reports:
        lat = float(report["location_lat"])
        lng = float(report["location_lng"])
        score = get_issue_weight(report.get("issue_type")) + (0.8 if is_report_open_for_action(report) else 0.2)
        cluster = next((
            item for item in clusters
            if ((item["lat"] / item["count"]) - lat) ** 2 + ((item["lng"] / item["count"]) - lng) ** 2 <= HOTSPOT_CLUSTER_THRESHOLD ** 2
        ), None)

        if not cluster:
            cluster = {
                "id": f"hotspot-{len(clusters) + 1}",
                "lat": 0.0,
                "lng": 0.0,
                "count": 0,
                "score": 0.0,
                "pending": 0,
                "completed": 0,
                "issue_counts": {},
                "sample_address": report.get("location_address") or report.get("location_text") or None,
                "reports": [],
            }
            clusters.append(cluster)

        cluster["lat"] += lat
        cluster["lng"] += lng
        cluster["count"] += 1
        cluster["score"] += score
        cluster["pending"] += 1 if is_report_open_for_action(report) else 0
        cluster["completed"] += 0 if is_report_open_for_action(report) else 1
        issue_type = report.get("issue_type") or "general"
        cluster["issue_counts"][issue_type] = cluster["issue_counts"].get(issue_type, 0) + 1
        if not cluster["sample_address"] and (report.get("location_address") or report.get("location_text")):
            cluster["sample_address"] = report.get("location_address") or report.get("location_text")
        cluster["reports"].append(report)

    shaped = []
    for index, cluster in enumerate(clusters, start=1):
        top_issue = sorted(cluster["issue_counts"].items(), key=lambda item: item[1], reverse=True)[0][0] if cluster["issue_counts"] else "general"
        shaped.append({
            "id": cluster["id"],
            "index": index,
            "lat": cluster["lat"] / cluster["count"],
            "lng": cluster["lng"] / cluster["count"],
            "count": cluster["count"],
            "score": cluster["score"],
            "pending": cluster["pending"],
            "completed": cluster["completed"],
            "top_issue": top_issue,
            "severity": "high" if cluster["score"] >= 8 else "medium" if cluster["score"] >= 4 else "low",
            "title": cluster["sample_address"] or f"Hotspot {index}",
            "reports": cluster["reports"],
        })

    return sorted(shaped, key=lambda item: item["score"], reverse=True)


def build_priority_routes(hotspots: List[dict]) -> List[dict]:
    routes = []
    for hotspot in hotspots[:5]:
        repeat_offender_pressure = sum(1 for report in hotspot["reports"] if report.get("issue_type") == "illegal_parking")
        public_space_impact = hotspot["count"] * 2 + hotspot["pending"] * 3 + repeat_offender_pressure * 2
        routes.append({
            "id": hotspot["id"],
            "title": hotspot["title"],
            "severity": hotspot["severity"],
            "priority_score": round(hotspot["score"] + public_space_impact, 1),
            "issue_type": hotspot["top_issue"],
            "recommended_action": (
                f"Clear {hotspot['title']} first to recover space and reduce repeat {str(hotspot['top_issue']).replace('_', ' ')} cases."
            ),
            "estimated_bikes": hotspot["count"],
            "public_space_impact": public_space_impact,
        })
    return sorted(routes, key=lambda item: item["priority_score"], reverse=True)


def distance_between(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    return ((lat_a - lat_b) ** 2 + (lng_a - lng_b) ** 2) ** 0.5


def build_parking_guidance(lat: Optional[float], lng: Optional[float], hotspots: List[dict]) -> dict:
    if lat is None or lng is None or not hotspots:
        return {
            "zone": "good",
            "headline": "No congestion warning right now.",
            "message": "You are clear to park responsibly and keep your streak moving.",
            "points_tip": "Proper parking still earns points, but corrective actions earn even more.",
        }

    nearest = min(hotspots, key=lambda hotspot: distance_between(lat, lng, hotspot["lat"], hotspot["lng"]))
    proximity = distance_between(lat, lng, nearest["lat"], nearest["lng"])
    hotspot_issue = str(nearest.get("top_issue") or "general").replace("_", " ")

    if nearest["severity"] == "high" and proximity <= HOTSPOT_GUIDANCE_RADIUS:
        return {
            "zone": "bad",
            "headline": "High clutter risk nearby.",
            "message": f"This area often gets flagged for {hotspot_issue}. Move the bike into a proper zone to protect your streak and keep walkways clear.",
            "points_tip": "A safer parking spot now is better than having to recover your streak later.",
            "hotspot_title": nearest["title"],
        }
    if proximity <= HOTSPOT_GUIDANCE_RADIUS * 1.8:
        return {
            "zone": "risky",
            "headline": "Busy parking area ahead.",
            "message": f"Reports are clustering near {nearest['title']}. Double-check your bike position before ending the ride.",
            "points_tip": "Good parking helps, and nearby return-and-earn missions can boost your points even more.",
            "hotspot_title": nearest["title"],
        }
    return {
        "zone": "good",
        "headline": "Good parking zone.",
        "message": "This area has low recent clutter pressure. Park neatly to keep the space usable for everyone.",
        "points_tip": "You can still earn extra by picking up a nearby return-and-earn mission.",
        "hotspot_title": nearest["title"],
    }


def build_return_missions(user: str) -> List[dict]:
    user_key = user.lower().strip()
    account = get_user_account(user_key)
    hotspots = cluster_reports(REPORTS)
    incident_count = len(account.get("parking_incidents", []))
    recovery_boost = RECOVERY_ACTION_BONUS if incident_count else 0
    missions = []

    for hotspot in hotspots:
        if hotspot["top_issue"] != "illegal_parking":
            continue
        open_reports = [
            report for report in hotspot["reports"]
            if report.get("issue_type") == "illegal_parking" and is_report_open_for_action(report)
        ]
        if not open_reports:
            continue
        missions.append({
            "id": f"mission-{hotspot['id']}",
            "hotspot_id": hotspot["id"],
            "title": f"Return bikes near {hotspot['title']}",
            "headline": "Return-and-earn mission",
            "description": "Help move misplaced bikes back into proper parking and unlock a bigger point reward than a normal ride.",
            "encouragement": "This is your chance to earn more points while freeing up shared space.",
            "issue_type": hotspot["top_issue"],
            "severity": hotspot["severity"],
            "location_title": hotspot["title"],
            "bike_ids": [report.get("bike_id") for report in open_reports[:3]],
            "estimated_bikes": hotspot["count"],
            "reward_points": CORRECTIVE_ACTION_BASE_POINTS + recovery_boost,
            "bonus_points": MISSION_COMPLETION_BONUS + recovery_boost,
            "recovery_boost": recovery_boost,
            "before_after_required": True,
        })
        if len(missions) >= 5:
            break

    return missions


def build_space_recovery_metrics() -> dict:
    corrected_events = []
    for account in USER_ACCOUNTS.values():
        ensure_points_fields(account)
        corrected_events.extend([
            event for event in account.get("help_events", [])
            if event.get("mission_id") or str(event.get("label") or "").lower().startswith("return-and-earn")
        ])

    recovered_bikes = len(corrected_events)
    recovered_space = round(recovered_bikes * SPACE_RECOVERED_PER_BIKE, 1)
    hotspots = cluster_reports(REPORTS)
    illegal_hotspots = [hotspot for hotspot in hotspots if hotspot["top_issue"] == "illegal_parking"]
    return {
        "bikes_reparked": recovered_bikes,
        "space_recovered_m2": recovered_space,
        "clutter_hotspots": len(illegal_hotspots),
        "blocked_space_cleared_estimate": round(recovered_space * 0.65, 1),
    }


def build_leaderboard() -> List[dict]:
    leaders = []
    for user_key, proxy in PROXY_USERS.items():
        if proxy.get("role") != "user":
            continue
        account = get_user_account(user_key)
        sync_user_points_state(account)
        missions_completed = int(account.get("correction_missions_completed", 0))
        help_events = len(account.get("help_events", []))
        score = int(account.get("help_points_earned", 0)) + missions_completed * 60 + int(account.get("good_action_streak", 0)) * 8
        leaders.append({
            "user": account["user"],
            "display_name": account.get("display_name") or account["user"],
            "score": score,
            "good_action_streak": int(account.get("good_action_streak", 0)),
            "space_recovered_estimate": round(float(account.get("space_recovered_estimate", 0.0)), 1),
            "correction_missions_completed": missions_completed,
            "help_events": help_events,
        })
    existing_users = {str(leader["user"]).lower() for leader in leaders}
    for demo_player in DEMO_LEADERBOARD_PLAYERS:
        if demo_player["user"].lower() in existing_users:
            continue
        leaders.append(dict(demo_player))
    return sorted(leaders, key=lambda item: (-item["score"], item["display_name"].lower()))[:8]

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
        "reward_catalog": reward_catalog(),
        "proxy_accounts": [
            {"user": user, "role": info["role"]}
            for user, info in PROXY_USERS.items()
        ],
    }


@app.get("/api/app-config")
def app_config():
    load_env_file()
    return {
        "dev_login_mode": is_dev_login_mode(),
        "google_maps_api_key": (os.getenv("GOOGLE_MAPS_API_KEY") or "").strip() or None,
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
    ai_analysis = analyze_report_image_with_llm(
        image_data,
        bike_id,
        issue_type,
        description,
        normalized_location_text,
        normalized_location_address,
    )
    ai_summary = ai_analysis.get("summary") if ai_analysis else None
    
    report_dict = {
        "report_id": report_id,
        "reporter": submitted_by,
        "bike_id": bike_id,
        "issue_type": normalize_issue_type(issue_type),
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
        "ai_alignment_status": ai_analysis.get("alignment_status") if ai_analysis else None,
        "ai_issue_match": ai_analysis.get("issue_match") if ai_analysis else None,
        "ai_detected_issue": ai_analysis.get("detected_issue") if ai_analysis else None,
        "ai_confidence": ai_analysis.get("confidence") if ai_analysis else None,
        "status": "pending",
        "reviewed_by": None,
        "review_notes": None,
        "review_action": None,
        "reward_granted": False,
        "reward_voucher": None,
        "points_awarded": 0,
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
    award_message = ""
    ai_alignment_status = report.get("ai_alignment_status")
    ai_detected_issue = normalize_issue_type(report.get("ai_detected_issue") or report.get("issue_type"))
    submitted_issue = normalize_issue_type(report.get("issue_type"))
    review_date = date.today().isoformat()

    if normalized_action == "reject" and ai_alignment_status == "not_aligned":
        reporter_account = get_user_account(report["reporter"])
        offense_count, warning_message = register_false_submission(reporter_account, review_date)
        award_message = f" {warning_message} False-submission offense count: {offense_count}."

    if normalized_action == "approve" and not report.get("reward_granted"):
        reporter_account = get_user_account(report["reporter"])
        report["reward_granted"] = True
        report["reward_voucher"] = None
        base_points, corrected_issue = get_report_reward_base_points(report)
        confirmed_issue = corrected_issue or submitted_issue
        reward_label = f"{format_location_text(report.get('location_lat'), report.get('location_lng'), report.get('location_accuracy')) or 'Verified report'} approved"
        if corrected_issue:
            reward_label = f"{reward_label} (retagged as {corrected_issue.replace('_', ' ')})"
        awarded_points, multiplier, streak_count = award_points_for_good_action(
            reporter_account,
            base_points,
            reward_label,
            review_date,
            "report_points_earned",
        )
        report["points_awarded"] = awarded_points
        award_message = f" {report['points_awarded']} points added with a {multiplier:.2f}x streak multiplier."
        if corrected_issue and corrected_issue != submitted_issue:
            mismatch_note = (
                f" AI suggests this looked more like {corrected_issue.replace('_', ' ')} than {submitted_issue.replace('_', ' ')}."
            )
            report["review_notes"] = f"{report['review_notes']} {mismatch_note}".strip() if report.get("review_notes") else mismatch_note.strip()
            award_message += f" Maintenance was informed that the image looks more like {corrected_issue.replace('_', ' ')} than {submitted_issue.replace('_', ' ')}, so the user received reduced points."
        if confirmed_issue == "illegal_parking":
            flagged_account = flag_illegal_parking_for_bike(
                report["bike_id"],
                "Illegal parking confirmed by maintenance review",
                review_date,
            )
            if flagged_account:
                award_message += f" The linked renter {flagged_account['user']} had their streak reset."
    save_reports_to_csv()
    action_word = "approved" if normalized_action == "approve" else "rejected"

    return {
        "message": f"Report {action_word} successfully.{award_message}",
        "report": report,
    }

@app.post("/api/parking-help")
def parking_help(help_request: HelpRequest):
    account = get_user_account(help_request.user)
    today = date.today().isoformat()
    mission_id = (help_request.mission_id or "").strip() or None
    is_corrective_mission = bool(mission_id)
    latest_incident = account.get("parking_incidents", [])[-1] if account.get("parking_incidents") else None
    recovery_bonus = RECOVERY_ACTION_BONUS if latest_incident else 0
    base_points = CORRECTIVE_ACTION_BASE_POINTS if is_corrective_mission else 25
    bonus_points = MISSION_COMPLETION_BONUS if is_corrective_mission else 0
    total_base_points = base_points + bonus_points + recovery_bonus
    guidance = build_parking_guidance(
        help_request.location_lat,
        help_request.location_lng,
        cluster_reports(REPORTS),
    )
    event = {
        "bike_id": help_request.bike_id,
        "notes": help_request.notes or "Helped keep the bicycle inside the assigned parking spot.",
        "date": today,
        "base_points": total_base_points,
        "mission_id": mission_id,
        "label": "Return-and-earn mission" if is_corrective_mission else "Parking help bonus",
        "location_lat": help_request.location_lat,
        "location_lng": help_request.location_lng,
        "location_address": help_request.location_address,
        "before_image": help_request.before_image,
        "after_image": help_request.after_image,
        "bonus_points": bonus_points,
        "recovery_bonus": recovery_bonus,
        "guidance_zone": guidance["zone"],
    }
    account["help_events"].append(event)
    awarded_points, multiplier, streak_count = award_points_for_good_action(
        account,
        event["base_points"],
        event["label"],
        today,
        "help_points_earned",
    )
    event["points"] = awarded_points
    event["multiplier"] = multiplier
    event["streak"] = streak_count
    account["space_recovered_estimate"] = round(float(account.get("space_recovered_estimate", 0.0)) + SPACE_RECOVERED_PER_BIKE, 1)
    if is_corrective_mission:
        account["correction_missions_completed"] = int(account.get("correction_missions_completed", 0)) + 1
    return {
        "message": (
            f"Parking help logged. You earned {awarded_points} points with a {multiplier:.2f}x multiplier."
            if not is_corrective_mission
            else f"Mission completed. You earned {awarded_points} points with a {multiplier:.2f}x multiplier."
        ),
        "points_balance": account["points_balance"],
        "help_event": event,
        "space_recovered_estimate": round(float(account.get("space_recovered_estimate", 0.0)), 1),
    }


@app.post("/api/rides/log")
def log_ride_activity(request: RideActivityRequest, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    account = get_user_account(current_user_key)
    today = date.today().isoformat()
    bike_id = request.bike_id.strip().upper()
    account["active_bike_id"] = bike_id
    awarded_points = award_usage_points(
        account,
        10,
        "Bike rental ride",
        today,
        "ride_history",
        bike_id,
        request.notes or "Completed a bicycle rental trip.",
        request.location_lat,
        request.location_lng,
        request.location_accuracy,
        request.location_address,
    )
    account.setdefault("rental_history", []).append({
        "bike_id": bike_id,
        "date": today,
        "notes": request.notes or "Bike linked through ride logging.",
        "method": "ride-log",
    })
    guidance = build_parking_guidance(
        request.location_lat,
        request.location_lng,
        cluster_reports(REPORTS),
    )
    account.setdefault("recent_guidance_checks", []).append({
        "date": today,
        "zone": guidance["zone"],
        "headline": guidance["headline"],
        "bike_id": bike_id,
    })
    return {
        "message": f"Ride logged. You earned {awarded_points} usage points.",
        "points_balance": account["points_balance"],
        "active_bike_id": account["active_bike_id"],
        "ride_history": account.get("ride_history", [])[-10:],
        "parking_guidance": guidance,
    }


@app.post("/api/parking/log")
def log_parking_activity(request: RideActivityRequest, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    account = get_user_account(current_user_key)
    today = date.today().isoformat()
    bike_id = request.bike_id.strip().upper()
    guidance = build_parking_guidance(
        request.location_lat,
        request.location_lng,
        cluster_reports(REPORTS),
    )
    awarded_points = award_usage_points(
        account,
        15,
        "Proper bike parking",
        today,
        "parking_history",
        bike_id,
        request.notes or "Returned and parked the bicycle responsibly.",
        request.location_lat,
        request.location_lng,
        request.location_accuracy,
        request.location_address,
    )
    if str(account.get("active_bike_id") or "").strip().upper() == bike_id:
        account["active_bike_id"] = None
    account.setdefault("recent_guidance_checks", []).append({
        "date": today,
        "zone": guidance["zone"],
        "headline": guidance["headline"],
        "bike_id": bike_id,
    })
    return {
        "message": f"Parking logged. You earned {awarded_points} usage points.",
        "points_balance": account["points_balance"],
        "active_bike_id": account.get("active_bike_id"),
        "parking_history": account.get("parking_history", [])[-10:],
        "parking_guidance": guidance,
    }


@app.post("/api/rentals/scan")
def scan_bike_qr(request: ScanRentalRequest, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    account = get_user_account(current_user_key)
    bike_id = (request.bike_id or DUMMY_BIKE_ID).strip().upper() or DUMMY_BIKE_ID
    previous_renter = find_active_renter_for_bike(bike_id)
    if previous_renter and previous_renter["user"].lower() != account["user"].lower():
        previous_renter["active_bike_id"] = None
    account["active_bike_id"] = bike_id
    account.setdefault("rental_history", []).append({
        "bike_id": bike_id,
        "date": date.today().isoformat(),
        "notes": "Bike linked through QR scan.",
        "method": "qr-scan",
    })
    latest_incident = next(
        (item for item in reversed(account.get("parking_incidents", [])) if str(item.get("bike_id") or "").strip().upper() == bike_id),
        None,
    )
    return {
        "message": f"Bike {bike_id} linked to your account.",
        "bike_id": bike_id,
        "active_bike_id": account["active_bike_id"],
        "warning": (
            f"This bike has a recent parking incident on record: {latest_incident['reason']}."
            if latest_incident else None
        ),
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

@app.get("/api/admin/accounts")
def admin_accounts(authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    current_account = get_user_account(current_user_key)
    if current_account["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can manage accounts.")

    accounts = []
    for user_key, info in PROXY_USERS.items():
        account = build_admin_account_snapshot(user_key)
        account["role"] = info["role"]
        accounts.append(account)

    return {
        "overview": build_admin_overview(),
        "accounts": sorted(accounts, key=lambda item: (ROLE_PRIORITY.get(item["role"], 0) * -1, item["user"].lower()))
    }


@app.post("/api/admin/accounts/create")
def admin_create_account(request: AdminAccountCreateRequest, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    current_account = get_user_account(current_user_key)
    if current_account["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create accounts.")

    target_user = (request.user or "").strip()
    target_password = (request.password or "").strip()
    target_role = (request.role or "user").strip().lower()
    if not target_user:
        raise HTTPException(status_code=400, detail="Email cannot be empty.")
    if not target_password:
        raise HTTPException(status_code=400, detail="Password cannot be empty.")
    if target_role not in {"user", "maintenance"}:
        raise HTTPException(status_code=400, detail="Role must be user or maintenance.")

    user_key = target_user.lower()
    if user_key in PROXY_USERS:
        raise HTTPException(status_code=400, detail="That account already exists.")

    PROXY_USERS[user_key] = {"password": target_password, "role": target_role}
    account = get_user_account(user_key)
    account["user"] = target_user
    account["role"] = target_role
    account["display_name"] = (request.display_name or target_user).strip() or target_user
    account["phone_number"] = (request.phone_number or "").strip()

    return {
        "message": "Account created successfully.",
        "account": build_admin_account_snapshot(user_key),
        "overview": build_admin_overview(),
    }

@app.post("/api/admin/accounts/{user}/update")
def admin_update_account(user: str, request: AdminAccountUpdateRequest, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    current_account = get_user_account(current_user_key)
    if current_account["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can manage accounts.")

    target_user_key = user.lower().strip()
    proxy = PROXY_USERS.get(target_user_key)
    if not proxy:
        raise HTTPException(status_code=404, detail="Account not found.")
    if proxy["role"] == "admin":
        raise HTTPException(status_code=403, detail="Admin accounts cannot be edited from this panel.")

    if request.role:
        normalized_role = request.role.strip().lower()
        if normalized_role not in {"user", "maintenance"}:
            raise HTTPException(status_code=400, detail="Role must be user or maintenance.")
        proxy["role"] = normalized_role

    if request.password is not None:
        next_password = request.password.strip()
        if not next_password:
            raise HTTPException(status_code=400, detail="Password cannot be empty.")
        proxy["password"] = next_password

    account = USER_ACCOUNTS.get(target_user_key)
    if account and request.display_name is not None:
        next_display_name = request.display_name.strip()
        account["display_name"] = next_display_name or account.get("display_name") or account.get("user", user)
    if account and request.phone_number is not None:
        account["phone_number"] = request.phone_number.strip()

    refreshed_account = get_user_account(account["user"] if account else user)
    return {
        "message": "Account updated successfully.",
        "account": build_admin_account_snapshot(target_user_key),
    }


@app.post("/api/admin/accounts/{user}/reset-streak")
def admin_reset_streak(user: str, request: StreakResetRequest, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    current_account = get_user_account(current_user_key)
    if current_account["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can reset streaks.")

    target_user_key = user.lower().strip()
    if target_user_key not in PROXY_USERS:
        raise HTTPException(status_code=404, detail="Account not found.")

    account = get_user_account(target_user_key)
    reset_reason = (request.reason or "Illegal parking suspected").strip() or "Illegal parking suspected"
    reset_streak(account, reset_reason, date.today().isoformat())
    return {
        "message": "User streak reset successfully.",
        "good_action_streak": account["good_action_streak"],
        "streak_multiplier": account["streak_multiplier"],
    }

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
    sync_user_points_state(account)
    if account["points_balance"] < request.points:
        raise HTTPException(status_code=400, detail="Not enough points to redeem this reward.")

    account["points_spent"] = int(account.get("points_spent", 0)) + request.points
    sync_user_points_state(account)
    account.setdefault("points_history", []).append({
        "type": "redeem",
        "label": request.reward_name or "Custom reward redemption",
        "points": -request.points,
        "date": date.today().isoformat(),
    })
    return {
        "message": "Reward redeemed using points.",
        "points_balance": account["points_balance"],
        "reward_name": request.reward_name or "Custom reward redemption",
    }

@app.post("/api/claim-reward")
def claim_reward(request: RewardRequest):
    raise HTTPException(status_code=403, detail="Rewards are only granted after maintenance approves a report.")

@app.post("/api/use-reward")
def use_reward(request: UseRewardRequest, authorization: Optional[str] = Header(None)):
    current_user_key = validate_session_token(authorization)
    account = get_user_account(current_user_key)
    sync_user_points_state(account)
    reward = get_catalog_reward(request.reward)
    if not reward:
        raise HTTPException(status_code=404, detail="Reward item not found.")
    if account["points_balance"] < reward["cost"]:
        raise HTTPException(status_code=400, detail="Not enough points to redeem this item.")
    account["points_spent"] = int(account.get("points_spent", 0)) + reward["cost"]
    sync_user_points_state(account)
    account.setdefault("points_history", []).append({
        "type": "redeem",
        "label": reward["name"],
        "points": -reward["cost"],
        "date": date.today().isoformat(),
    })
    return {
        "message": f"{reward['name']} redeemed successfully.",
        "points_balance": account["points_balance"],
        "points_history": account["points_history"][-10:],
    }

@app.get("/api/rewards/{user}")
def reward_status(user: str):
    account = get_user_account(user)
    sync_user_points_state(account)
    hotspots = cluster_reports(REPORTS)
    missions = build_return_missions(user)
    space_metrics = build_space_recovery_metrics()
    leaderboard = build_leaderboard()
    priority_routes = build_priority_routes(hotspots)
    latest_parking = account.get("parking_history", [])[-1] if account.get("parking_history") else None
    latest_guidance = build_parking_guidance(
        latest_parking.get("location_lat") if latest_parking else None,
        latest_parking.get("location_lng") if latest_parking else None,
        hotspots,
    )
    hotspot_alert = next((hotspot for hotspot in hotspots if hotspot["severity"] == "high"), hotspots[0] if hotspots else None)
    recovery_status = {
        "has_recent_incident": bool(account.get("parking_incidents")),
        "headline": "Keep the streak going with community parking saves.",
        "message": "Helpful actions build your multiplier faster than normal rides and make the town feel tidier.",
    }
    if account.get("parking_incidents"):
        recovery_status = {
            "has_recent_incident": True,
            "headline": "You can rebuild quickly.",
            "message": "A recent parking incident reset your streak, but return-and-earn missions and clean parking can boost you back fast.",
        }
    return {
        "user": user,
        "points_balance": account["points_balance"],
        "lifetime_points": account["lifetime_points"],
        "good_action_streak": account.get("good_action_streak", 0),
        "streak_multiplier": account.get("streak_multiplier", 1.0),
        "points_to_next_streak": max(next_streak_target(account.get("good_action_streak", 0)) - account.get("good_action_streak", 0), 0),
        "points_to_next_reward": max(min(item["cost"] for item in reward_catalog()) - account["points_balance"], 0),
        "catalog": reward_catalog(),
        "help_events": account["help_events"],
        "points_history": account.get("points_history", [])[-10:],
        "ride_history": account.get("ride_history", [])[-10:],
        "parking_history": account.get("parking_history", [])[-10:],
        "active_bike_id": account.get("active_bike_id"),
        "parking_incidents": account.get("parking_incidents", [])[-10:],
        "false_submission_offenses": int(account.get("false_submission_offenses", 0)),
        "missions": missions,
        "parking_guidance": latest_guidance,
        "hotspot_alert": {
            "active": bool(hotspot_alert),
            "title": hotspot_alert["title"] if hotspot_alert else None,
            "severity": hotspot_alert["severity"] if hotspot_alert else None,
            "message": (
                f"Illegal parking is clustering near {hotspot_alert['title']}. This is your chance to earn more points by helping."
                if hotspot_alert and hotspot_alert["top_issue"] == "illegal_parking"
                else f"Community issue pressure is rising near {hotspot_alert['title']}."
                if hotspot_alert else "No major congestion hotspot right now."
            ),
        },
        "space_metrics": space_metrics,
        "leaderboard": leaderboard,
        "priority_routes": priority_routes,
        "recovery_status": recovery_status,
        "community_impact": {
            "space_recovered_estimate": round(float(account.get("space_recovered_estimate", 0.0)), 1),
            "correction_missions_completed": int(account.get("correction_missions_completed", 0)),
            "helpful_actions": len(account.get("help_events", [])),
        },
    }
