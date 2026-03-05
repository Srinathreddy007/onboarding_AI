import json
import os
import re
import uuid
from typing import List, Optional, Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

try:
    from google.cloud import secretmanager
except Exception:
    secretmanager = None  # type: ignore

load_dotenv()

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    confirmed: Optional[bool] = None


class MiamiExample(BaseModel):
    name: str
    neighborhood: str
    description: str
    hours: str


class ChatResponse(BaseModel):
    session_id: str
    assistant_message: str
    interests: List[str]
    interests_count: int
    examples: List[MiamiExample]
    is_complete: bool
    profile: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

class SessionState:
    def __init__(self) -> None:
        self.interests: List[str] = []
        self.messages: List[ChatMessage] = []
        self.awaiting_confirmation: bool = False


SESSIONS: Dict[str, SessionState] = {}


def get_or_create_session(sid: Optional[str]) -> str:
    if sid and sid in SESSIONS:
        return sid
    new_id = str(uuid.uuid4())
    SESSIONS[new_id] = SessionState()
    return new_id


# ---------------------------------------------------------------------------
# Miami venues (real places with hours)
# ---------------------------------------------------------------------------

MIAMI_VENUES: Dict[str, List[MiamiExample]] = {
    "food": [
        MiamiExample(name="Joe's Stone Crab", neighborhood="South Beach", description="Iconic Miami Beach spot for stone crabs and seafood since 1913.", hours="Sun–Thu 11:30AM–10PM, Fri–Sat 11:30AM–11PM"),
        MiamiExample(name="Versailles", neighborhood="Little Havana", description="Legendary Cuban restaurant and bakery, a Miami institution.", hours="Mon–Sun 8AM–12AM"),
        MiamiExample(name="Mandolin Aegean Bistro", neighborhood="Design District", description="Mediterranean courtyard restaurant with fresh Greek and Turkish dishes.", hours="Mon–Sat 12PM–11PM, Sun 11AM–10PM"),
    ],
    "mexican food": [
        MiamiExample(name="Coyo Taco", neighborhood="Wynwood", description="Casual taqueria with house-made tortillas and margaritas in the heart of Wynwood.", hours="Mon–Wed 11AM–12AM, Thu–Sat 11AM–3AM, Sun 11AM–12AM"),
        MiamiExample(name="Bodega Taqueria y Tequila", neighborhood="South Beach", description="Late-night tacos up front with a hidden speakeasy bar in the back.", hours="Mon–Sun 11AM–5AM"),
        MiamiExample(name="Taquiza", neighborhood="North Beach", description="Hand-pressed blue corn tortillas and authentic street-style tacos near the beach.", hours="Mon–Sun 12PM–10PM"),
    ],
    "live jazz": [
        MiamiExample(name="Lagniappe", neighborhood="Edgewater", description="Wine and cheese garden with nightly live jazz in a relaxed backyard setting.", hours="Mon–Sun 5PM–1AM"),
        MiamiExample(name="Ball & Chain", neighborhood="Little Havana", description="Historic 1935 club on Calle Ocho with Latin jazz, live bands, and dancing.", hours="Mon–Thu 12PM–12AM, Fri–Sat 12PM–3AM, Sun 12PM–12AM"),
        MiamiExample(name="The Corner", neighborhood="Downtown", description="Craft cocktail bar with rotating live jazz acts and an intimate vibe.", hours="Tue–Sat 7PM–2AM"),
    ],
    "rooftop bars": [
        MiamiExample(name="Sugar", neighborhood="Brickell", description="Rooftop bar atop EAST hotel with lush tropical decor and stunning skyline views.", hours="Mon–Wed 5PM–12AM, Thu–Sat 5PM–2AM, Sun 5PM–12AM"),
        MiamiExample(name="Watr at 1 Hotel Rooftop", neighborhood="South Beach", description="Poolside rooftop with ocean views and Nikkei-inspired small plates.", hours="Mon–Sun 12PM–10PM"),
        MiamiExample(name="Area 31", neighborhood="Downtown", description="16th-floor terrace bar overlooking the Miami River and Biscayne Bay.", hours="Mon–Thu 6:30AM–11PM, Fri–Sat 6:30AM–12AM, Sun 6:30AM–10PM"),
    ],
    "art galleries": [
        MiamiExample(name="Pérez Art Museum Miami (PAMM)", neighborhood="Downtown", description="Waterfront contemporary art museum with rotating exhibitions and bay views.", hours="Thu–Tue 11AM–6PM, Closed Wed"),
        MiamiExample(name="Rubell Museum", neighborhood="Allapattah", description="One of the largest private contemporary art collections in North America.", hours="Wed–Sun 10:30AM–5:30PM"),
        MiamiExample(name="Wynwood Walls", neighborhood="Wynwood", description="Open-air street art museum with large-scale murals from artists worldwide.", hours="Mon–Sat 11AM–7PM, Sun 11AM–5PM"),
    ],
    "farmers markets": [
        MiamiExample(name="Coconut Grove Organic Market", neighborhood="Coconut Grove", description="Saturday morning market with organic produce, fresh juices, and vegan bites.", hours="Sat 10AM–7PM"),
        MiamiExample(name="Lincoln Road Farmers Market", neighborhood="South Beach", description="Sunday market on the pedestrian mall with produce, flowers, and artisan goods.", hours="Sun 9AM–6:30PM"),
        MiamiExample(name="Upper Buena Vista Market", neighborhood="Little Haiti", description="Vibrant weekend market with local food vendors, art, and live music.", hours="Sat 10AM–3PM"),
    ],
    "beach activities": [
        MiamiExample(name="South Beach", neighborhood="South Beach", description="Iconic beach with turquoise water, volleyball courts, and lively boardwalk.", hours="Open 24 hours; lifeguards 9AM–6PM"),
        MiamiExample(name="Crandon Park Beach", neighborhood="Key Biscayne", description="Family-friendly beach with calm shallow water, picnic areas, and nature trails.", hours="Mon–Sun 8AM–Sunset"),
        MiamiExample(name="Bill Baggs Cape Florida State Park", neighborhood="Key Biscayne", description="Pristine beach with a historic lighthouse, kayaking, and snorkeling.", hours="Mon–Sun 8AM–Sunset"),
    ],
    "sports": [
        MiamiExample(name="Flamingo Park", neighborhood="Miami Beach", description="Public park with soccer/football fields, tennis courts, and a pool.", hours="Mon–Sun 8AM–9PM"),
        MiamiExample(name="Tropical Park", neighborhood="Westchester", description="Large park with multiple soccer fields, jogging trails, and sports facilities.", hours="Mon–Sun 7AM–10PM"),
        MiamiExample(name="Hard Rock Stadium", neighborhood="Miami Gardens", description="Home of the Miami Dolphins (NFL) and Inter Miami CF (MLS), major sports events year-round.", hours="Event days; tours Mon–Fri 10AM–4PM"),
    ],
    "nightlife": [
        MiamiExample(name="LIV", neighborhood="Miami Beach", description="World-famous nightclub at Fontainebleau with top DJs and A-list crowds.", hours="Wed, Fri, Sat 11PM–5AM"),
        MiamiExample(name="E11EVEN", neighborhood="Downtown", description="24/7 ultraclub with live performances, DJs, and an electric atmosphere.", hours="Open 24/7"),
        MiamiExample(name="Basement", neighborhood="Miami Beach", description="Subterranean club with a bowling alley, ice-skating rink, and dance floor.", hours="Thu–Sun 10PM–5AM"),
    ],
    "coffee shops": [
        MiamiExample(name="Panther Coffee", neighborhood="Wynwood", description="Local specialty roaster serving single-origin brews in a warehouse-style space.", hours="Mon–Sun 7AM–9PM"),
        MiamiExample(name="All Day", neighborhood="Design District", description="Trendy café with craft espresso, pastries, and a minimalist vibe.", hours="Mon–Sat 7AM–6PM, Sun 8AM–5PM"),
        MiamiExample(name="Threefold Café", neighborhood="Coral Gables", description="Australian-style café with flat whites, avocado toast, and brunch.", hours="Mon–Fri 7AM–4PM, Sat–Sun 8AM–4PM"),
    ],
    "brunch": [
        MiamiExample(name="Greenstreet Café", neighborhood="Coconut Grove", description="Local favorite for outdoor brunch with bottomless mimosas and people-watching.", hours="Mon–Sun 7:30AM–12AM"),
        MiamiExample(name="Boia De", neighborhood="Upper Buena Vista", description="Intimate kitchen serving creative brunch dishes with Italian and Asian flair.", hours="Wed–Sun 6PM–10PM; Brunch Sat–Sun 11AM–3PM"),
        MiamiExample(name="The Salty Donut", neighborhood="Wynwood", description="Artisan donut shop with creative flavors, coffee, and weekend brunch items.", hours="Mon–Sun 8AM–5PM"),
    ],
}

