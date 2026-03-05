# HelloCity – AI-Powered Interest Onboarding

Mobile-first web app that collects three city interests from the user via chat, shows real Miami examples for each, and outputs a structured profile. Built for the HelloCity Engineering Exercise (full-stack, ~3 hr).

## What it does

- **Chat:** User talks to an LLM-powered assistant that asks what they like doing in the city (e.g. food, live music, art, beach).
- **Interests:** The backend extracts interests from natural language (with keyword/typo fallback), collects exactly 3, and prevents duplicates.
- **Examples:** After each interest, the app shows 3 real Miami venues (name, neighborhood, description, hours).
- **Validation:** User confirms with “Yes, that’s what I meant” or “No”; either way the interest counts and the flow continues.
- **Profile:** When 3 interests are collected, a structured profile `{ "interests": [...] }` is generated server-side and displayed.

## Tech stack

- **Backend:** Python, FastAPI, Uvicorn. Session state in memory; OpenAI (GPT-4o-mini) for conversation and interest extraction.
- **Frontend:** React (Vite), TypeScript. HelloCity yellow/black branding, mobile-first layout.

## Run locally

### 1. Backend

```bash
# From the project root
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` in the project root (optional; without it the app uses mock responses):

```env
OPENAI_API_KEY=sk-your-key-here
```

Start the server:

```bash
uvicorn backend.main:app --reload --port 8000
```

Backend runs at **http://127.0.0.1:8000**. Health: http://127.0.0.1:8000/health | LLM status: http://127.0.0.1:8000/llm-status

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (e.g. **http://localhost:5173**). The app talks to the backend at `http://127.0.0.1:8000` by default. To use another backend URL:

```env
# frontend/.env.local
VITE_API_BASE_URL=http://localhost:8000
```

## Deploy

See **[DEPLOY.md](./DEPLOY.md)** for deploying the frontend to Vercel and the backend to Render.

## Project layout

- `backend/main.py` – FastAPI app, session state, LLM + fallback, Miami venues, chat endpoint.
- `frontend/src/App.tsx` – Chat UI, example cards, Yes/No, profile.
- `SUMMARY.md` – Short summary for the exercise (stack, LLM, reasoning vs backend, unfinished).
- `REQUIREMENTS_CHECKLIST.md` – PDF requirements checklist.
