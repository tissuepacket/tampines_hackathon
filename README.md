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

install npm

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
