"""The ONLY app that is exposed to the internet (via ngrok) for Vapi calls.

  uvicorn checkin.vapi_app:app --port 8000

One route, POST /vapi/end, guarded by a shared secret. The Twilio/admin app (checkin.app: /call, /sms,
/voice ...) is deliberately not mounted here, and the API docs pages are disabled, so a public URL
reaches nothing else.

Vapi sends three kinds of message here:
  assistant-request     inbound call just arrived -> we return the assistant (fresh memory in the prompt)
  transcript            live speech -> urgent words alert the caregiver right away
  end-of-call-report    call over -> summarize, trends, save, alert
"""
import hmac

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from checkin import config, llm, memory, notify
from checkin.app import _alert_urgent, _finish, _new_state, _sid
import vapi_call

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _authorized(request: Request) -> None:
    """Shared secret in X-Vapi-Secret (or Authorization: Bearer). Refuse everything if none is configured."""
    given = request.headers.get("x-vapi-secret") or request.headers.get("authorization", "").removeprefix("Bearer ")
    if not config.VAPI_SECRET or not hmac.compare_digest(given, config.VAPI_SECRET):
        raise HTTPException(status_code=401, detail="unauthorized")


def _transcript(messages: list[dict]) -> list[dict]:
    """Vapi artifact.messages -> our transcript. Keeps only what was said (assistant/user)."""
    roles = {"assistant": "ai", "bot": "ai", "user": "senior"}
    out = []
    for m in messages or []:
        text = (m.get("message") or m.get("content") or "").strip()
        if m.get("role") in roles and text:
            out.append({"role": roles[m["role"]], "text": text})
    return out


def _digits(p: str) -> str:
    return "".join(c for c in (p or "") if c.isdigit())


def _assistant_for_call(call: dict) -> dict:
    """Reply to assistant-request: our assistant, or a polite refusal if the caller isn't the senior.
    (Vapi must get this within 7.5 s: it only reads small local files, no model call.)"""
    caller = (call.get("customer") or {}).get("number")
    if caller and config.SENIOR_PHONE and _digits(caller)[-10:] != _digits(config.SENIOR_PHONE)[-10:]:
        return {"error": "Sorry, this line is private."}
    sid = _sid()
    return {"assistant": vapi_call.build_assistant(config.SENIOR_NAME, config.SENIOR_LANGUAGE,
                                                   memory.load_history(sid, 7), memory.get_questions(sid), inbound=True)}


@app.post("/vapi/end")
async def vapi_events(request: Request, bg: BackgroundTasks):
    _authorized(request)
    msg = (await request.json()).get("message", {})
    call = msg.get("call") or {}
    call_id = call.get("id") or "vapi-unknown"

    if msg.get("type") == "assistant-request":
        return _assistant_for_call(call)

    if msg.get("type") == "transcript":
        text = msg.get("transcript", "")
        if (msg.get("role") == "user" and msg.get("transcriptType") == "final"
                and llm.mentions_emergency(text) and notify.configured()):
            state = memory.load_session(call_id) or _new_state()
            if not state["urgent_sent"]:
                state["urgent_sent"] = True
                memory.save_session(call_id, state)
                bg.add_task(_alert_urgent, call_id, text)
    elif msg.get("type") == "end-of-call-report":
        state = memory.load_session(call_id) or _new_state()
        if not state["finished"]:
            state["transcript"] = _transcript((msg.get("artifact") or {}).get("messages"))
            memory.save_session(call_id, state)
            bg.add_task(_finish, call_id)  # summarizing takes a few seconds; answer Vapi immediately
    return {}
