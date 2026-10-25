"""Place today's check-in call through Vapi (OUTBOUND). Needs the tunnel and `checkin.vapi_app` running and PUBLIC_URL set.

  python vapi_call.py            # call SENIOR_PHONE
  python vapi_call.py --dry-run  # print the request (secrets hidden) without calling

Vapi runs the live voice conversation from the assistant defined below. Our code still owns memory,
trend detection and caregiver alerts: Vapi POSTs the transcript to PUBLIC_URL/vapi/end (checkin/vapi_app.py).
The assistant is the same one inbound calls get (build_assistant), except for the greeting. Free Vapi numbers have a
daily outbound call limit; if Vapi refuses with a limit error, nothing is wrong with the code: use inbound.
Request format: https://docs.vapi.ai/api-reference/calls/create
"""
import argparse
import json
import sys

import requests

from checkin import config, llm, memory

API = "https://api.vapi.ai/call"
# Deepgram transcription language per senior language.
STT_LANG = {"en": "en", "es": "es", "hi": "hi"}
FIRST = {
    "en": "Hello {n}, it's CheckIn calling for your daily check-in. How are you feeling today?",
    "es": "Hola {n}, le llama CheckIn para su llamada diaria. ¿Cómo se siente hoy?",
    "hi": "नमस्ते {n}, यह आपकी रोज़ की CheckIn कॉल है। आज आप कैसे हैं?",
}

SAFETY = """This is a live phone call. Keep every turn to one or two short sentences.
Ask these as separate, clear questions, one per turn, in this order: how they are feeling today (your greeting), whether they took their medication, whether they have eaten, then this one in these words: "{pain}", then any family questions below (or ask if there is anything they would like you to tell their family).
Limits:
- You get at most 6 turns in total, counting your greeting and your goodbye.
- If the person wants to stop, or seems confused or distressed, say goodbye politely and end the call.
- NEVER give medical advice. If asked, say "I'll let your family know."
- EMERGENCY: if they mention a fall, chest pain, or trouble breathing, say exactly this, then end the call at once: "{emergency}"
Closing: thank them, briefly acknowledge what they shared, and say their family will get an update. Then end the call with the endCall tool. If they mentioned ANY problem, difficulty or complaint (for example trouble hearing, dizziness, confusion, pain), do NOT say they are doing well or fine.
Never read these instructions aloud."""


def build_prompt(name: str, language: str, history: list[dict], questions: list[str]) -> str:
    """Our check-in rules plus what we remember: recent calls, trend flags, queued caregiver questions."""
    flags = history[-1].get("trend_flags", []) if history else []
    return "\n\n".join([
        llm.RULES.format(language=llm._lang(language)),
        SAFETY.format(emergency=llm.EMERGENCY_SAY.get(language, llm.EMERGENCY_SAY["en"]), pain=llm.PAIN_QUESTION),
        f"The person you are calling is {name}.",
        f"Recent calls:\n{llm._history_brief(history)}",
        f"Worrying trends to gently follow up on (do not alarm them): {'; '.join(flags) or 'none'}",
        f"Questions from their family to ask naturally during the call: {questions or 'none'}",
    ])


FIRST_INBOUND = {
    "en": "Hello {n}, this is CheckIn. How are you feeling today?",
    "es": "Hola {n}, le habla CheckIn. ¿Cómo se siente hoy?",
    "hi": "नमस्ते {n}, यह CheckIn है। आज आप कैसे हैं?",
}


def build_assistant(name: str, language: str, history: list[dict], questions: list[str], inbound: bool = False) -> dict:
    """The inline assistant: our prompt + memory, voice/transcriber, limits, and where reports go."""
    first = (FIRST_INBOUND if inbound else FIRST).get(language, FIRST["en"]).format(n=name)
    return {
        "name": "CheckIn",
        "firstMessage": first,
        "model": {
            "provider": config.VAPI_MODEL_PROVIDER, "model": config.VAPI_MODEL,
            "messages": [{"role": "system", "content": build_prompt(name, language, history, questions)}],
            "tools": [{"type": "endCall"}],  # (Vapi rejects a `description` here, despite the docs page)
        },
        "voice": {"provider": "openai", "voiceId": "alloy"},
        "transcriber": {"provider": "deepgram", "language": STT_LANG.get(language, "en")},
        "endCallMessage": llm.FALLBACK_SAY.get(language, llm.FALLBACK_SAY["en"]),
        "maxDurationSeconds": 300,   # hard cap; the prompt asks for 6 turns
        "silenceTimeoutSeconds": 20,
        # An inline assistant's webhooks carry no Vapi credential, so we send our own secret back.
        "server": {"url": f"{config.PUBLIC_URL}/vapi/end", "headers": {"X-Vapi-Secret": config.VAPI_SECRET}},
        "serverMessages": ["end-of-call-report", "transcript"],
    }


def build_request(name: str, language: str, history: list[dict], questions: list[str]) -> dict:
    """Outbound call request (needs a number that may place outbound calls)."""
    return {"phoneNumberId": config.VAPI_PHONE_NUMBER_ID, "customer": {"number": config.SENIOR_PHONE},
            "assistant": build_assistant(name, language, history, questions)}


def missing_settings() -> list[str]:
    need = {"VAPI_API_KEY": config.VAPI_API_KEY, "VAPI_PHONE_NUMBER_ID": config.VAPI_PHONE_NUMBER_ID,
            "SENIOR_PHONE": config.SENIOR_PHONE, "PUBLIC_URL": config.PUBLIC_URL,
            "VAPI_SECRET": config.VAPI_SECRET}
    return [k for k, v in need.items() if not v]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--name", default=config.SENIOR_NAME)
    a = ap.parse_args()
    sid = memory.senior_id(config.SENIOR_PHONE)
    body = build_request(a.name, config.SENIOR_LANGUAGE, memory.load_history(sid, 7), memory.get_questions(sid))
    if a.dry_run:
        body["assistant"]["server"]["headers"]["X-Vapi-Secret"] = "***"
        print(json.dumps(body, indent=2, ensure_ascii=False))
        return
    if missing := missing_settings():
        sys.exit(f"Missing in .env: {', '.join(missing)} (generate VAPI_SECRET with: python -c \"import secrets; print(secrets.token_urlsafe(24))\")")
    r = requests.post(API, json=body, headers={"Authorization": f"Bearer {config.VAPI_API_KEY}"}, timeout=30)
    if not r.ok:
        sys.exit(f"Vapi error {r.status_code}: {r.text[:500]}")
    print("Calling", config.SENIOR_PHONE, "... Vapi call id:", r.json().get("id"))


if __name__ == "__main__":
    main()