# All categories we can show examples for
VALID_CATEGORIES = sorted(MIAMI_VENUES.keys())

# ---------------------------------------------------------------------------
# Typos / variant -> canonical category
# ---------------------------------------------------------------------------

TYPO_TO_CANONICAL: Dict[str, str] = {
    "gallaries": "art galleries", "galeries": "art galleries", "gallary": "art galleries",
    "galery": "art galleries", "galleri": "art galleries", "gallerys": "art galleries",
    "art gallery": "art galleries", "art gallaries": "art galleries",
    "restraunt": "food", "resturant": "food", "restaurants": "food", "restaurant": "food",
    "resto": "food", "restobar": "food", "restobars": "food",
    "rooftop bar": "rooftop bars", "rooftop": "rooftop bars",
    "farmers market": "farmers markets", "farmer market": "farmers markets",
    "farmers": "farmers markets", "farmer": "farmers markets",
    "beach activity": "beach activities", "beach": "beach activities",
    "live music": "live jazz", "jazz": "live jazz", "music": "live jazz",
    "concerts": "live jazz", "live band": "live jazz",
    "mexican": "mexican food", "tacos": "mexican food", "taco": "mexican food",
    "football": "sports", "soccer": "sports", "play football": "sports", "play soccer": "sports",
    "clubs": "nightlife", "clubbing": "nightlife", "party": "nightlife", "dancing": "nightlife",
    "coffee": "coffee shops", "cafe": "coffee shops", "café": "coffee shops",
    "eating": "food", "dining": "food", "eat out": "food",
}

