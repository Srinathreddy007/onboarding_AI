# HelloCity – AI-Powered Interest Onboarding

Mobile-first web app that collects three city interests from the user via chat, shows real Miami examples for each, and outputs a structured profile. Built for the HelloCity Engineering Exercise (full stack, ~3 hr).

---

## Deliverables

1. **Live URL:** [https://hellocity-ai.uc.r.appspot.com](https://hellocity-ai.uc.r.appspot.com)  
   (Also: https://hellocity-ai.appspot.com)

2. **GitHub repository:** [https://github.com/Srinathreddy007/onboarding_AI](https://github.com/Srinathreddy007/onboarding_AI)

3. **Short summary**
   - **Stack used:** Backend: Python, FastAPI, Uvicorn. Frontend: React (Vite), TypeScript. Deployed on Google App Engine for the hosted version.
   - **LLM used:** OpenAI GPT-4o-mini for conversational replies and for extracting interest candidates from user messages. API key from `.env` locally and from GCP Secret Manager in production.
   - **Reasoning vs backend logic:** The LLM returns free-form `assistant_message` and structured `interest_candidates`. The backend owns progression: it normalizes candidates, prevents duplicates, enforces “exactly 3” interests, decides when to show examples and when to show the final profile, and applies fallback extraction when the LLM is weak or unavailable. Session state and interest list live only in the backend.
   - **Anything unfinished:** Session state is in memory only. Place suggestions are dynamic through Google Places first, with an LLM fallback if needed, so the quality depends on external API results. The README and code now separate example suggestions, backend normalization rules, and supported search categories, but more category coverage can still be added over time.

---

## What it does

- **Chat:** User talks to an LLM-powered assistant that asks what they like doing in the city (e.g. food, live music, art, beach).
- **Interests:** The backend extracts interests from natural language, lets the LLM propose labels dynamically, then applies backend normalization and fallback matching when needed.
- **One at a time:** The backend stays in control of progression and collects interests one by one. If the user answers vaguely with messages like `these` or `those` before any cards are on screen, the assistant asks for one specific interest instead of inferring a new one.
- **Examples:** After each interest, the app tries to show 3 real Miami places using Google Places first and an LLM place fallback second.
- **Validation:** User confirms with “Yes, that’s what I meant” or “No”; either way the interest counts and the flow continues. If the user types something like `I like these places` while cards are visible, the app keeps the same cards on screen and asks them to use the existing Yes/No choice instead of advancing implicitly.
- **Profile:** When 3 interests are collected, a structured profile `{ "interests": [...] }` is generated server-side and displayed.

## Interest handling and place lookup

The exercise says an interest *“can be any activity category”* and gives examples (Mexican restaurants, live jazz, rooftop bars, art galleries, farmers markets, beach activities). It also requires that **each interest be backed by 3 real Miami examples** (real venue/event names, not placeholders).

This implementation does **not** hard-restrict the LLM to a short fixed category list. Instead, it uses three layers:

- **Example suggestions:** a static list of example interests used only for conversational prompts and suggestion copy.
- **Normalization and fallback rules:** static typo, synonym, semantic, and keyword mappings used only when the LLM is weak or unavailable.
- **Supported search categories:** canonical search labels the backend knows how to turn into strong Miami place searches.

If the user goes beyond the example list, the LLM can still return a new label and search query. If that search query produces good Miami results, the app can still show 3 cards. If the model cannot map the interest well, the backend falls back to normalization rules or returns an honest “no good matches found” response.

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
GOOGLE_PLACES_API_KEY=your_google_places_key
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

The current Vite toolchain requires **Node 20.19+** locally.

Open the URL Vite prints (e.g. **http://localhost:5173**). The app talks to the backend at `http://127.0.0.1:8000` by default. To use another backend URL:

```env
# frontend/.env.local
VITE_API_BASE_URL=http://localhost:8000
```

## Deploy

The repo includes [app.yaml](/Users/srinathreddy/Documents/onboarding_AI/app.yaml) and [deploy_gcp.sh](/Users/srinathreddy/Documents/onboarding_AI/deploy_gcp.sh) for Google App Engine.

### App Engine

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud app create   # only the first time for a project

export OPENAI_API_KEY=your_openai_key
export GOOGLE_PLACES_API_KEY=your_google_places_key

./deploy_gcp.sh
```

Notes:
- The script builds the Vite frontend into `frontend/dist` before deploying.
- The current Vite build requires **Node 20.19+** on the machine running the deploy script.
- `OPENAI_API_KEY` is optional if production can read `openai-api-key` from Secret Manager.
- `GOOGLE_PLACES_API_KEY` is recommended if you want Google Places cards to work in production.
- The deployed app serves the frontend and FastAPI backend from the same App Engine service, so `VITE_API_BASE_URL` is left empty for production.

## Project layout

- `backend/main.py` – FastAPI app, session state, OpenAI extraction, backend fallback logic, Google Places lookup, chat endpoint.
- `frontend/src/App.tsx` – Chat UI, example cards, Yes/No, profile.
