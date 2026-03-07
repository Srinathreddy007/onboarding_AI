import json
import os
import re
import time
import uuid
from typing import List, Optional, Dict, Any

import requests
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
        self.last_examples: List[MiamiExample] = []


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

# Static venue data commented out so only dynamic (Google Places + LLM) are used for cards.
# Full MIAMI_VENUES dict is in git history; uncomment and restore here to re-enable static fallback.
MIAMI_VENUES: Dict[str, List[MiamiExample]] = {}

# Example interests used only for conversational suggestions in prompts and copy.
# The LLM is not limited to this list.
EXAMPLE_INTEREST_SUGGESTIONS: List[str] = [
    "live music",
    "coffee shops",
    "movies",
    "outdoor activities",
    "art galleries",
    "shopping",
    "rooftop bars",
    "beach activities",
    "food",
    "mexican food",
    "farmers markets",
    "racket sports",
    "sports",
    "arcades and gaming",
    "family fun",
    "nightlife",
    "brunch",
    "yoga and wellness",
    "water sports",
    "water parks",
    "shopping",
    "sightseeing",
    "fitness",
]

OPENING_INTEREST_SUGGESTIONS: List[str] = [
    "coffee shops",
    "movies",
    "outdoor activities",
    "live music",
    "art galleries",
    "shopping",
    "rooftop bars",
    "beach activities",
    "nightlife",
    "food",
]

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
GOOGLE_PLACES_ENDPOINT = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# Simple in-memory cache for Places results: {search_query: {"ts": float, "examples": List[MiamiExample]}}
PLACES_CACHE: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Interest mapping layers
# ---------------------------------------------------------------------------
#
# 1. NORMALIZED_CATEGORY_ALIASES:
#    Static typo / synonym cleanup for backend recovery when the LLM is vague.
# 2. FALLBACK_KEYWORD_CATEGORIES and SEMANTIC_CATEGORY_PATTERNS:
#    Extra backend-only extraction rules for common phrases.
# 3. CANONICAL_CATEGORY_SEARCH_QUERIES:
#    Canonical supported search labels that map cleanly to real Miami place searches.
#    The LLM can still propose labels outside this set, but these are the backend's
#    strongest supported categories for search and suggestion copy.

NORMALIZED_CATEGORY_ALIASES: Dict[str, str] = {
    # Art
    "gallaries": "art galleries", "galeries": "art galleries", "gallary": "art galleries",
    "galery": "art galleries", "galleri": "art galleries", "gallerys": "art galleries",
    "art gallery": "art galleries", "art gallaries": "art galleries", "museums": "art galleries",
    # Food
    "restraunt": "food", "resturant": "food", "restaurants": "food", "restaurant": "food",
    "resto": "food", "restobar": "food", "restobars": "food", "diners": "food", "diner": "food",
    "eating": "food", "dining": "food", "eat out": "food",
    # Mexican
    "mexican": "mexican food", "tacos": "mexican food", "taco": "mexican food",
    # Rooftop
    "rooftop bar": "rooftop bars", "rooftop": "rooftop bars",
    # Farmers
    "farmers market": "farmers markets", "farmer market": "farmers markets",
    "farmers": "farmers markets", "farmer": "farmers markets",
    # Beach
    "beach activity": "beach activities", "beach": "beach activities",
    "swimming": "beach activities", "swim": "beach activities",
    # Music
    "live music": "live music", "jazz": "live music", "music": "live music",
    "concerts": "live music", "live band": "live music", "live jazz": "live music",
    # Sports
    "football": "sports", "soccer": "sports", "play football": "sports", "play soccer": "sports",
    "basketball": "sports", "baseball": "sports",
    # Nightlife
    "clubs": "nightlife", "clubbing": "nightlife", "party": "nightlife", "dancing": "nightlife",
    "dance": "nightlife",
    # Coffee
    "coffee": "coffee shops", "cafe": "coffee shops", "café": "coffee shops",
    # Brunch
    "breakfast": "brunch",
    # Movies / Cinema
    "movies": "movies", "movie": "movies", "cinema": "movies", "cinemas": "movies",
    "film": "movies", "films": "movies", "movie theater": "movies", "movie theatre": "movies",
    # Outdoor
    "hiking": "outdoor activities", "hikes": "outdoor activities", "hike": "outdoor activities",
    "trek": "outdoor activities", "treks": "outdoor activities", "trekking": "outdoor activities",
    "parks": "outdoor activities", "park": "outdoor activities", "trails": "outdoor activities",
    "nature": "outdoor activities", "walks": "outdoor activities", "walk": "outdoor activities",
    "dog walking": "outdoor activities", "dog walk": "outdoor activities",
    # Racket sports
    "padel": "racket sports", "paddle": "racket sports", "tennis": "racket sports",
    "pickleball": "racket sports", "badminton": "racket sports", "squash": "racket sports",
    # Arcades / Gaming
    "arcade": "arcades and gaming", "arcades": "arcades and gaming", "gaming": "arcades and gaming",
    "bowling": "arcades and gaming", "go-karts": "arcades and gaming",
    "go karts": "arcades and gaming", "escape room": "arcades and gaming",
    # Yoga / Wellness
    "yoga": "yoga and wellness", "wellness": "yoga and wellness", "spa": "yoga and wellness",
    "meditation": "yoga and wellness", "pilates": "yoga and wellness",
    # Water sports
    "kayaking": "water sports", "kayak": "water sports", "paddleboard": "water sports",
    "jet ski": "water sports", "snorkeling": "water sports", "scuba": "water sports",
    "surfing": "water sports", "kiteboarding": "water sports",
    # Water parks
    "water park": "water parks", "waterpark": "water parks", "waterparks": "water parks",
    "water world": "water parks", "waterworld": "water parks",
    "water slides": "water parks", "water slide": "water parks", "water rides": "water parks",
    "waterride": "water parks", "waterrides": "water parks",
    # Shopping
    "shopping": "shopping", "shop": "shopping", "shops": "shopping", "mall": "shopping",
    "boutiques": "shopping",
    # Family
    "family": "family fun", "kids": "family fun", "children": "family fun",
    "zoo": "family fun", "aquarium": "family fun",
    # Sightseeing
    "sightseeing": "sightseeing", "sight seeing": "sightseeing", "tours": "sightseeing",
    "tour": "sightseeing", "landmarks": "sightseeing",
    # Fitness
    "gym": "fitness", "fitness": "fitness", "workout": "fitness", "crossfit": "fitness",
    "running": "fitness", "jogging": "fitness",
}

FALLBACK_KEYWORD_CATEGORIES: List[tuple[list[str], str]] = [
    (["live music", "live musix", "live musik", "music", "jazz", "concerts", "live band"], "live music"),
    (["food", "restaurant", "restaurants", "resto", "restobar", "restobars", "eating", "dining", "eat out", "restraunt", "resturant", "diner", "diners"], "food"),
    (["mexican", "tacos", "taco"], "mexican food"),
    (["rooftop", "bars with a view"], "rooftop bars"),
    (["art", "gallery", "galleries", "gallaries", "galeries", "gallary", "museum", "museums"], "art galleries"),
    (["farmers market", "farmers markets", "farmers", "farmer", "market"], "farmers markets"),
    (["beach", "beaches", "sunbathe", "swim", "swimming"], "beach activities"),
    (["football", "soccer", "sports", "play football", "play soccer", "sport", "basketball", "baseball"], "sports"),
    (["nightlife", "clubs", "clubbing", "party", "dancing", "dance"], "nightlife"),
    (["coffee", "cafe", "café", "espresso", "latte"], "coffee shops"),
    (["brunch", "mimosa", "breakfast"], "brunch"),
    (["movie", "movies", "cinema", "cinemas", "film", "films", "movie theater", "theater", "theatre"], "movies"),
    (["hik", "trek", "trekking", "park", "trail", "nature", "walk", "outdoor", "dog walk", "long walk"], "outdoor activities"),
    (["padel", "paddle", "tennis", "pickleball", "badminton", "squash", "racket"], "racket sports"),
    (["arcade", "gaming", "bowling", "go-kart", "escape room"], "arcades and gaming"),
    (["yoga", "wellness", "spa", "meditation", "pilates"], "yoga and wellness"),
    (["water park", "waterpark", "waterparks", "water world", "waterworld", "water slide", "water slides", "water rides", "waterride", "waterrides"], "water parks"),
    (["kayak", "paddleboard", "jet ski", "snorkel", "scuba", "surf", "kite"], "water sports"),
    (["shopping", "shop", "mall", "boutique"], "shopping"),
    (["family", "kids", "children", "zoo", "aquarium"], "family fun"),
    (["sightseeing", "tour", "landmark", "sight"], "sightseeing"),
    (["gym", "fitness", "workout", "crossfit", "running", "jogging"], "fitness"),
]

