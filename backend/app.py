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
    reporter: str = Field(..., title="Reporter name or email")
    bike_id: str = Field(..., title="Bike identifier")
    issue_type: IssueType = Field(..., title="Type of issue")
    description: str = Field(..., title="What happened")
    outside_zone: Optional[bool] = Field(False, title="Outside designated parking zone")
    toppled: Optional[bool] = Field(False, title="Bike is toppled")
    faulty: Optional[bool] = Field(False, title="Bike appears faulty")

class AiInspectRequest(BaseModel):
    bike_id: str = Field(..., title="Bike identifier")
    outside_zone: bool = Field(False, title="Outside designated parking zone")
    toppled: bool = Field(False, title="Bike is toppled")
    faulty: bool = Field(False, title="Bike appears faulty")
    notes: Optional[str] = Field(None, title="Additional notes")

class RewardRequest(BaseModel):
    user: str = Field(..., title="User name or email")
    action: str = Field(..., title="Reward action requested")

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

class ReportSummary(BaseModel):
    total_reports: int
    recent_reports: List[Report]

REPORTS: List[Report] = []
USER_ACCOUNTS: Dict[str, dict] = {}
REWARD_LIMIT_PER_DAY = 3
reward_store = {}
SESSIONS: Dict[str, str] = {}
ROLE_PRIORITY = {"admin": 3, "maintenance": 2, "user": 1}


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
        "role": role,
        "reports": [],
        "parking_points": 0,
        "help_events": [],
        "claimed_rewards": [],
        "profile_photo": None,
        "settings": {
            "theme": "light",
            "font_size": "medium",
        },
    })
    account.setdefault("display_name", user)
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
        "role": account["role"],
        "parking_points": account["parking_points"],
        "settings": account.get("settings", {"theme": "light", "font_size": "medium"}),
        "profile_photo": account.get("profile_photo"),
        "total_reports": len(account["reports"]),
        "total_help_events": len(account["help_events"]),
        "claimed_rewards": account["claimed_rewards"],
        "recent_reports": account["reports"][-10:],
        "recent_help_events": account["help_events"][-10:],
    }

@app.get("/api/status")
def status():
    return {
        "app_name": "Bike Patrol Rewards",
        "report_count": len(REPORTS),
        "reward_limit_per_day": REWARD_LIMIT_PER_DAY,
        "available_vouchers": AVAILABLE_VOUCHERS,
        "proxy_accounts": [
            {"user": user, "role": info["role"]}
            for user, info in PROXY_USERS.items()
        ],
    }

@app.get("/api/reports", response_model=ReportSummary)
def get_reports():
    return {
        "total_reports": len(REPORTS),
        "recent_reports": REPORTS[-10:],
    }

@app.post("/api/reports")
def submit_report(report: Report):
    REPORTS.append(report)
    account = get_user_account(report.reporter)
    account["reports"].append(report)
    return {
        "message": "Report received. Maintenance team alerted.",
        "report": report,
        "user_summary": build_user_summary(report.reporter),
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
    proxy["password"] = request.new_password
    return {"message": "Password changed successfully."}

@app.post("/api/reset-password")
def reset_password(request: PasswordResetRequest):
    user_key = request.user.lower().strip()
    proxy = PROXY_USERS.get(user_key)
    if not proxy:
        raise HTTPException(status_code=404, detail="User not found.")
    proxy["password"] = request.new_password
    return {"message": "Password reset successfully (demo mode)."}

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
def current_user():
    current_user_key = get_current_user()
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

@app.post("/api/ai-check")
async def ai_check(
    image: UploadFile = File(...),
    bike_id: str = Form("BK-000"),
    outside_zone: bool = Form(False),
    toppled: bool = Form(False),
    faulty: bool = Form(False),
    notes: Optional[str] = Form(None),
    llm_token: Optional[str] = Form(None),
):
    issues = []
    actions = []
    if outside_zone:
        issues.append("Illegal parking detected outside designated zone.")
        actions.append("Dispatch maintenance to move bike into parking area.")
    if toppled:
        issues.append("Toppled bicycle detected.")
        actions.append("Send crew to stand the bike upright and inspect it.")
    if faulty:
        issues.append("Faulty bicycle components detected.")
        actions.append("Create a repair ticket and reserve a replacement.")
    if not issues:
        issues.append("No major issues detected. Continue monitoring the area.")
        actions.append("Record a clean sweep and keep the route under observation.")

    placeholder_token = llm_token or "PLACEHOLDER_LLM_TOKEN"
    notes_text = notes or "AI check complete."
    return {
        "bike_id": bike_id,
        "image_filename": image.filename,
        "issues": issues,
        "actions": actions,
        "notes": f"{notes_text} Placeholder token used: {placeholder_token}.",
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
    }
