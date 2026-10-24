"""All model calls: next_turn() for the live conversation, summarize() and detect_trends() after it.

call_model() is the only function that talks to a model. LLM_PROVIDER picks Ollama (local, default)
or Anthropic. Small local models are unreliable at JSON, so every structured result is validated
and falls back to safe defaults.
"""
import json
import re

import requests

from checkin import config

LANGS = {"en": "English", "es": "Spanish", "hi": "Hindi"}

# Words that force urgency regardless of what the model says (safety net).
EMERGENCY_WORDS = ["fell", "fallen", "had a fall", "a fall", "fall down", "chest pain", "can't breathe", "cannot breathe",
                   "trouble breathing", "hard to breathe", "short of breath", "caí", "me caí",
                   "dolor de pecho", "no puedo respirar", "गिर", "सीने में दर्द", "सांस"]
# Phrases meaning the senior wants to end the call.
STOP_WORDS = ["goodbye", "bye", "stop", "have to go", "gotta go", "leave me alone", "adiós", "adios",
              "hasta luego", "अलविदा", "बाय"]

EMERGENCY_SAY = {
    "en": "I'm so sorry to hear that. I'm alerting your family right now. If this is an emergency, please call 911.",
    "es": "Lo siento mucho. Voy a avisar a su familia ahora mismo. Si es una emergencia, por favor llame al 911.",
    "hi": "मुझे बहुत दुख है। मैं अभी आपके परिवार को सूचित कर रही हूँ। अगर यह आपातकाल है तो कृपया 911 पर कॉल करें।",
}
FALLBACK_SAY = {
    "en": "Thank you for talking with me. I'll let your family know. Take care.",
    "es": "Gracias por hablar conmigo. Le avisaré a su familia. Cuídese.",
    "hi": "मुझसे बात करने के लिए धन्यवाद। मैं आपके परिवार को बता दूँगी। अपना ध्यान रखिए।",
}

RULES = """You are CheckIn, a warm, patient voice assistant making a short daily phone call to an older adult who lives alone.
Rules:
- Say ONLY one or two short, simple sentences. No lists, no emojis, no stage directions. It is read aloud by a phone.
- Over the call, find out: did they take their medication, did they eat, how is their mood, any pain or falls. Ask ONE thing at a time, and do not repeat a question they already answered.
- Ask any pending family questions naturally. Follow up on anything worrying from recent calls.
- NEVER give medical advice. If asked for any, say you'll let their family know.
- Reply in {language}. Output only the words to speak."""


def call_model(system: str, user: str, max_tokens: int = 300, json_mode: bool = False) -> str:
    """Single entry point to the model. json_mode asks the model to emit JSON (Ollama format=json)."""
    if config.LLM_PROVIDER == "anthropic":
        import anthropic  # optional dependency, only needed for this provider
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        resp = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY).messages.create(
            model=config.MODEL, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}])
        return resp.content[0].text
    payload = {"model": config.OLLAMA_MODEL, "stream": False,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "options": {"num_predict": max_tokens, "temperature": 0.3}}
    if json_mode:
        payload["format"] = "json"
    try:
        r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
    except requests.ConnectionError:
        raise RuntimeError(f"Can't reach Ollama at {config.OLLAMA_URL}. Is it running? (ollama serve; ollama pull {config.OLLAMA_MODEL})")
    return r.json()["message"]["content"]


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
    return "\n".join(f"- {c.get('date', '?')}: {c.get('summary_text', '')}" for c in history[-3:])


def _has(text: str, words: list[str]) -> bool:
    t = text.lower()
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", t) for w in words)


def mentions_emergency(text: str) -> bool:
    return _has(text, EMERGENCY_WORDS)


def _clean_reply(text: str) -> str:
    """Trim a model reply to at most two sentences, no quotes or role prefixes."""
    text = re.sub(r"^\s*(CheckIn|You|Assistant)\s*:\s*", "", text.strip()).strip('"“” \n')
    sentences = re.findall(r"[^.!?।]+[.!?।]?", text)
    return " ".join(s.strip() for s in sentences[:2]).strip()