CANONICAL_CATEGORY_SEARCH_QUERIES: Dict[str, str] = {
    "live music": "live music venues",
    "food": "restaurants",
    "mexican food": "mexican restaurants",
    "rooftop bars": "rooftop bars",
    "art galleries": "art galleries",
    "farmers markets": "farmers markets",
    "beach activities": "beach activities",
    "outdoor activities": "parks and hiking trails",
    "racket sports": "padel tennis pickleball courts",
    "sports": "sports bars and stadium activities",
    "movies": "movie theaters",
    "arcades and gaming": "arcades and family entertainment centers",
    "family fun": "family attractions",
    "nightlife": "nightlife spots",
    "coffee shops": "coffee shops",
    "brunch": "brunch spots",
    "yoga and wellness": "yoga studios and wellness spots",
    "water sports": "water sports rentals",
    "water parks": "water parks",
    "shopping": "shopping centers and boutiques",
    "sightseeing": "sightseeing attractions",
    "fitness": "fitness studios and gyms",
}

SUPPORTED_SEARCH_CATEGORIES: List[str] = list(CANONICAL_CATEGORY_SEARCH_QUERIES.keys())

SEMANTIC_CATEGORY_PATTERNS: List[tuple[list[str], str]] = [
    (["movie theater", "movie theatre", "going to movies", "going to the movies", "cinema", "cinemas", "films", "movies"], "movies"),
    (["arcades", "arcade", "gaming", "bowling", "go karts", "go-karts", "escape room"], "arcades and gaming"),
    (["padel", "tennis", "pickleball", "badminton", "squash"], "racket sports"),
    (["long walks", "walks with my dog", "walk with my dog", "parks", "park", "hiking", "hikes", "hike", "trails", "nature"], "outdoor activities"),
    (["swimming", "swim", "beach"], "beach activities"),
    (["dancing", "dance", "clubs", "nightlife"], "nightlife"),
    (["coffee", "cafe", "café"], "coffee shops"),
    (["brunch", "breakfast"], "brunch"),
]

FOOD_INTEREST_TERMS: set[str] = {
    "food",
    "foods",
    "restaurant",
    "restaurants",
    "cuisine",
    "eatery",
    "eateries",
}

FOOD_DESCRIPTOR_STOPWORDS: set[str] = {
    "a",
    "an",
    "and",
    "any",
    "around",
    "best",
    "cool",
    "find",
    "for",
    "good",
    "great",
    "here",
    "in",
    "kind",
    "like",
    "local",
    "looking",
    "maybe",
    "more",
    "near",
    "nearby",
    "of",
    "option",
    "options",
    "or",
    "place",
    "places",
    "restaurant",
    "restaurants",
    "some",
    "spot",
    "spots",
    "the",
    "town",
    "type",
    "types",
    "want",
    "where",
}

SMALL_TALK_PATTERNS: List[str] = [
    "how are you",
    "who are you",
    "what are you",
    "what model",
    "how can you help",
    "help me",
    "what do you do",
    "what can you do",
]

MODEL_QUESTION_PATTERNS: List[str] = [
    "what model",
    "which model",
    "are you gpt",
    "what ai",
]

HELP_QUESTION_PATTERNS: List[str] = [
    "how can you help",
    "help me",
    "what can you do",
    "what do you do",
]

SOCIAL_MESSAGE_PATTERNS: List[str] = [
    "i love you",
    "love you",
    "thank you",
    "thanks",
    "bye",
    "goodbye",
    "see you",
]

HOSTILE_MESSAGE_PATTERNS: List[str] = [
    "you are dumb",
    "you're dumb",
    "what is your problem",
    "why are you forcing",
    "why you repeating",
    "why are you repeating",
    "are you a parrot",
    "stupid",
]

IDENTITY_QUESTION_PATTERNS: List[str] = [
    "who are you",
    "what are you",
]

OUT_OF_SCOPE_PATTERNS: List[str] = [
    "weather",
    "temperature",
    "rain",
    "forecast",
    "time is it",
    "what time",
    "date today",
    "what day",
    "news",
    "stock price",
    "bitcoin price",
    "score today",
]

QUESTION_LEADERS: List[str] = [
    "what",
    "whats",
    "what's",
    "how",
    "hows",
    "how's",
    "who",
    "can",
    "could",
    "will",
    "would",
    "is",
    "are",
    "do",
    "does",
    "tell",
]

MODEL_HINT_TOKENS: set[str] = {"model", "version", "gpt", "llm", "ai", "engine"}
HELP_HINT_TOKENS: set[str] = {"help", "assist", "do", "can", "find", "support"}
IDENTITY_HINT_TOKENS: set[str] = {"who", "what", "name", "assistant", "bot", "guide"}
WEATHER_HINT_TOKENS: set[str] = {"weather", "temperature", "temp", "forecast", "rain", "raining", "sunny", "humid", "humidity", "wind", "outside"}
TIME_HINT_TOKENS: set[str] = {"time", "date", "day", "today", "tomorrow", "clock"}
NEWS_HINT_TOKENS: set[str] = {"news", "headline", "headlines", "score", "scores", "price", "prices", "stock", "stocks", "bitcoin", "btc", "traffic"}

# ---------------------------------------------------------------------------
# Interest extraction helpers
# ---------------------------------------------------------------------------

def choose_interest_label(raw: str) -> str:
    key = raw.strip().lower()
    if not key:
        return raw.strip()
    specific_food = _extract_specific_food_candidate(key)
    if specific_food:
        return specific_food["label"]
    if key in NORMALIZED_CATEGORY_ALIASES:
        return NORMALIZED_CATEGORY_ALIASES[key]
    for canonical in sorted(SUPPORTED_SEARCH_CATEGORIES, key=len, reverse=True):
        if key == canonical:
            return canonical
    for typo, canonical in NORMALIZED_CATEGORY_ALIASES.items():
        if typo in key:
            return canonical
    for canonical in sorted(SUPPORTED_SEARCH_CATEGORIES, key=len, reverse=True):
        if canonical in key or key in canonical:
            return canonical
    for canonical in MIAMI_VENUES:
        if canonical in key or key in canonical:
            return canonical
    return raw.strip()


def canonical_search_query(label: str) -> str:
    canonical = choose_interest_label(label)
    return CANONICAL_CATEGORY_SEARCH_QUERIES.get(canonical, canonical)


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s']", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _text_tokens(text: str) -> set[str]:
    normalized = _normalize_text(text)
    return set(normalized.split()) if normalized else set()


