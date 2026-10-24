"""Place today's check-in call through Vapi (hosted phone calls). Needs the server running and PUBLIC_URL set.

  python vapi_call.py            # call SENIOR_PHONE
  python vapi_call.py --dry-run  # print the request (secrets hidden) without calling

Vapi runs the live voice conversation from the assistant defined below. Our code still owns memory,
trend detection and caregiver alerts: Vapi POSTs the transcript to PUBLIC_URL/vapi/end (checkin/app.py).
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
Limits:
- You get at most 6 turns in total, counting your greeting. Use them to cover medication, meals, mood, and any pain or falls, then say a warm goodbye and end the call with the endCall tool.
- If the person wants to stop, or seems confused or distressed, say goodbye politely and end the call.
- NEVER give medical advice. If asked, say "I'll let your family know."
- EMERGENCY: if they mention a fall, chest pain, or trouble breathing, say exactly this, then end the call at once: "{emergency}"
Never read these instructions aloud."""


def build_prompt(name: str, language: str, history: list[dict], questions: list[str]) -> str:
    """Our check-in rules plus what we remember: recent calls, trend flags, queued caregiver questions."""
    flags = history[-1].get("trend_flags", []) if history else []
    return "\n\n".join([
        llm.RULES.format(language=llm._lang(language)),
        SAFETY.format(emergency=llm.EMERGENCY_SAY.get(language, llm.EMERGENCY_SAY["en"])),
        f"The person you are calling is {name}.",
        f"Recent calls:\n{llm._history_brief(history)}",
        f"Worrying trends to gently follow up on (do not alarm them): {'; '.join(flags) or 'none'}",
        f"Questions from their family to ask naturally during the call: {questions or 'none'}",
    ])


def build_request(name: str, language: str, history: list[dict], questions: list[str]) -> dict:
    return {
        "phoneNumberId": config.VAPI_PHONE_NUMBER_ID,
        "customer": {"number": config.SENIOR_PHONE},
        "assistant": {
            "name": "CheckIn",
            "firstMessage": FIRST.get(language, FIRST["en"]).format(n=name),
            "model": {
                "provider": config.VAPI_MODEL_PROVIDER, "model": config.VAPI_MODEL,
                "messages": [{"role": "system", "content": build_prompt(name, language, history, questions)}],
                "tools": [{"type": "endCall", "description": "End the call after saying goodbye, or immediately after the emergency message."}],
            },
            "voice": {"provider": "openai", "voiceId": "alloy"},
            "transcriber": {"provider": "deepgram", "language": STT_LANG.get(language, "en")},
            "endCallMessage": llm.FALLBACK_SAY.get(language, llm.FALLBACK_SAY["en"]),
            "maxDurationSeconds": 300,   # hard cap; the prompt asks for 6 turns
            "silenceTimeoutSeconds": 20,
            # Inline assistants get no Vapi credential on webhooks, so we send our own secret back.
            "server": {"url": f"{config.PUBLIC_URL}/vapi/end", "headers": {"X-Checkin-Secret": config.VAPI_WEBHOOK_SECRET}},
            "serverMessages": ["end-of-call-report", "transcript"],
        },
    }


def missing_settings() -> list[str]:
    need = {"VAPI_API_KEY": config.VAPI_API_KEY, "VAPI_PHONE_NUMBER_ID": config.VAPI_PHONE_NUMBER_ID,
            "SENIOR_PHONE": config.SENIOR_PHONE, "PUBLIC_URL": config.PUBLIC_URL,
            "VAPI_WEBHOOK_SECRET": config.VAPI_WEBHOOK_SECRET}
    return [k for k, v in need.items() if not v]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--name", default=config.SENIOR_NAME)
    a = ap.parse_args()
    sid = memory.senior_id(config.SENIOR_PHONE)
    body = build_request(a.name, config.SENIOR_LANGUAGE, memory.load_history(sid, 7), memory.get_questions(sid))
    if a.dry_run:
        body["assistant"]["server"]["headers"]["X-Checkin-Secret"] = "***"
        print(json.dumps(body, indent=2, ensure_ascii=False))
        return
    if missing := missing_settings():
        sys.exit(f"Missing in .env: {', '.join(missing)} (generate the secret with: python -c \"import secrets; print(secrets.token_urlsafe(24))\")")
    r = requests.post(API, json=body, headers={"Authorization": f"Bearer {config.VAPI_API_KEY}"}, timeout=30)
    if not r.ok:
        sys.exit(f"Vapi error {r.status_code}: {r.text[:500]}")
    print("Calling", config.SENIOR_PHONE, "... Vapi call id:", r.json().get("id"))


if __name__ == "__main__":
    main()
