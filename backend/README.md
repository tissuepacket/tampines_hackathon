# Bike Patrol Rewards Prototype

A simple FastAPI backend with a minimal HTML/CSS frontend for reporting bicycle issues, simulating AI inspections, and claiming daily reward vouchers.

## Features

- Submit bike reports for illegal parking, toppled bikes, and faults
- Simulated AI inspection for bikes outside the designated zone or with visible problems
- Simple reward claim flow limited to a few vouchers per day
- Frontend communicates with backend via fetch requests

## Run locally

1. Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

4. Open `http://localhost:8000` in your browser.