# Keywords in user message -> canonical (for fallback detection)
INTEREST_KEYWORDS: List[tuple] = [
    (["live music", "live musix", "live musik", "music", "jazz", "concerts", "live band"], "live jazz"),
    (["food", "restaurant", "restaurants", "resto", "restobar", "restobars", "eating", "dining", "eat out", "restraunt", "resturant"], "food"),
    (["mexican", "tacos", "taco"], "mexican food"),
    (["rooftop", "bars with a view"], "rooftop bars"),
    (["art", "gallery", "galleries", "gallaries", "galeries", "gallary", "galery", "galleri", "museum", "museums"], "art galleries"),
    (["farmers market", "farmers markets", "farmers", "farmer", "market"], "farmers markets"),
    (["beach", "beaches", "swimming", "sunbathe", "surfing"], "beach activities"),
    (["football", "soccer", "sports", "play football", "play soccer", "sport"], "sports"),
    (["nightlife", "clubs", "clubbing", "party", "dancing"], "nightlife"),
    (["coffee", "cafe", "café", "espresso", "latte"], "coffee shops"),
    (["brunch", "mimosa", "breakfast"], "brunch"),
]

# ---------------------------------------------------------------------------
# Interest extraction helpers
# ---------------------------------------------------------------------------

def choose_interest_label(raw: str) -> str:
    key = raw.strip().lower()
    if not key:
        return raw.strip()
    if key in TYPO_TO_CANONICAL:
        return TYPO_TO_CANONICAL[key]
    for typo, canonical in TYPO_TO_CANONICAL.items():
        if typo in key:
            return canonical
    for canonical in MIAMI_VENUES:
        if canonical in key or key in canonical:
            return canonical
    return raw.strip()


def get_examples(interest: str) -> List[MiamiExample]:
    label = choose_interest_label(interest)
    if label in MIAMI_VENUES:
        return MIAMI_VENUES[label]
    for key, venues in MIAMI_VENUES.items():
        if key.split()[0] in interest.lower():
            return venues
    return []