def _contains_normalized_phrase(text: str, phrase: str) -> bool:
    normalized_text = _normalize_text(text)
    normalized_phrase = _normalize_text(phrase)
    if not normalized_text or not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {normalized_text} "


def _looks_like_question(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    first = normalized.split()[0]
    return "?" in text or first in QUESTION_LEADERS


def _should_try_typo_recovery(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    tokens = normalized.split()
    compact = normalized.replace(" ", "")
    if any(marker in compact for marker in ("waterrides", "waterride", "coffeeshops", "pedal", "moviez")):
        return True
    return len(tokens) <= 6 and any(len(token) >= 8 for token in tokens)


def _extract_specific_food_candidate(text: str) -> Optional[Dict[str, str]]:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    tokens = normalized.split()
    if not tokens:
        return None

    for idx, token in enumerate(tokens):
        if token not in FOOD_INTEREST_TERMS:
            continue
        descriptor_tokens: List[str] = []
        back = idx - 1
        while back >= 0 and len(descriptor_tokens) < 2:
            candidate = tokens[back]
            if candidate in FOOD_DESCRIPTOR_STOPWORDS:
                if descriptor_tokens:
                    break
                back -= 1
                continue
            descriptor_tokens.insert(0, candidate)
            back -= 1
        if not descriptor_tokens:
            continue
        descriptor = " ".join(descriptor_tokens).strip()
        if not descriptor or descriptor in {"food", "restaurant", "restaurants"}:
            continue
        return {
            "label": f"{descriptor} food",
            "search_query": f"{descriptor} restaurants",
        }

    return None


def _is_self_introduction(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    intro_markers = ("i am ", "i'm ", "my name is ", "im ")
    has_intro = any(marker in normalized for marker in intro_markers)
    has_greeting = normalized.startswith(("hi", "hello", "hey"))
    short_message = len(normalized.split()) <= 8
    return has_intro and (has_greeting or short_message)


def _is_small_talk(text: str) -> bool:
    normalized = _normalize_text(text)
    if normalized in {"hi", "hello", "hey", "yo", "sup", "hi there", "hello there"}:
        return True
    if _is_self_introduction(text):
        return True
    return any(pattern in normalized for pattern in SMALL_TALK_PATTERNS)


def _is_social_message(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(pattern in normalized for pattern in SOCIAL_MESSAGE_PATTERNS)


def _is_hostile_message(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(pattern in normalized for pattern in HOSTILE_MESSAGE_PATTERNS)


def _small_talk_kind(text: str) -> str:
    normalized = _normalize_text(text)
    tokens = _text_tokens(text)
    if normalized in {"hi", "hello", "hey", "yo", "sup", "hi there", "hello there"}:
        return "greeting"
    if _is_self_introduction(text):
        return "introduction"
    if any(pattern in normalized for pattern in MODEL_QUESTION_PATTERNS):
        return "model"
    if MODEL_HINT_TOKENS.intersection(tokens) and ("what" in tokens or "which" in tokens or "using" in tokens or "powered" in tokens):
        return "model"
    if any(pattern in normalized for pattern in HELP_QUESTION_PATTERNS):
        return "help"
    if ("help" in tokens and "you" in tokens) or (HELP_HINT_TOKENS.intersection(tokens) and ("what" in tokens or "can" in tokens)):
        return "help"
    if any(pattern in normalized for pattern in IDENTITY_QUESTION_PATTERNS):
        return "identity"
    if "you" in tokens and (("who" in tokens) or ("what" in tokens and "are" in tokens) or ("your" in tokens and "name" in tokens)):
        return "identity"
    if "how are you" in normalized or "how are you doing" in normalized:
        return "how_are_you"
    if "you" in tokens and "how" in tokens and ({"doing", "today", "going", "well"} & tokens):
        return "how_are_you"
    return "generic"


def _is_out_of_scope_query(text: str) -> bool:
    normalized = _normalize_text(text)
    tokens = _text_tokens(text)
    if any(pattern in normalized for pattern in OUT_OF_SCOPE_PATTERNS):
        return True
    if WEATHER_HINT_TOKENS.intersection(tokens):
        return True
    if NEWS_HINT_TOKENS.intersection(tokens):
        return True
    if TIME_HINT_TOKENS.intersection(tokens) and _looks_like_question(text):
        return True
    return False


def _normalize_candidate(label: str, search_query: Optional[str] = None) -> Optional[Dict[str, str]]:
    raw_label = (label or "").strip()
    if not raw_label:
        return None

    raw_query = (search_query or raw_label).strip()
    specific_food = _extract_specific_food_candidate(raw_query) or _extract_specific_food_candidate(raw_label)

    normalized_label = choose_interest_label(raw_label)
    if specific_food and normalized_label == "food":
        normalized_label = specific_food["label"]
    normalized_key = _normalize_text(normalized_label)

    if normalized_label not in SUPPORTED_SEARCH_CATEGORIES:
        for phrases, canonical in SEMANTIC_CATEGORY_PATTERNS:
            if normalized_key == canonical or any(_contains_normalized_phrase(normalized_key, phrase) for phrase in phrases):
                normalized_label = canonical
                break

    query = raw_query
    if not query:
        query = normalized_label

    if specific_food and normalized_label == specific_food["label"]:
        query = specific_food["search_query"]
    elif normalized_label in CANONICAL_CATEGORY_SEARCH_QUERIES:
        query = CANONICAL_CATEGORY_SEARCH_QUERIES[normalized_label]

    return {"label": normalized_label, "search_query": query}


def extract_interest_fallbacks(msg: str, existing: List[str]) -> List[Dict[str, str]]:
    text = _normalize_text(msg)
    existing_lower = {item.lower() for item in existing}
    if not text or _is_small_talk(text):
        return []
    if (text.startswith("yes") or text.startswith("no")) and len(text) < 60:
        return []

    candidates: List[Dict[str, str]] = []
    seen: set[str] = set()

    specific_food = _extract_specific_food_candidate(text)
    if specific_food and specific_food["label"].lower() not in existing_lower and not _user_rejects_interest(msg, specific_food["label"]):
        seen.add(specific_food["label"].lower())
        candidates.append(specific_food)

    if text in NORMALIZED_CATEGORY_ALIASES:
        canonical = NORMALIZED_CATEGORY_ALIASES[text]
        normalized = _normalize_candidate(canonical)
        if normalized and normalized["label"].lower() not in existing_lower and not _user_rejects_interest(msg, normalized["label"]):
            seen.add(normalized["label"].lower())
            candidates.append(normalized)

    for phrases, canonical in SEMANTIC_CATEGORY_PATTERNS:
        if canonical.lower() in existing_lower or canonical.lower() in seen:
            continue
        if any(_contains_normalized_phrase(text, phrase) for phrase in phrases):
            if _user_rejects_interest(msg, canonical):
                continue
            normalized = _normalize_candidate(canonical)
            if normalized:
                seen.add(normalized["label"].lower())
                candidates.append(normalized)

    for keywords, canonical in FALLBACK_KEYWORD_CATEGORIES:
        if canonical.lower() in existing_lower or canonical.lower() in seen:
            continue
        if any(kw in text for kw in keywords):
            if _user_rejects_interest(msg, canonical):
                continue
            normalized = _normalize_candidate(canonical)
            if normalized:
                seen.add(normalized["label"].lower())
                candidates.append(normalized)

    return candidates


def get_examples(interest: str) -> List[MiamiExample]:
    label = choose_interest_label(interest)
    if label in MIAMI_VENUES:
        return MIAMI_VENUES[label]
    for key, venues in MIAMI_VENUES.items():
        if key.split()[0] in interest.lower():
            return venues
    return []


def _llm_suggest_places(search_query: str) -> List[MiamiExample]:
    """Ask LLM to suggest 3 real Miami places when Google Places is unavailable."""
    api_key = _get_openai_api_key()
    if not api_key or OpenAI is None:
        return []
    try:
        client = OpenAI(api_key=api_key.strip())
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "You suggest real places in Miami. Return ONLY a JSON array of 3 objects, "
                    "each with: name, neighborhood, description (one sentence), hours. "
                    "All places must be real and currently operating. No markdown, just the JSON array."
                )},
                {"role": "user", "content": f"Suggest 3 real places in Miami for: {search_query}"},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        raw = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*\]", raw)
        if m:
            items = json.loads(m.group(0))
            examples: List[MiamiExample] = []
            for item in items[:3]:
                examples.append(MiamiExample(
                    name=item.get("name", "Place in Miami"),
                    neighborhood=item.get("neighborhood", "Miami"),
                    description=item.get("description", "Popular spot in Miami."),
                    hours=item.get("hours", "See Google Maps for hours"),
                ))
            return examples
    except Exception:
        pass
    return []


def find_miami_places(search_query: str, limit: int = 3) -> List[MiamiExample]:
    """
    Dynamic venue discovery. Priority order:
    1. In-memory cache (TTL 7 days)
    2. Google Places Text Search API
    3. LLM-generated suggestions (real places)
    """
    key = search_query.strip().lower()
    if not key:
        return []

    now = time.time()

    # 1) Serve from cache if fresh
    cached = PLACES_CACHE.get(key)
    if cached and (now - cached.get("ts", 0)) < PLACES_TTL_SECONDS:
        return cached.get("examples", [])

    # 2) Try Google Places
    if GOOGLE_PLACES_API_KEY:
        params = {
            "query": f"{search_query} in Miami, FL",
            "key": GOOGLE_PLACES_API_KEY,
        }
        try:
            resp = requests.get(GOOGLE_PLACES_ENDPOINT, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")
            results = data.get("results", [])[:limit]
            if status == "OK" and results:
                examples: List[MiamiExample] = []
                for r in results:
                    name = r.get("name") or "Place in Miami"
                    vicinity = r.get("vicinity") or r.get("formatted_address") or "Miami"
                    rating = r.get("rating")
                    user_total = r.get("user_ratings_total")
                    rating_str = f" Rated {rating}/5 ({user_total} reviews)." if rating else ""
                    types_raw = r.get("types") or []
                    friendly_types = [t.replace("_", " ") for t in types_raw if t not in ("point_of_interest", "establishment")]
                    desc = ", ".join(friendly_types[:3]).capitalize() if friendly_types else "Popular spot in Miami."
                    desc += rating_str
                    open_now = r.get("opening_hours", {}).get("open_now")
                    hours_str = "Open now" if open_now else ("Closed now" if open_now is False else "See Google Maps for hours")
                    examples.append(MiamiExample(
                        name=name,
                        neighborhood=vicinity,
                        description=desc,
                        hours=hours_str,
                    ))
                PLACES_CACHE[key] = {"ts": now, "examples": examples}
                return examples
        except Exception:
            pass

    # 3) Fallback: ask LLM to suggest real places
    llm_examples = _llm_suggest_places(search_query)
    if llm_examples:
        PLACES_CACHE[key] = {"ts": now, "examples": llm_examples}
        return llm_examples

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


def _rejects_suggested_options(msg: str) -> bool:
    """True when the user is rejecting the assistant's suggested options in general."""
    t = (msg or "").strip().lower()
    if not t:
        return False

    explicit_patterns = [
        "i don't like these",
        "i dont like these",
        "i don't like those",
        "i dont like those",
        "don't like these",
        "dont like these",
        "don't like those",
        "dont like those",
        "not these",
        "not those",
        "none of these",
        "none of those",
        "not these options",
        "not those options",
        "different options",
        "other options",
        "something else",
    ]
    if any(pattern in t for pattern in explicit_patterns):
        return True

    has_negation = any(token in t for token in ["don't", "dont", "do not", "not", "no", "none"])
    refers_to_suggestions = any(token in t for token in ["these", "those", "options", "suggestions", "recommendations"])
    return has_negation and refers_to_suggestions


def _is_soft_positive_confirmation(msg: str) -> bool:
    """True when the user is positively reacting to the shown examples in free text."""
    t = (msg or "").strip().lower()
    if not t:
        return False
    patterns = [
        "i like these",
        "i like those",
        "i like this",
        "i like that",
        "i like these places",
        "i like those places",
        "i like to check out these places",
        "i like to checkout these places",
        "i want to check out these places",
        "i want to checkout these places",
        "these look good",
        "these seem good",
        "this looks good",
        "this seems good",
        "these are good",
        "this is good",
        "i would check these out",
        "i'd check these out",
        "i want to go to these places",
        "i want to visit these places",
    ]
    return any(pattern in t for pattern in patterns)


def _is_ambiguous_interest_reference(msg: str) -> bool:
    """True when the user refers to vague prior suggestions instead of naming one concrete interest."""
    t = (msg or "").strip().lower()
    if not t:
        return False
    patterns = [
        "i like these",
        "i like those",
        "i like these as well",
        "i like those as well",
        "i want to checkout these",
        "i want to check out these",
        "i like to checkout these",
        "i like to check out these",
        "all these",
        "these as well",
        "those as well",
    ]
    return any(pattern in t for pattern in patterns)


def extract_interest_fallback(msg: str, existing: List[str]) -> Optional[str]:
    candidates = extract_interest_fallbacks(msg, existing)
    if not candidates:
        return None
    return candidates[0]["label"]


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

GREETING = (
    "Hey! I'm your HelloCity guide. Just tell me what you're into when you're out in the city. "
    "Like coffee shops, movies, live music, outdoor stuff, rooftop bars, whatever."
)


def _remaining_options(existing: List[str], messages: Optional[List[ChatMessage]] = None, limit: int = 5) -> str:
    source_options = OPENING_INTEREST_SUGGESTIONS if not existing and len(messages or []) <= 2 else EXAMPLE_INTEREST_SUGGESTIONS
    existing_lower = {item.lower() for item in existing}
    recent_assistant_text = " ".join(
        msg.content.lower()
        for msg in (messages or [])[-6:]
        if msg.role == "assistant"
    )
    recent_user_messages = [
        msg.content
        for msg in (messages or [])[-6:]
        if msg.role == "user"
    ]
    recently_suggested = {
        option.lower()
        for option in source_options
        if option.lower() in recent_assistant_text
    }
    recently_rejected = {
        option.lower()
        for option in source_options
        if any(_user_rejects_interest(user_msg, option) for user_msg in recent_user_messages)
    }
    remaining = [
        option
        for option in source_options
        if option.lower() not in existing_lower
        and option.lower() not in recently_suggested
        and option.lower() not in recently_rejected
    ]
    if len(remaining) < limit:
        fallback_remaining = [
            option
            for option in source_options
            if option.lower() not in existing_lower and option not in remaining
        ]
        remaining.extend(fallback_remaining)
    if not remaining:
        remaining = source_options[:]
    offset_seed = len(existing) + len(messages or [])
    offset = offset_seed % len(remaining)
    rotated = remaining[offset:] + remaining[:offset]
    return ", ".join(rotated[:limit])


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


def _format_recent_chat(messages: Optional[List[ChatMessage]], limit: int = 6) -> str:
    if not messages:
        return ""
    return "\n".join(
        f"{msg.role}: {msg.content}"
        for msg in messages[-limit:]
    )


def _has_introduced_assistant(messages: Optional[List[ChatMessage]]) -> bool:
    if not messages:
        return False
    return any(
        msg.role == "assistant" and "hellocity onboarding assistant" in msg.content.lower()
        for msg in messages
    )


def _clean_assistant_text(text: str) -> str:
    cleaned = (text or "").replace("—", ", ").replace("–", ", ")
    cleaned = re.sub(r"\s-\s", ", ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _llm_one_line(prompt: str, fallback: str, messages: Optional[List[ChatMessage]] = None, max_sentences: int = 2) -> str:
    """Ask the LLM for a short, casual reply with optional recent chat context."""
    api_key = _get_openai_api_key()
    if not api_key or OpenAI is None:
        return fallback
    try:
        client = OpenAI(api_key=api_key.strip())
        context = _format_recent_chat(messages)
        system_parts = [
            "You are HelloCity's friendly assistant.",
            f"Reply with at most {max_sentences} short casual sentence(s).",
            "Sound like you're texting a friend.",
            "No quotes, no preamble, no lists, no hyphens, no dashes.",
            "Avoid repeating the exact same wording you used recently.",
        ]
        if context:
            system_parts.append(f"Recent chat:\n{context}")
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": " ".join(system_parts)},
                {"role": "user", "content": prompt},
            ],
            temperature=0.95,
            max_tokens=90,
        )
        raw = _clean_assistant_text((resp.choices[0].message.content or "").strip().strip('"'))
        return raw if raw else fallback
    except Exception:
        return fallback


def _examples_intro(interest: str, messages: Optional[List[ChatMessage]] = None) -> str:
    fallback = f"Here are some spots in Miami for {interest}."
    return _llm_one_line(
        f"The user said they like '{interest}'. Reply in one short casual sentence: acknowledge and say you're showing Miami spots. "
        "Use a comma or period only. No hyphens or dashes. Do NOT say 'you're going to love' or 'I found' or 'awesome'. "
        "Examples: 'Nice, here are some spots for that.' 'Got it. Here are some Miami spots for " + interest + ".'",
        fallback,
        messages=messages,
    )


def _progress_message(existing: List[str], messages: Optional[List[ChatMessage]] = None, confirmed: Optional[bool] = None) -> str:
    n = len(existing)
    needed = 3 - n
    if needed <= 0:
        return _llm_one_line(
            "You already have all 3 interests. Wrap up naturally and say their Miami profile is ready.",
            "All done! Here's your Miami profile.",
            messages=messages,
        )
    opts = _remaining_options(existing, messages)
    if n == 0:
        return GREETING
    if confirmed is True:
        fallback = f"Nice, that works. {needed} more and we're set. What else are you into?"
        prompt = (
            f"The user just confirmed the last set of examples matched well. We've collected {n} interests so far and need {needed} more. "
            f"Reply naturally in 1 or 2 short sentences and ask for another interest. You can lightly suggest from: {opts}."
        )
    elif confirmed is False:
        fallback = f"All good, I can still use that as a rough fit. {needed} more to go. What else are you into?"
        prompt = (
            f"The user said the examples were not quite right, but the app still keeps that interest and needs {needed} more total. "
            f"Reply naturally in 1 or 2 short sentences, acknowledge the mismatch without sounding stiff, and ask for another interest. "
            f"You can lightly suggest from: {opts}."
        )
    else:
        fallback = f"Got it. {needed} more and we're set. What else? Maybe {opts}?"
        prompt = (
            f"We've collected {n} interest(s) so far. We need {needed} more. "
            f"Tell the user how many more you need and casually suggest these if helpful: {opts}."
        )
    return _llm_one_line(
        prompt,
        fallback,
        messages=messages,
        max_sentences=2,
    )


def _small_talk_message(user_text: str, existing: List[str], messages: Optional[List[ChatMessage]] = None) -> str:
    opts = _remaining_options(existing, messages)
    kind = _small_talk_kind(user_text)
    intro_needed = not _has_introduced_assistant(messages)
    intro_prefix = "First say that you are the HelloCity onboarding assistant. " if intro_needed else ""
    if kind == "how_are_you":
        fallback = (
            "I am the HelloCity onboarding assistant, doing well, thanks. Tell me one thing you're into around Miami and I'll pull some spots for it."
            if intro_needed else
            "Doing well, thanks. Tell me one thing you're into around Miami and I'll pull some spots for it."
        )
        prompt = (
            f"The user said: '{user_text}'. {intro_prefix}Answer the greeting directly in a warm casual way. "
            "Then ask for one interest around Miami. Do not pivot with phrases like 'speaking of which'."
        )
    elif kind == "model":
        fallback = (
            "I am the HelloCity onboarding assistant, powered by OpenAI on the backend. Tell me one thing you're into around Miami and I'll pull some spots for it."
            if intro_needed else
            "I'm powered by OpenAI on the backend. Tell me one thing you're into around Miami and I'll pull some spots for it."
        )
        prompt = (
            f"The user asked: '{user_text}'. {intro_prefix}Answer directly that you're powered by OpenAI. "
            "Then ask for one Miami interest. Keep it short and natural. Do not dodge the question."
        )
    elif kind == "help":
        fallback = (
            "I am the HelloCity onboarding assistant. I can help find Miami spots based on what you're into. Tell me one activity, vibe, or place type you like."
            if intro_needed else
            "I can help find Miami spots based on what you're into. Tell me one activity, vibe, or place type you like."
        )
        prompt = (
            f"The user asked: '{user_text}'. {intro_prefix}Answer directly what you can help with. "
            "Say you can find Miami spots based on their interests, then ask for one thing they like."
        )
    elif kind == "identity":
        fallback = "I am the HelloCity onboarding assistant. Tell me one thing you're into and I'll start there."
        prompt = (
            f"The user asked: '{user_text}'. First say that you are the HelloCity onboarding assistant. Then ask for one Miami interest."
        )
    elif kind == "greeting":
        fallback = (
            f"I am the HelloCity onboarding assistant. Tell me one thing you're into around Miami, maybe {opts}."
            if intro_needed else
            f"Hey. Tell me one thing you're into around Miami, maybe {opts}."
        )
        prompt = (
            f"The user said: '{user_text}'. {intro_prefix}Then reply with a natural greeting and ask what they're into around Miami. "
            f"You can lightly suggest from: {opts}. Avoid defaulting to Mexican food unless the user mentioned a specific cuisine."
        )
    elif kind == "introduction":
        fallback = (
            "I am the HelloCity onboarding assistant. Nice to meet you. Tell me one thing you're into around Miami and I'll take it from there."
            if intro_needed else
            "Nice to meet you. Tell me one thing you're into around Miami and I'll take it from there."
        )
        prompt = (
            f"The user said: '{user_text}'. They are introducing themselves. {intro_prefix}Then greet them back naturally and say nice to meet you. "
            "After that, ask for one Miami interest. Do not invent any activity category from their name."
        )
    else:
        fallback = (
            f"I am the HelloCity onboarding assistant. I can help narrow down Miami spots around what you're into. Tell me one thing you like, maybe {opts}."
            if intro_needed else
            f"I can help narrow down Miami spots around what you're into. Tell me one thing you like, maybe {opts}."
        )
        prompt = (
            f"The user said: '{user_text}'. {intro_prefix}This is small talk or a meta question, not an interest submission. "
            f"Reply naturally in 1 or 2 short sentences, answer directly when possible, then gently steer back to city interests. Suggest a couple of these if helpful: {opts}. "
            "Do not use filler pivots like 'speaking of which'. Avoid defaulting to Mexican food unless the user mentioned a specific cuisine."
        )

    return _llm_one_line(
        prompt,
        fallback,
        messages=messages,
        max_sentences=2,
    )


def _out_of_scope_message(user_text: str, existing: List[str], messages: Optional[List[ChatMessage]] = None) -> str:
    opts = _remaining_options(existing, messages)
    intro_needed = not _has_introduced_assistant(messages)
    intro_prefix = "First say that you are the HelloCity onboarding assistant. " if intro_needed else ""
    fallback = (
        f"I am the HelloCity onboarding assistant. I can't help with live weather or general info here, but I can help find Miami spots. Tell me one thing you're into, maybe {opts}."
        if intro_needed else
        f"I can't help with live weather or general info here, but I can help find Miami spots. Tell me one thing you're into, maybe {opts}."
    )
    return _llm_one_line(
        f"The user asked: '{user_text}'. {intro_prefix}This is outside the app's scope, like weather or general info. "
        f"Answer briefly that you cannot help with that here, then steer back to Miami interests. Suggest from: {opts}. "
        "Do not pretend to know the answer. Do not mention an existing interest unless the user asked about it.",
        fallback,
        messages=messages,
        max_sentences=2,
    )


def _social_redirect_message(user_text: str, existing: List[str], messages: Optional[List[ChatMessage]] = None) -> str:
    opts = _remaining_options(existing, messages)
    fallback = f"Got you. I'm here to help with Miami interests. Tell me one thing you're into, maybe {opts}."
    return _llm_one_line(
        f"The user said: '{user_text}'. This is social chatter or a sign-off, not an activity interest. "
        f"Acknowledge it briefly, then gently steer back to Miami interests. Suggest from: {opts}.",
        fallback,
        messages=messages,
        max_sentences=2,
    )


def _hostile_redirect_message(user_text: str, existing: List[str], messages: Optional[List[ChatMessage]] = None) -> str:
    opts = _remaining_options(existing, messages)
    fallback = f"I hear you. I'm here to help with Miami interests, not force anything. Tell me one thing you actually want, maybe {opts}."
    return _llm_one_line(
        f"The user said: '{user_text}'. This is frustrated or hostile, not an activity interest. "
        f"Respond calmly, do not be defensive, and steer back to Miami interests without repeating rejected categories. Suggest from: {opts}.",
        fallback,
        messages=messages,
        max_sentences=2,
    )


def _unknown_message(existing: List[str], user_text: str = "", messages: Optional[List[ChatMessage]] = None) -> str:
    n = len(existing)
    needed = 3 - n
    opts = _remaining_options(existing, messages)
    if n == 0:
        fallback = f"Hmm, not sure I got that. Try something like: {opts}?"
    else:
        fallback = f"Didn't catch that one. So far I have: {', '.join(existing)}. Need {needed} more. Maybe {opts}?"
    return _llm_one_line(
        f"The user said: '{user_text}'. You couldn't match it cleanly to an activity interest. "
        f"Interests so far: {existing}. Need {needed} more. Available options: {opts}. "
        "Let them know gently and suggest options. Keep it natural and specific to what they said. No lists.",
        fallback,
        messages=messages,
        max_sentences=2,
    )


def _one_interest_at_a_time_message(existing: List[str], messages: Optional[List[ChatMessage]] = None) -> str:
    opts = _remaining_options(existing, messages)
    fallback = f"Tell me one specific interest at a time, like {opts}. Then I'll show 3 Miami spots for it."
    return _llm_one_line(
        f"We are collecting interests one by one. The user referred vaguely to prior suggestions instead of naming one clear interest. "
        f"Ask for one specific interest at a time, then say you'll show 3 Miami spots for it. Suggest from: {opts}.",
        fallback,
        messages=messages,
        max_sentences=2,
    )


def _duplicate_interest_message(existing: List[str], duplicate_label: str, messages: Optional[List[ChatMessage]] = None) -> str:
    """When the user named an interest we already have; acknowledge and suggest something different."""
    opts = _remaining_options(existing, messages)
    fallback = f"I already have {duplicate_label}. Give me a different vibe or activity, maybe {opts}."
    return _llm_one_line(
        f"The user said something that maps to '{duplicate_label}', which is already in their list. "
        f"Tell them you already have that one and ask for a different interest. Suggest: {opts}. Keep it casual and not repetitive.",
        fallback,
        messages=messages,
        max_sentences=2,
    )


def _no_results_message(query: str, existing: List[str], messages: Optional[List[ChatMessage]] = None) -> str:
    """
    Message to use when we understand the interest / query but can't find real
    Miami places for it (e.g. water parks that don't exist, highly niche asks).
    """
    base = query.strip() or "that"
    fallback = f"I couldn't find any good Miami spots for {base}. Want to try a different kind of activity?"
    return _llm_one_line(
        f"You tried to find places for '{base}' in Miami, but there don't seem to be any good real matches. "
        "Tell the user clearly that there aren't good options in Miami for that and invite them to try a different activity. "
        "Keep it short and natural.",
        fallback,
        messages=messages,
        max_sentences=2,
    )


def _specific_rejection_message(rejected_label: str, existing: List[str], messages: Optional[List[ChatMessage]] = None) -> str:
    fallback = f"Got it, we can skip {rejected_label}. Tell me what kind of place or activity you do want and I'll pivot."
    return _llm_one_line(
        f"The user rejected '{rejected_label}'. Interests so far: {existing}. "
        "Acknowledge that naturally, do not repeat the rejected category, and ask what they would actually like instead. "
        "Keep it short and warm.",
        fallback,
        messages=messages,
        max_sentences=2,
    )


def _suggestion_rejection_message(existing: List[str], messages: Optional[List[ChatMessage]] = None) -> str:
    fallback = "No problem, we can skip those. Just tell me what you actually enjoy doing in Miami and I'll work from that."
    return _llm_one_line(
        f"The user rejected your suggested options. Interests so far: {existing}. "
        "Acknowledge that briefly, do not repeat the same suggestions, and invite them to share what they actually like doing in Miami. "
        "Keep it natural and short.",
        fallback,
        messages=messages,
        max_sentences=2,
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
        pass

    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        match = re.search(pattern, text)
        if not match:
            continue
        snippet = match.group(0).strip()
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    return {}


def _parse_interest_candidates(raw_candidates: Any) -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []
    if isinstance(raw_candidates, list):
        for c in raw_candidates:
            if isinstance(c, str):
                normalized = _normalize_candidate(c, c)
                if normalized:
                    candidates.append(normalized)
            elif isinstance(c, dict):
                label = c.get("label") or c.get("interest") or ""
                search_query = c.get("search_query") or label
                normalized = _normalize_candidate(label, search_query)
                if normalized:
                    candidates.append(normalized)
    return candidates


def _llm_extract_candidates(
    client: Any,
    user_text: str,
    existing: List[str],
    infer_typos: bool = False,
) -> List[Dict[str, str]]:
    typo_rules = (
        "5. Infer simple misspellings, merged words, and spacing errors when the intent is obvious. "
        "Examples: 'waterrides' -> water rides or water parks, 'pedal' -> padel, 'coffeeshops' -> coffee shops, 'moviez' -> movies.\n"
        if infer_typos else
        ""
    )
    prompt = (
        "Extract activity interests from the user's message for a Miami onboarding app.\n"
        f"Existing interests: {existing}\n"
        f"User message: {user_text}\n\n"
        "Rules:\n"
        "1. Return only JSON.\n"
        "2. If the user is naming, implying, asking where to do, asking how to do, or asking for spots for an activity, extract it as an interest.\n"
        "3. Treat questions like 'how do I play padel', 'where can I play badminton', 'where can I dance with my wife', or 'suggest football spots' as interest submissions.\n"
        "4. Use broad labels when helpful, but do not force every interest into a fixed category. If a specific activity or cuisine is clearer, keep it.\n"
        "5. Preserve cuisine specificity for food interests. For example, 'indian food' should stay 'indian food' with a search query like 'indian restaurants'.\n"
        f"{typo_rules}"
        "6. Return up to 3 candidates with label and search_query.\n"
        "7. If there is no activity interest, return an empty list.\n\n"
        "Return JSON only in this format:\n"
        "{\"interest_candidates\": [{\"label\": \"...\", \"search_query\": \"...\"}]}"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You extract structured activity interests. Return JSON only. Be good at obvious typos and merged words when the intent is clear."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=180,
        )
        raw = resp.choices[0].message.content or "{}"
        data = _parse_llm_json(raw)
        candidates = _parse_interest_candidates(data.get("interest_candidates"))
        return candidates
    except Exception:
        return []


def _llm_refine_search_candidate(
    client: Any,
    user_text: str,
    existing: List[str],
) -> List[Dict[str, str]]:
    prompt = (
        "Turn the user's message into the best Miami place search candidate you can.\n"
        f"Existing interests: {existing}\n"
        f"User message: {user_text}\n\n"
        "Rules:\n"
        "1. Return JSON only.\n"
        "2. If the user is clearly asking about an activity, event type, hobby, or vibe, return one candidate.\n"
        "3. It is fine to go beyond common categories like nightlife or sports.\n"
        "4. Keep the label specific when useful, for example poetry readings, pottery classes, karaoke nights, board game cafes, salsa dancing, indian food, vegan food, sushi.\n"
        "5. Infer simple misspellings and merged words when the intent is obvious, for example waterrides, pedal, coffeeshops, moviez.\n"
        "6. The search_query should be optimized for real Miami place search results.\n"
        "7. If there is no usable activity, return an empty list.\n\n"
        "Return JSON only in this format:\n"
        "{\"interest_candidates\": [{\"label\": \"...\", \"search_query\": \"... in Miami\"}]}"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You refine user interests into searchable Miami activity queries. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=180,
        )
        raw = resp.choices[0].message.content or "{}"
        data = _parse_llm_json(raw)
        candidates = _parse_interest_candidates(data.get("interest_candidates"))
        return candidates
    except Exception:
        return []


def _llm_classify_non_interest_query(client: Any, user_text: str) -> str:
    prompt = (
        "Classify the user's message for a city onboarding assistant.\n"
        f"User message: {user_text}\n\n"
        "Return JSON only in this format:\n"
        "{\"intent\": \"greeting|how_are_you|model|help|identity|out_of_scope|interest|generic\"}\n\n"
        "Rules:\n"
        "1. Use out_of_scope for weather, time, date, news, finance, sports scores, and other general info requests.\n"
        "2. Use model for questions about the AI, model, version, or what powers the assistant.\n"
        "3. Use help for questions about what the assistant can do.\n"
        "4. Use identity for who the assistant is.\n"
        "5. Use interest only if the user is actually naming or asking about an activity they want.\n"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You classify onboarding messages. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=60,
        )
        raw = resp.choices[0].message.content or "{}"
        data = _parse_llm_json(raw)
        intent = str(data.get("intent") or "").strip().lower()
        return intent
    except Exception:
        return ""


def call_llm(messages: List[ChatMessage], existing: List[str]) -> Dict[str, Any]:
    user_text = ""
    for msg in reversed(messages):
        if msg.role == "user":
            user_text = msg.content
            break

    if _is_out_of_scope_query(user_text):
        return {"assistant_message": _out_of_scope_message(user_text, existing, messages), "interest_candidates": []}
    if _is_social_message(user_text):
        return {"assistant_message": _social_redirect_message(user_text, existing, messages), "interest_candidates": []}
    if _is_hostile_message(user_text):
        return {"assistant_message": _hostile_redirect_message(user_text, existing, messages), "interest_candidates": []}

    api_key = _get_openai_api_key()
    if not api_key or OpenAI is None:
        # Mock mode: use semantic fallback and conversational helpers.
        small_talk_kind = _small_talk_kind(user_text) if _is_small_talk(user_text) else ""
        if small_talk_kind:
            return {"assistant_message": _small_talk_message(user_text, existing, messages), "interest_candidates": []}
        fallback_candidates = extract_interest_fallbacks(user_text, existing)
        if fallback_candidates:
            first = fallback_candidates[0]
            return {
                "assistant_message": _examples_intro(first["label"]),
                "interest_candidates": fallback_candidates,
            }
        if not existing:
            return {"assistant_message": GREETING, "interest_candidates": []}
        return {"assistant_message": _unknown_message(existing, user_text), "interest_candidates": []}

    client = OpenAI(api_key=api_key.strip())
    n = len(existing)
    needed = 3 - n
    state_info = f"Interests so far: {existing}. Need {needed} more." if existing else "No interests yet. Need 3."
    example_cats = ", ".join(EXAMPLE_INTEREST_SUGGESTIONS)
    recent_history = "\n".join(
        f"{m.role}: {m.content}"
        for m in messages[-6:]
    )

    system_prompt = (
        "You are HelloCity's onboarding assistant helping users find what they love to do in Miami. "
        "Sound casual and natural, like you're texting a friend. No corporate or robotic phrases. Use contractions, short sentences, and a warm tone.\n\n"
        f"STATE: {state_info}\n"
        f"EXAMPLE INTERESTS (you are NOT limited to these): {example_cats}\n\n"
        f"RECENT CHAT:\n{recent_history}\n\n"
        "GOALS:\n"
        "- Have a friendly, human-feeling conversation.\n"
        "- Help the user discover 3 interests about what they enjoy doing in a city like Miami.\n"
        "- For each interest, propose a label AND a search_query that the backend can use with a places API.\n"
        "- If the user mentions more than one interest in a single message, extract up to 3 candidates.\n\n"
        "RULES:\n"
        "1. When the user says they do NOT want something (e.g. 'i dont want brunch', 'no brunch', 'not into art'), "
        "set interest_candidates to [] and reply acknowledging that and asking what they'd like instead. Do NOT suggest that category.\n"
        "2. When the user greets you (hi/hello/hey) or makes small talk (e.g. 'how are you', 'what model are you'), reply naturally in 1–2 short sentences, then gently steer back to what they like to do (mention 2–3 options they haven't picked yet).\n"
        "3. When the user mentions an activity they LIKE (even in a long sentence), map it to a short, natural activity label. "
        "Prefer broad labels when they improve search quality, but do not force every interest into a fixed set. Specific interests are allowed when they are searchable in Miami.\n"
        "Examples: 'dancing with my wife' -> nightlife, 'I love taking my son to arcades' -> arcades and gaming, 'walks with my dog at parks' -> outdoor activities, 'padel and tennis' -> racket sports, 'movies' or 'cinema' -> movies, 'indian food' -> indian food with search_query 'indian restaurants'.\n"
        "Questions about doing an activity still count as interest submissions when clear, for example 'how do I play padel', 'where can I play badminton', or 'where can I dance with my wife'.\n"
        "4. For each detected interest, add an object to interest_candidates: {\"label\": \"category_label\", \"search_query\": \"query for places API\"}. Example: {\"label\": \"movies\", \"search_query\": \"movie theaters\"} or {\"label\": \"racket sports\", \"search_query\": \"padel and tennis courts\"} or {\"label\": \"poetry readings\", \"search_query\": \"poetry readings and spoken word venues\"}.\n"
        "   - assistant_message should be ONE short casual sentence (e.g. 'Nice, here are some spots for that.' or 'Got it. I'll find some Miami spots for movies.').\n"
        "   - No hyphens or dashes. No 'you're going to love' or 'I found' or 'awesome'. Do NOT ask what they like again in the same message.\n"
        "5. When you CANNOT map to any category, set interest_candidates to [] and assistant_message should say you didn't quite get it in a friendly way and suggest a few options. Vary your wording; don't repeat the exact same sentence.\n"
        "6. NEVER repeat the exact same message across turns. Vary phrasing even when the situation is similar.\n"
        "7. Do not default to mexican food, brunch, art galleries, or farmers markets unless they fit what the user actually said. Vary opening suggestions across coffee shops, movies, outdoor activities, shopping, live music, rooftop bars, and beach activities.\n\n"
        "Return ONLY valid JSON: {\"assistant_message\": \"...\", \"interest_candidates\": [ {\"label\": \"...\", \"search_query\": \"...\"}, ... ]}. No markdown."
    )

    api_messages = [{"role": "system", "content": system_prompt}]
    api_messages += [{"role": m.role, "content": m.content} for m in messages]

    try:
        resp = client.chat.completions.create(model="gpt-4o-mini", messages=api_messages, temperature=0.8)
        raw = resp.choices[0].message.content or "{}"
    except Exception:
        fallback_candidates = extract_interest_fallbacks(user_text, existing)
        if fallback_candidates:
            return {
                "assistant_message": _examples_intro(fallback_candidates[0]["label"]),
                "interest_candidates": fallback_candidates,
            }
        if _is_small_talk(user_text):
            return {"assistant_message": _small_talk_message(user_text, existing), "interest_candidates": []}
        return {"assistant_message": _unknown_message(existing, user_text), "interest_candidates": []}

    data = _parse_llm_json(raw)
    raw_candidates = data.get("interest_candidates")
    candidates = _parse_interest_candidates(raw_candidates)
    used_extraction_recovery = False
    if not candidates and not _is_small_talk(user_text):
        candidates = _llm_extract_candidates(client, user_text, existing)
        used_extraction_recovery = bool(candidates)
    if not candidates and not _is_small_talk(user_text) and _should_try_typo_recovery(user_text):
        candidates = _llm_extract_candidates(client, user_text, existing, infer_typos=True)
        used_extraction_recovery = bool(candidates)
    if not candidates and not _is_small_talk(user_text):
        candidates = _llm_refine_search_candidate(client, user_text, existing)
        used_extraction_recovery = bool(candidates)
    inferred_non_interest_intent = ""
    if not candidates and _looks_like_question(user_text) and not _is_out_of_scope_query(user_text) and not _is_small_talk(user_text):
        inferred_non_interest_intent = _llm_classify_non_interest_query(client, user_text)
    msg = data.get("assistant_message") or (
        _small_talk_message(user_text, existing, messages) if (_is_small_talk(user_text) or inferred_non_interest_intent in {"greeting", "how_are_you", "model", "help", "identity", "generic"})
        else _out_of_scope_message(user_text, existing, messages) if (_is_out_of_scope_query(user_text) or inferred_non_interest_intent == "out_of_scope")
        else _unknown_message(existing, user_text, messages)
    )
    if used_extraction_recovery and candidates:
        msg = _examples_intro(candidates[0]["label"], messages)
    msg = _clean_assistant_text(msg)

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
        state.last_examples = []
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

    if state.awaiting_confirmation and _is_soft_positive_confirmation(req.message):
        msg = "If these feel right, tap Yes. If not, tap No and I'll adjust."
        state.messages.append(ChatMessage(role="assistant", content=msg))
        return ChatResponse(
            session_id=session_id, assistant_message=msg,
            interests=state.interests, interests_count=len(state.interests),
            examples=state.last_examples, is_complete=False, profile=None,
        )

    if not state.awaiting_confirmation and _is_ambiguous_interest_reference(req.message):
        msg = _one_interest_at_a_time_message(state.interests, state.messages)
        state.messages.append(ChatMessage(role="assistant", content=msg))
        return ChatResponse(
            session_id=session_id, assistant_message=msg,
            interests=state.interests, interests_count=len(state.interests),
            examples=[], is_complete=len(state.interests) >= 3,
            profile={"interests": state.interests[:3]} if len(state.interests) >= 3 else None,
        )

    # Call LLM
    llm_result = call_llm(state.messages, state.interests)
    assistant_message = llm_result["assistant_message"]
    raw_candidates = llm_result.get("interest_candidates") or []

    # Normalize candidates into dicts with label + search_query (+ source for bookkeeping)
    candidates: List[Dict[str, str]] = []
    for c in raw_candidates:
        if isinstance(c, str):
            normalized = _normalize_candidate(c, c)
            if normalized:
                normalized["source"] = "llm"
                candidates.append(normalized)
        elif isinstance(c, dict):
            label = c.get("label") or c.get("interest") or ""
            search_query = c.get("search_query") or label
            normalized = _normalize_candidate(label, search_query)
            if normalized:
                normalized["source"] = "llm"
                candidates.append(normalized)

    # Backend fallback if LLM returned nothing
    if not candidates:
        fallback_candidates = extract_interest_fallbacks(req.message, state.interests)
        if fallback_candidates:
            candidates = [{**cand, "source": "fallback"} for cand in fallback_candidates]
            assistant_message = _examples_intro(fallback_candidates[0]["label"])

    # Find the first new interest (skip if user explicitly rejected it, e.g. "i dont want brunch")
    new_interest: Optional[str] = None
    search_query: Optional[str] = None
    handled_rejection = False
    duplicate_label: Optional[str] = None  # first candidate that was already in list
    chosen_source: Optional[str] = None
    for cand in candidates:
        raw_label = (cand.get("label") or "").strip()
        if not raw_label:
            continue
        label = raw_label
        if not label:
            continue
        if label.lower() in [i.lower() for i in state.interests]:
            if duplicate_label is None:
                duplicate_label = label
            continue
        if _user_rejects_interest(req.message, label):
            new_interest = None
            handled_rejection = True
            assistant_message = _specific_rejection_message(label, state.interests, state.messages)
        else:
            new_interest = label
            search_query = cand.get("search_query") or label
            chosen_source = cand.get("source") or "unknown"
        break

    # All candidates were duplicates: acknowledge and ask for something different
    if new_interest is None and not handled_rejection and duplicate_label is not None:
        assistant_message = _duplicate_interest_message(state.interests, duplicate_label)

    # Show examples and count the interest
    examples: List[MiamiExample] = []
    if new_interest:
        # Use Places API / LLM suggestions to find real places
        examples = find_miami_places(search_query or new_interest)
        if examples:
            state.interests.append(new_interest)
            state.awaiting_confirmation = True
            state.last_examples = examples
        else:
            # We understood the interest, but couldn't find real places.
            # Don't show Yes/No; instead, be honest that there aren't good matches.
            state.awaiting_confirmation = False
            state.last_examples = []
            assistant_message = _no_results_message(search_query or new_interest, state.interests)
    elif not candidates and not handled_rejection and duplicate_label is None:
        # No interest found — check if they were rejecting a category (e.g. "i dont want rooftop bar")
        if _rejects_suggested_options(req.message):
            assistant_message = _suggestion_rejection_message(state.interests, state.messages)
        else:
            rejected_category = None
            for cat in SUPPORTED_SEARCH_CATEGORIES:
                if _user_rejects_interest(req.message, cat):
                    rejected_category = cat
                    break
            if rejected_category:
                assistant_message = _specific_rejection_message(rejected_category, state.interests, state.messages)
            else:
                assistant_message = _small_talk_message(req.message, state.interests, state.messages) if _is_small_talk(req.message) else (
                    _out_of_scope_message(req.message, state.interests, state.messages) if _is_out_of_scope_query(req.message) else (
                        _unknown_message(state.interests, req.message, state.messages) if state.interests or req.message.strip().lower() not in ("hi", "hello", "hey", "hi!", "hi there", "hello there") else GREETING
                    )
                )

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
