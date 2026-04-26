# Bike Patrol Rewards Prototype

This repository is split into two folders:

- `backend/` — FastAPI backend for the bike report API and reward logic
- `frontend/` — Vite-powered frontend to interact with the backend via `/api` proxy

## Run the backend

1. Activate the Python virtual environment:

```bash
cd /Users/tissuepacket/first_hackathon/tampines_hackathon
source .venv/bin/activate
```

2. Install backend dependencies if not already installed:

```bash
pip install -r backend/requirements.txt
```

3. Start the backend server:

```bash
cd backend
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

## Run the frontend

### Option A: If you have npm installed

1. Install frontend dependencies once:

```bash
cd /Users/tissuepacket/first_hackathon/tampines_hackathon/frontend
npm install
```

2. Start the frontend dev server:

```bash
npm run dev
```

3. Open the URL shown in the terminal, usually `http://127.0.0.1:5173`.

### Option B: No npm installed

1. Start the backend server as described above.

2. Serve the frontend folder with Python from the frontend directory:

```bash
cd /Users/tissuepacket/first_hackathon/tampines_hackathon/frontend
python3 -m http.server 8001
```

3. Open `http://127.0.0.1:8001` in your browser.

The frontend now supports uploading an image for the AI inspection check. It will send the image to the backend along with a placeholder LLM token for review.

The frontend is configured to call the backend directly at `http://127.0.0.1:8000`, so it works without npm.