def _user_rejects_interest(msg: str, interest: str) -> bool:
    """True if the user is saying they do NOT want this interest (e.g. 'i dont want brunch spots')."""
    t = msg.strip().lower()
    interest_lower = interest.lower()
    if not t or not interest_lower:
        return False
    # Negation phrases that indicate rejection
    neg_phrases = [
        "don't want", "dont want", "do not want", "not into", "skip", "without",
        "avoid", "not interested in", "never want", "don't need", "dont need",
        "no interest in", "not a fan of", "don't like", "dont like",
    ]
    has_neg = any(np in t for np in neg_phrases) or t.startswith("no ") or " not " in t
    if not has_neg:
        return False
    # Message negates something; check if it's this interest
    if interest_lower in t:
        return True
    for word in interest_lower.split():
        if len(word) > 2 and word in t:
            return True
    return False


def extract_interest_fallback(msg: str, existing: List[str]) -> Optional[str]:
    text = msg.strip().lower()
    if not text or text in ("hi", "hello", "hey", "hi there", "hello there", "yo", "sup"):
        return None
    if (text.startswith("yes") or text.startswith("no")) and len(text) < 60:
        return None
    # Direct typo map (skip if user said they don't want this)
    if text in TYPO_TO_CANONICAL:
        cand = TYPO_TO_CANONICAL[text]
        if cand.lower() not in [i.lower() for i in existing] and not _user_rejects_interest(msg, cand):
            return cand
    # Keyword scan
    for keywords, canonical in INTEREST_KEYWORDS:
        for kw in keywords:
            if kw in text and canonical.lower() not in [i.lower() for i in existing]:
                if not _user_rejects_interest(msg, canonical):
                    return canonical
    return None


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

GREETING = (
    "Hey! I'm your HelloCity guide. Just tell me what you're into when you're out in the city. "
    "Like food, live music, art, rooftop bars, the beach, nightlife, whatever."
)


def _remaining_options(existing: List[str]) -> str:
    remaining = [c for c in VALID_CATEGORIES if c.lower() not in [i.lower() for i in existing]]
    return ", ".join(remaining[:5])


def _get_openai_api_key() -> Optional[str]:
    """
    Resolve the OpenAI API key.

    - Locally: comes from .env via load_dotenv() (OPENAI_API_KEY).
    - In production (GCP): prefer OPENAI_API_KEY env var; if missing and
      google-cloud-secret-manager is available, try Secret Manager.
    """
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key.strip()

    # Optional: fall back to Secret Manager when running on GCP
    if secretmanager is None:
        return None

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT")
    if not project_id:
        return None

    # Secret name can be overridden; default is "openai-api-key"
    secret_id = os.getenv("OPENAI_SECRET_NAME", "openai-api-key")

    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(name=name)
        payload = response.payload.data.decode("utf-8")
        return (payload or "").strip()
    except Exception:
        return None


def _llm_one_line(prompt: str, fallback: str) -> str:
    """Ask the LLM for a single short, casual sentence. Falls back to static text when no key."""
    api_key = _get_openai_api_key()
    if not api_key or OpenAI is None:
        return fallback
    try:
        client = OpenAI(api_key=api_key.strip())
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "You are HelloCity's friendly assistant. "
                    "Reply with exactly ONE short casual sentence. "
                    "Sound like you're texting a friend. No quotes, no preamble, no lists."
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=0.9,
            max_tokens=60,
        )
        raw = (resp.choices[0].message.content or "").strip().strip('"')
        return raw if raw else fallback
    except Exception:
        return fallback


def _examples_intro(interest: str) -> str:
    fallback = f"Here are some spots in Miami for {interest}."
    return _llm_one_line(
        f"The user said they like '{interest}'. Reply in one short casual sentence: acknowledge and say you're showing Miami spots. "
        "Use a comma or period, not an em dash (—). Do NOT say 'you're going to love' or 'I found' or 'awesome'. "
        "Examples: 'Nice, here are some spots for that.' 'Got it. Here are some Miami spots for " + interest + ".'",
        fallback,
    )


def _progress_message(existing: List[str]) -> str:
    n = len(existing)
    needed = 3 - n
    if needed <= 0:
        return "All done! Here's your Miami profile."
    opts = _remaining_options(existing)
    if n == 0:
        return GREETING
    fallback = f"Got it. {needed} more and we're set. What else? Maybe {opts}?"
    return _llm_one_line(
        f"We've collected {n} interest(s) so far. We need {needed} more. "
        f"Tell the user how many more you need and casually suggest these: {opts}. "
        "One sentence, friendly.",
        fallback,
    )


