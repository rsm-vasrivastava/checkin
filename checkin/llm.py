"""All Claude calls: next_turn() for the live conversation, summarize() and detect_trends() after it."""
import json
import re

import anthropic

from checkin import config

_client = None

LANGS = {"en": "English", "es": "Spanish", "hi": "Hindi"}

# Words that force urgency regardless of what the model says (safety net).
EMERGENCY_WORDS = ["fell", "fall", "chest pain", "can't breathe", "cannot breathe",
                   "trouble breathing", "hard to breathe", "short of breath", "caí", "me caí",
                   "dolor de pecho", "no puedo respirar", "गिर", "सीने में दर्द", "सांस"]

RULES = """You are CheckIn, a warm, patient voice assistant making a short daily phone call to an older adult who lives alone.
Rules:
- Speak simply, 1-2 short sentences per turn, no lists, no emojis. This is read aloud by a phone.
- Cover over the call: medication taken, meals, mood, any pain or falls. Ask ONE thing at a time.
- Ask any pending family questions naturally. Follow up on anything worrying from recent calls.
- NEVER give medical advice. If asked, say you'll let their family know.
- If they mention a fall, chest pain, or trouble breathing: set emergency=true, say you are alerting their family and suggest calling 911 if it is an emergency, then end the call.
- If they want to stop, or seem confused or distressed, end politely.
- Reply in {language}."""


def _client_():
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add it.")
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _ask(system: str, user: str, max_tokens: int = 600) -> str:
    resp = _client_().messages.create(
        model=config.MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}])
    return resp.content[0].text


def _parse_json(text: str):
    """Pull the first JSON object/array out of a model reply."""
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    if not m:
        raise ValueError(f"no JSON in model reply: {text[:200]}")
    return json.loads(m.group(0))


def _lang(code: str) -> str:
    return LANGS.get(code, code or "English")


def _history_brief(history: list[dict]) -> str:
    if not history:
        return "No previous calls."
    return "\n".join(f"- {c.get('date', '?')}: {c.get('summary_text', '')} (urgency {c.get('urgency')})"
                     for c in history[-3:])


def mentions_emergency(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in EMERGENCY_WORDS)


def next_turn(name: str, language: str, history: list[dict], questions: list[str],
              transcript: list[dict], turn: int) -> dict:
    """Next thing to say. transcript = [{"role": "ai"|"senior", "text": ...}].
    Returns {"say": str, "end": bool, "emergency": bool}. turn is 1-based (AI turn number)."""
    system = RULES.format(language=_lang(language))
    convo = "\n".join(f"{'You' if t['role'] == 'ai' else name}: {t['text']}" for t in transcript) or "(call just connected)"
    final = turn >= config.MAX_TURNS
    user = f"""Senior's name: {name}
Recent calls:
{_history_brief(history)}
Pending questions from family: {questions or 'none'}

Conversation so far:
{convo}

This is your turn {turn} of at most {config.MAX_TURNS}. {'This is your LAST turn: warmly say goodbye and set end=true.' if final else 'If this is turn 1, greet them by name.'}
Reply ONLY with JSON: {{"say": "...", "end": true|false, "emergency": true|false}}"""
    _client_()  # fail loudly on a missing key; the fallback below is for API/parse errors only
    try:
        out = _parse_json(_ask(system, user, 300))
        out = {"say": str(out["say"]), "end": bool(out.get("end")), "emergency": bool(out.get("emergency"))}
    except Exception:
        # Never leave a phone line silent: fall back to a safe line.
        out = {"say": "Thank you for talking with me. I'll let your family know. Take care.",
               "end": True, "emergency": False}
    last = next((t["text"] for t in reversed(transcript) if t["role"] == "senior"), "")
    if mentions_emergency(last):
        out["emergency"] = True
    if final or out["emergency"]:
        out["end"] = True
    return out


def summarize(name: str, language: str, transcript: list[dict], no_response: bool = False) -> dict:
    """End-of-call structured summary (always English, for the caregiver)."""
    if no_response or not any(t["role"] == "senior" for t in transcript):
        return {"meds_taken": None, "ate": None, "mood": "unknown", "pain_or_fall": None,
                "concerns": ["No response to the call"], "urgency": "watch",
                "summary_text": f"{name} did not answer or respond to today's call.", "trend_flags": []}
    convo = "\n".join(f"{'CheckIn' if t['role'] == 'ai' else name}: {t['text']}" for t in transcript)
    system = "You summarize check-in calls with older adults for their family. Be factual; do not invent anything."
    user = f"""Transcript (language: {_lang(language)}):
{convo}

Return ONLY JSON in English:
{{"meds_taken": true|false|null, "ate": true|false|null, "mood": "good|ok|low|unknown",
 "pain_or_fall": "short description or null", "concerns": ["..."],
 "urgency": "ok|watch|urgent", "summary_text": "1-2 sentences for family"}}
urgency=urgent for a fall, chest pain, or trouble breathing. "watch" for missed meds, skipped meals, low mood, new or ongoing pain, confusion. Otherwise "ok". null = not discussed."""
    try:
        s = _parse_json(_ask(system, user, 500))
    except Exception:
        s = {"meds_taken": None, "ate": None, "mood": "unknown", "pain_or_fall": None,
             "concerns": ["Could not summarize call"], "urgency": "watch",
             "summary_text": f"Call with {name} completed but the summary failed."}
    s.setdefault("concerns", [])
    s["trend_flags"] = []
    # Safety net: emergency words in the senior's own speech force urgent.
    if any(t["role"] == "senior" and mentions_emergency(t["text"]) for t in transcript):
        s["urgency"] = "urgent"
    if s.get("urgency") not in ("ok", "watch", "urgent"):
        s["urgency"] = "watch"
    return s


def detect_trends(today: dict, history: list[dict]) -> list[str]:
    """Compare today's summary with up to the last 7 calls; return short human-readable flags."""
    if not history:
        return []
    slim = lambda c: {k: c.get(k) for k in ("date", "meds_taken", "ate", "mood", "pain_or_fall", "urgency", "concerns")}
    system = "You spot worrying trends in daily check-in data for an older adult, for their family."
    user = f"""Past calls (oldest first):
{json.dumps([slim(c) for c in history], indent=1)}

Today:
{json.dumps(slim(today), indent=1)}

Return ONLY a JSON array of 0-3 short strings, e.g. ["pain reported 3 days in a row", "mood declining", "missed meds twice this week"].
Only flag patterns that really appear in the data (repeat of the same issue, worsening, or 2+ misses). Return [] if none."""
    try:
        flags = _parse_json(_ask(system, user, 300))
        return [str(f) for f in flags][:3]
    except Exception:
        return []
