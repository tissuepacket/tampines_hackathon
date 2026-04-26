from datetime import date
from enum import Enum
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional

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

class ReportSummary(BaseModel):
    total_reports: int
    recent_reports: List[Report]

REPORTS: List[Report] = []
REWARD_LIMIT_PER_DAY = 3
reward_store = {}
AVAILABLE_VOUCHERS = [
    "CDC Food Voucher",
    "CDC Shopping Discount",
    "CDC Transport Subsidy",
    "CDC Bike Care Coupon"
]

@app.get("/api/status")
def status():
    return {
        "app_name": "Bike Patrol Rewards",
        "report_count": len(REPORTS),
        "reward_limit_per_day": REWARD_LIMIT_PER_DAY,
        "available_vouchers": AVAILABLE_VOUCHERS,
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
    return {
        "message": "Report received. Maintenance team alerted.",
        "report": report,
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

    return {
        "message": "Reward claimed successfully.",
        "voucher": voucher,
        "claimed_today": record["count"],
        "limit": REWARD_LIMIT_PER_DAY,
    }

@app.get("/api/rewards/{user}")
def reward_status(user: str):
    record = reward_store.get(user.lower())
    if not record:
        return {"user": user, "claimed_today": 0, "limit": REWARD_LIMIT_PER_DAY, "claimed_vouchers": []}
    return {
        "user": user,
        "claimed_today": record["count"],
        "limit": REWARD_LIMIT_PER_DAY,
        "claimed_vouchers": record["claimed"],
    }
