# Bike Patrol Rewards Prototype

This repository is split into two folders:

- `backend/` — FastAPI backend for the bike report API and reward logic
- `frontend/` — Vite-powered frontend to interact with the backend via `/api` proxy

## Run the backend

1. Activate the Python virtual environment:

```bash
cd tampines_hackathon
source .venv/bin/activate
```

2. Install backend dependencies if not already installed:

```bash◊
pip install -r backend/requirements.txt
```

3. Start the backend server:

```bash
cd backend
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

## Proxy account setup

The repo includes `.env.example` with dummy proxy credentials. Copy it to `.env` in the repository root and keep `.env` private.

```bash
cp .env.example .env
```

Then use one of these sample accounts in the sidebar login:

- `admin@bikepatrol.test` / `admin123`
- `maintenance@bikepatrol.test` / `maint123`
- `user@bikepatrol.test` / `user123`

If you want the login screen to show quick-login cards instead of the normal form, set:

```env
DEV_LOGIN_MODE=1
```

When `DEV_LOGIN_MODE=1`, the login screen shows `User`, `Admin`, and `Maintenance` cards that log in with the sample accounts above.

## Run the frontend

install npm

1. Install frontend dependencies once:

```bash
cd tampines_hackathon/frontend
npm install
```

2. Start the frontend dev server:

```bash
npm run dev
```

3. Open the URL shown in the terminal, usually `http://127.0.0.1:5173`.