def next_turn(name: str, language: str, history: list[dict], questions: list[str],
              transcript: list[dict], turn: int) -> dict:
    """Next thing to say. transcript = [{"role": "ai"|"senior", "text": ...}], turn is the 1-based AI turn.
    Returns {"say": str, "end": bool, "emergency": bool}. Ending and emergencies are decided in code,
    not by the model, so safety never depends on a small model following instructions."""
    last = next((t["text"] for t in reversed(transcript) if t["role"] == "senior"), "")
    if mentions_emergency(last):
        return {"say": EMERGENCY_SAY.get(language, EMERGENCY_SAY["en"]), "end": True, "emergency": True}
    final = turn >= config.MAX_TURNS or (bool(last) and _has(last, STOP_WORDS))

    convo = "\n".join(f"{'CheckIn' if t['role'] == 'ai' else name}: {t['text']}" for t in transcript) or "(call just connected)"
    if turn == 1:
        task = f"Greet {name} by name warmly and ask how they are feeling today."
    elif final:
        task = "Warmly say goodbye and tell them their family will hear how they are doing. Do not ask a question."
    else:
        task = "Reply briefly to what they just said, then ask the next thing you still need to know."
    user = f"""Senior's name: {name}
Recent calls:
{_history_brief(history)}
Pending questions from family: {questions or 'none'}

Conversation so far:
{convo}

Your task now: {task}"""
    _check_provider()
    try:
        say = _clean_reply(call_model(RULES.format(language=_lang(language)), user, 120))
    except RuntimeError:
        raise
    except Exception:
        say = ""
    if not say:  # never leave a phone line silent
        say, final = FALLBACK_SAY.get(language, FALLBACK_SAY["en"]), True
    return {"say": say, "end": final, "emergency": False}


def _check_provider() -> None:
    """Fail loudly on config problems (missing key / Ollama down) instead of using fallback text."""
    if config.LLM_PROVIDER == "anthropic" and not config.ANTHROPIC_API_KEY:
        raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")


def _tri(v):
    """Coerce a model value to True/False/None."""
    if isinstance(v, bool) or v is None:
        return v
    s = str(v).strip().lower()
    return True if s in ("true", "yes", "y", "1") else False if s in ("false", "no", "n", "0") else None


def _validate_summary(raw: dict, name: str) -> dict:
    """Coerce a model's JSON into the exact summary schema; bad fields become safe defaults."""
    mood = str(raw.get("mood", "unknown")).lower()
    pain = raw.get("pain_or_fall")
    p = str(pain).strip().lower()
    pain = None if p in ("", "none", "null", "no", "false", "n/a") or p.startswith(("no ", "none", "not ")) else str(pain)[:200]
    concerns = raw.get("concerns")
    concerns = [str(c)[:120] for c in concerns if str(c).strip()] if isinstance(concerns, list) else []
    urgency = str(raw.get("urgency", "watch")).lower()
    return {"meds_taken": _tri(raw.get("meds_taken")), "ate": _tri(raw.get("ate")),
            "mood": mood if mood in ("good", "ok", "low", "unknown") else "unknown",
            "pain_or_fall": pain, "concerns": concerns,
            "urgency": urgency if urgency in ("ok", "watch", "urgent") else "watch",
            "summary_text": str(raw.get("summary_text") or f"Call with {name} completed.")[:300],
            "trend_flags": []}


def summarize(name: str, language: str, transcript: list[dict]) -> dict:
    """End-of-call structured summary (always English, for the caregiver)."""
    if not any(t["role"] == "senior" for t in transcript):
        return {"meds_taken": None, "ate": None, "mood": "unknown", "pain_or_fall": None,
                "concerns": ["No response to the call"], "urgency": "watch",
                "summary_text": f"{name} did not answer or respond to today's call.", "trend_flags": []}
    convo = "\n".join(f"{'CheckIn' if t['role'] == 'ai' else name}: {t['text']}" for t in transcript)
    system = "You summarize check-in phone calls with an older adult for their family. Use only facts stated in the transcript. Output JSON only."
    user = f"""Transcript (language: {_lang(language)}):
{convo}

Fill in this JSON, in English, based ONLY on what {name} said:
{{"meds_taken": true or false or null,
 "ate": true or false or null,
 "mood": "good" or "ok" or "low" or "unknown",
 "pain_or_fall": "short description, or null if none mentioned",
 "concerns": ["short phrases"],
 "urgency": "ok" or "watch" or "urgent",
 "summary_text": "one or two sentences for the family, third person"}}
Rules: null means not discussed. meds_taken=false if they forgot or skipped medication. ate=false if they skipped meals or had almost nothing. mood "low" if sad, lonely or down. urgency "urgent" for a fall, chest pain or trouble breathing; "watch" for missed meds, skipped meals, low mood, pain, or confusion; otherwise "ok"."""
    _check_provider()
    try:
        s = _validate_summary(_parse_json(call_model(system, user, 500, json_mode=True)), name)
    except RuntimeError:
        raise
    except Exception:
        s = _validate_summary({"concerns": ["Could not summarize call"], "urgency": "watch",
                               "summary_text": f"Call with {name} completed but the summary failed."}, name)
    _backstop(s, " ".join(t["text"] for t in transcript if t["role"] == "senior"))
    # Safety net: emergency words in the senior's own speech force urgent.
    if any(t["role"] == "senior" and mentions_emergency(t["text"]) for t in transcript):
        s["urgency"] = "urgent"
    return s