def _unknown_message(existing: List[str]) -> str:
    n = len(existing)
    needed = 3 - n
    opts = _remaining_options(existing)
    if n == 0:
        fallback = f"Hmm, not sure I got that. Try something like: {opts}?"
    else:
        fallback = f"Didn't catch that one. So far I have: {', '.join(existing)}. Need {needed} more. Maybe {opts}?"
    return _llm_one_line(
        f"The user said something you couldn't match to an activity category. "
        f"Interests so far: {existing}. Need {needed} more. Available options: {opts}. "
        "Let them know gently and suggest options. One sentence, casual, no lists.",
        fallback,
    )


def _duplicate_interest_message(existing: List[str], duplicate_label: str) -> str:
    """When the user named an interest we already have; acknowledge and suggest something different."""
    opts = _remaining_options(existing)
    fallback = f"You already have {duplicate_label} in your list. What else? Maybe {opts}?"
    return _llm_one_line(
        f"The user said something that maps to '{duplicate_label}', which is already in their list. "
        f"Tell them you already have that one and ask for a different interest. Suggest: {opts}. One sentence, casual.",
        fallback,
    )


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def _parse_llm_json(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def call_llm(messages: List[ChatMessage], existing: List[str]) -> Dict[str, Any]:
    api_key = _get_openai_api_key()
    if not api_key or OpenAI is None:
        # Mock mode: use keyword fallback, return a reasonable message
        user_text = ""
        for msg in reversed(messages):
            if msg.role == "user":
                user_text = msg.content
                break
        fb = extract_interest_fallback(user_text, existing)
        if fb:
            return {"assistant_message": _examples_intro(fb), "interest_candidates": [fb]}
        if not existing:
            return {"assistant_message": GREETING, "interest_candidates": []}
        return {"assistant_message": _unknown_message(existing), "interest_candidates": []}

    client = OpenAI(api_key=api_key.strip())
    n = len(existing)
    needed = 3 - n
    state_info = f"Interests so far: {existing}. Need {needed} more." if existing else "No interests yet. Need 3."
    cats = ", ".join(VALID_CATEGORIES)

    system_prompt = (
        "You are HelloCity's onboarding assistant helping users find what they love to do in Miami. "
        "Sound casual and natural, like you're texting a friend. No corporate or robotic phrases. Use contractions, short sentences, and a warm tone.\n\n"
        f"STATE: {state_info}\nVALID CATEGORIES: {cats}\n\n"
        "RULES:\n"
        "1. When the user says they do NOT want something (e.g. 'i dont want brunch', 'no brunch', 'not into art'), "
        "set interest_candidates to [] and reply acknowledging that and asking what they'd like instead. Do NOT suggest that category.\n"
        "2. When the user greets you (hi/hello/hey), reply in a relaxed way and ask what they're into. Mention 2-3 categories they haven't picked yet.\n"
        "3. When the user mentions an activity they LIKE, map it to the closest valid category. Be generous with typos and variants.\n"
        "4. When you detect an interest, set interest_candidates to [category_label] and assistant_message to ONE short casual sentence (e.g. 'Nice, here are some spots for that.' or 'Got it. Here are some Miami spots for that.'). No em dashes (—). No 'you're going to love' or 'I found' or 'awesome'. Do NOT ask what they like again.\n"
        "5. When you CANNOT map to any category, set interest_candidates to [] and assistant_message should say you didn't get it and suggest options. Keep it friendly.\n"
        "6. NEVER repeat the exact same message. Vary your wording.\n\n"
        "Return ONLY valid JSON: {\"assistant_message\": \"...\", \"interest_candidates\": [...]}. No markdown."
    )

    api_messages = [{"role": "system", "content": system_prompt}]
    api_messages += [{"role": m.role, "content": m.content} for m in messages]

    try:
        resp = client.chat.completions.create(model="gpt-4o-mini", messages=api_messages, temperature=0.8)
        raw = resp.choices[0].message.content or "{}"
    except Exception:
        return {"assistant_message": _unknown_message(existing), "interest_candidates": []}

    data = _parse_llm_json(raw)
    candidates = data.get("interest_candidates")
    if not isinstance(candidates, list):
        candidates = []
    msg = data.get("assistant_message") or _unknown_message(existing)

    return {"assistant_message": msg, "interest_candidates": candidates}


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session_id = get_or_create_session(req.session_id)
    state = SESSIONS[session_id]

    # --- Handle Yes/No confirmation (don't call LLM) ---
    if req.confirmed is not None:
        state.awaiting_confirmation = False
        is_complete = len(state.interests) >= 3
        if is_complete:
            profile = {"interests": state.interests[:3]}
            msg = "All set! Here's your Miami profile."
        else:
            msg = _progress_message(state.interests)
            profile = None
        state.messages.append(ChatMessage(role="assistant", content=msg))
        return ChatResponse(
            session_id=session_id, assistant_message=msg,
            interests=state.interests, interests_count=len(state.interests),
            examples=[], is_complete=is_complete, profile=profile,
        )

    # --- Normal message ---
    state.messages.append(ChatMessage(role="user", content=req.message))

    # Call LLM
    llm_result = call_llm(state.messages, state.interests)
    assistant_message = llm_result["assistant_message"]
    candidates = llm_result.get("interest_candidates") or []

    # Backend fallback if LLM returned nothing
    if not candidates:
        fb = extract_interest_fallback(req.message, state.interests)
        if fb:
            candidates = [fb]
            assistant_message = _examples_intro(fb)

    # Find the first new interest (skip if user explicitly rejected it, e.g. "i dont want brunch")
    new_interest: Optional[str] = None
    handled_rejection = False
    duplicate_label: Optional[str] = None  # first candidate that was already in list
    for cand in candidates:
        label = choose_interest_label(cand)
        if not label:
            continue
        if label.lower() in [i.lower() for i in state.interests]:
            if duplicate_label is None:
                duplicate_label = label
            continue
        if _user_rejects_interest(req.message, label):
            new_interest = None
            handled_rejection = True
            assistant_message = _llm_one_line(
                f"The user said they do NOT want '{label}'. Acknowledge that and ask what they'd like instead. One sentence, casual.",
                f"Got it, no {label}. What else are you into? Maybe {_remaining_options(state.interests)}?",
            )
        else:
            new_interest = label
        break

    # All candidates were duplicates: acknowledge and ask for something different
    if new_interest is None and not handled_rejection and duplicate_label is not None:
        assistant_message = _duplicate_interest_message(state.interests, duplicate_label)

    # Show examples and count the interest
    examples: List[MiamiExample] = []
    if new_interest:
        state.interests.append(new_interest)
        examples = get_examples(new_interest)
        state.awaiting_confirmation = True
    elif not candidates and not handled_rejection and duplicate_label is None:
        # No interest found — check if they were rejecting a category (e.g. "i dont want rooftop bar")
        rejected_category = None
        for cat in VALID_CATEGORIES:
            if _user_rejects_interest(req.message, cat):
                rejected_category = cat
                break
        if rejected_category:
            assistant_message = _llm_one_line(
                f"The user said they do NOT want '{rejected_category}'. Acknowledge that clearly, then suggest other options. One sentence, casual.",
                f"Got it, no {rejected_category}. What else are you into? Maybe {_remaining_options(state.interests)}?",
            )
        else:
            assistant_message = _unknown_message(state.interests) if state.interests or req.message.strip().lower() not in ("hi", "hello", "hey", "hi!", "hi there", "hello there") else GREETING

    state.messages.append(ChatMessage(role="assistant", content=assistant_message))

    # Only show profile after they've seen examples and clicked Yes/No (not in the same response as examples)
    if examples:
        is_complete = False
        profile = None
    else:
        is_complete = len(state.interests) >= 3
        profile = {"interests": state.interests[:3]} if is_complete else None

    return ChatResponse(
        session_id=session_id, assistant_message=assistant_message,
        interests=state.interests, interests_count=len(state.interests),
        examples=examples, is_complete=is_complete, profile=profile,
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/llm-status")
def llm_status():
    api_key = _get_openai_api_key()
    if not api_key:
        return {"llm": "mock", "message": "No OPENAI_API_KEY found in env or Secret Manager. Using mock responses."}
    if OpenAI is None:
        return {"llm": "mock", "message": "openai package not installed."}
    try:
        client = OpenAI(api_key=api_key.strip())
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Reply with only OK"}],
            max_tokens=5,
        )
        return {"llm": "openai", "status": "ok", "message": "API key valid.", "test_reply": (r.choices[0].message.content or "").strip()[:20]}
    except Exception as e:
        return {"llm": "openai", "status": "error", "message": str(e)}
