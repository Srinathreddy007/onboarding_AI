# HelloCity Engineering Exercise — Requirements Checklist

Checked against the [HelloCity Engineering Exercise PDF](https://github.com/Srinathreddy007/onboarding_AI).

---

## What You Are Building

| Requirement | Status | Notes |
|-------------|--------|--------|
| Converse with user via chat | ✅ | Chat UI + `/chat` endpoint |
| Collect **exactly 3** interests | ✅ | Backend tracks `state.interests`, stops at 3 |
| After each interest, display **3 real Miami examples** | ✅ | `MIAMI_VENUES` per category, `get_examples()` |
| Store and manage state on **real server-side backend** | ✅ | FastAPI, `SESSIONS` in memory |
| Output **structured user profile** at the end | ✅ | `profile: { "interests": [...] }` server-side |

---

## User Experience

| Requirement | Status | Notes |
|-------------|--------|--------|
| Mobile web, fit to phone | ✅ | Responsive, max-width 480px, safe-area |
| HelloCity branding and colors | ✅ | Yellow/black, logo, tagline |
| Chat interface (assistant + user bubbles) | ✅ | `msg-row`, `msg-bubble` |
| Input field for user responses | ✅ | Input bar + send button |
| Example cards after each interest | ✅ | Cards with name, neighborhood, description, hours |
| Two buttons: “Yes, that’s what I meant” / “No” | ✅ | `confirm-btns` |
| Chat feels natural and coherent | ✅ | LLM + fallbacks, casual tone |

---

## Conversation Flow

| Requirement | Status | Notes |
|-------------|--------|--------|
| Assistant acts as onboarding assistant | ✅ | Greeting + interest prompts |
| Ask about interests when going out in the city | ✅ | Prompt + suggestions |
| **Extract interests from natural language** | ✅ | LLM + keyword/typo fallback |
| Continue until **at least 3 interests** collected | ✅ | Backend loop, `_progress_message` |
| Example categories (Mexican, live jazz, rooftop bars, art, farmers markets, beach) | ✅ | `VALID_CATEGORIES` + venues |
| Handle natural, messy language | ✅ | Typos, “don’t want” handling, unknown message |

---

## Interest Validation Step

| Requirement | Status | Notes |
|-------------|--------|--------|
| Display 3 **real** Miami examples per interest | ✅ | Real venues in `MIAMI_VENUES` |
| Real venue/event names, not mock placeholders | ✅ | Joe’s Stone Crab, Versailles, PAMM, etc. |
| Details: name, location, hours (images optional) | ✅ | name, neighborhood, description, hours |
| Show “Yes, that’s what I meant” and “No” | ✅ | Under cards |
| **Regardless of Yes/No**: interest counts and flow moves forward | ✅ | Backend counts on detection; Yes/No only affects next message |

---

## Backend (Mandatory)

| Requirement | Status | Notes |
|-------------|--------|--------|
| Real backend (Node or Python preferred) | ✅ | Python FastAPI |
| **Maintain session state** | ✅ | `SESSIONS[session_id]`, `SessionState` |
| **Track how many interests collected** | ✅ | `len(state.interests)`, `interests_count` in response |
| **Store interests in memory / temporary storage** | ✅ | `state.interests` in `SESSIONS` |
| **Prevent duplicate interests** | ✅ | Only add if `label not in state.interests`; reply with “You already have X” when duplicate |
| **Decide when onboarding is complete** | ✅ | `is_complete = len(state.interests) >= 3` |
| Return updated state after each interaction | ✅ | `ChatResponse`: interests, count, examples, profile |
| State **not** stored only in prompt memory | ✅ | Backend owns `state.interests`, progression |
| **Backend in control of progression logic** | ✅ | Backend adds interests, decides completion, when to show profile |

---

## LLM

| Requirement | Status | Notes |
|-------------|--------|--------|
| Real LLM for **conversational responses** | ✅ | OpenAI GPT-4o-mini (mock when no key) |
| Real LLM for **extracting structured interest candidates** | ✅ | JSON `interest_candidates` from LLM |
| Structure prompts / extract data / combine with backend logic | ✅ | System prompt + `choose_interest_label`, fallback, duplicate handling |

---

## Final Output

| Requirement | Status | Notes |
|-------------|--------|--------|
| After 3 interests: structured profile like `{ "interests": [ "Mexican food", "Live jazz", "Art galleries" ] }` | ✅ | `profile` in `ChatResponse` |
| Profile generated **server-side** | ✅ | Built in `/chat` from `state.interests` |
| May be displayed on screen | ✅ | Profile block with chips |

---

## Deliverables

| Deliverable | Status |
|-------------|--------|
| Live URL | ✅ e.g. `https://hellocity-ai.appspot.com` (or Vercel + Render) |
| GitHub repository | ✅ e.g. `https://github.com/Srinathreddy007/onboarding_AI` |
| Short summary (stack, LLM, reasoning vs backend, unfinished) | 📄 Use `SUMMARY.md` or README |

---

## Optional / Nice-to-have (from doc)

- **Duplicate interest**: User says “diners” then “breakfast diner” (same as food) → backend now replies e.g. “You already have food in your list. What else? Maybe …” so it’s not ignorant.
- **Unrecognized input** (e.g. “tea shop”): Backend uses `_unknown_message` so we acknowledge we didn’t match and suggest options.