MEDS_NO = r"(forgot|skipped|missed|didn't take|did not take|haven't taken|have not taken|not taken|not yet taken|didn't see the point).{0,40}(pill|med|tablet)|(pill|med|tablet)s?.{0,25}(forgot|skipped|missed|not yet)|did not take my pills|skipped my pills"
MEDS_YES = r"(took|taken|had) (my|the) (pill|med|tablet)"
ATE_NO = r"(not (very )?hungry|didn't eat|did not eat|skipped (breakfast|lunch|dinner|a meal|meals)|only had (a|some) |not eat|haven't eaten|just had (tea|a cracker|coffee))"


PAIN_WORDS = r"\b(knee|pain|painful|hurt|hurts|sore|ache|aches|aching|dizzy)\b"
MOOD_LOW = r"\b(sad|lonely|down|depressed|miserable|no point|don't see the point|hopeless)\b"


def _backstop(s: dict, said: str) -> None:
    """A small model often leaves fields null or wrong. Fix the clear-cut cases from the senior's own
    words, then derive urgency from the fields (so it never depends on the model's judgement)."""
    t = said.lower()
    if re.search(MEDS_NO, t):
        s["meds_taken"] = False
    elif re.search(MEDS_YES, t):
        s["meds_taken"] = True
    if re.search(ATE_NO, t):
        s["ate"] = False
    if not s["pain_or_fall"]:
        hit = next((x.strip() for x in re.split(r"(?<=[.!?])\s+", said) if re.search(PAIN_WORDS, x.lower())
                    and not re.search(r"\b(no|not|without) (any )?(pain|hurt)", x.lower())), None)
        s["pain_or_fall"] = hit[:200] if hit else None
    if re.search(MOOD_LOW, t):
        s["mood"] = "low"
    if s["urgency"] != "urgent":
        worrying = s["meds_taken"] is False or s["ate"] is False or s["mood"] == "low" or bool(s["pain_or_fall"])
        s["urgency"] = "watch" if worrying else "ok"


def _streak(calls: list[dict], pred) -> int:
    """How many of the most recent calls in a row satisfy pred."""
    n = 0
    for c in reversed(calls):
        if not pred(c):
            break
        n += 1
    return n


def detect_trends(today: dict, history: list[dict]) -> list[str]:
    """Compare today with the last 6 calls (a 7-call window) and return up to 3 short flags.

    Counting is done in plain code over the validated summary fields: llama3.2 miscounted streaks
    and invented patterns when we asked it to compare calls itself (see AI_LOG.md).
    """
    if not history:
        return []
    calls = history[-6:] + [today]
    flags = []
    pain = _streak(calls, lambda c: bool(c.get("pain_or_fall")))
    if pain >= 2:
        flags.append(f"pain reported {pain} days in a row")
    missed = sum(1 for c in calls if c.get("meds_taken") is False)
    if missed >= 2:
        flags.append(f"missed meds {missed} times this week")
    low = _streak(calls, lambda c: c.get("mood") == "low")
    score = {"good": 2, "ok": 1, "low": 0}
    moods = [score[c["mood"]] for c in calls if c.get("mood") in score][-3:]
    if low >= 2:
        flags.append(f"low mood {low} days in a row")
    elif len(moods) == 3 and moods[0] > moods[-1] and moods == sorted(moods, reverse=True):
        flags.append("mood declining")
    skipped = sum(1 for c in calls if c.get("ate") is False)
    if skipped >= 2:
        flags.append(f"skipped meals {skipped} times this week")
    return flags[:3]
