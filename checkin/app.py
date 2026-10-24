"""FastAPI webhooks: /call, /voice, /gather, /status, /sms.

Each Twilio request is independent; the conversation is kept in a small per-call file
keyed by CallSid (see memory.load_session), so any server instance can handle any request.
"""
import re

from fastapi import BackgroundTasks, FastAPI, Form, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import Gather, VoiceResponse

from checkin import config, llm, memory, pipeline, twilio_client

app = FastAPI(title="CheckIn")

# Twilio speech-recognition language and a matching voice per senior language.
VOICES = {"en": ("en-US", "Polly.Joanna"), "es": ("es-US", "Polly.Lupe"), "hi": ("hi-IN", "Polly.Aditi")}


def _sid() -> str:
    return memory.senior_id(config.SENIOR_PHONE)


def _twiml(vr: VoiceResponse) -> Response:
    return Response(content=str(vr), media_type="application/xml")


def _speak(vr: VoiceResponse, text: str) -> None:
    lang, voice = VOICES.get(config.SENIOR_LANGUAGE, VOICES["en"])
    vr.say(text, language=lang, voice=voice)


def _say_and_listen(text: str) -> VoiceResponse:
    """Speak, then listen. If nothing is heard, Twilio falls through to the redirect (silence path)."""
    vr = VoiceResponse()
    lang, voice = VOICES.get(config.SENIOR_LANGUAGE, VOICES["en"])
    g = Gather(input="speech", action="/gather", method="POST", language=lang,
               speech_timeout="auto", timeout=6)
    g.say(text, language=lang, voice=voice)
    vr.append(g)
    vr.redirect("/gather", method="POST")
    return vr


def _new_state() -> dict:
    return {"transcript": [], "turn": 0, "silent": 0, "finished": False, "urgent_sent": False}


def _finish(call_sid: str) -> None:
    """Summarize, detect trends, save, text the caregiver. Runs once per call (background task)."""
    state = memory.load_session(call_sid)
    if state is None or state["finished"]:
        return
    state["finished"] = True  # set first so /status can't double-finish
    memory.save_session(call_sid, state)
    summary = pipeline.finish_call(_sid(), config.SENIOR_NAME, config.SENIOR_LANGUAGE, state["transcript"])
    pipeline.notify_caregiver(config.SENIOR_NAME, summary, state["urgent_sent"])


def _alert_urgent(call_sid: str, quote: str) -> None:
    """Text the caregiver the moment an emergency is mentioned (background task).
    On failure, clear the flag so the end-of-call SMS carries the URGENT prefix instead."""
    try:
        twilio_client.send_sms(config.CAREGIVER_PHONE,
                               f'URGENT - CheckIn: {config.SENIOR_NAME} may need help now. They said: "{quote[:200]}". Please call them.')
    except Exception as e:
        print("urgent SMS failed:", e)
        state = memory.load_session(call_sid)
        if state:
            state["urgent_sent"] = False
            memory.save_session(call_sid, state)


@app.get("/")
def health():
    return {"ok": True}


@app.post("/call")
def call():
    """Trigger today's check-in call."""
    return {"call_sid": twilio_client.place_call(config.SENIOR_PHONE)}


@app.post("/voice")
def voice(CallSid: str = Form(...)):
    """Twilio hits this when the senior picks up: greet and listen."""
    state = _new_state()
    state["turn"] = 1
    out = llm.next_turn(config.SENIOR_NAME, config.SENIOR_LANGUAGE, memory.load_history(_sid(), 7),
                        memory.get_questions(_sid()), [], 1)
    state["transcript"].append({"role": "ai", "text": out["say"]})
    memory.save_session(CallSid, state)
    return _twiml(_say_and_listen(out["say"]))


@app.post("/gather")
def gather(bg: BackgroundTasks, CallSid: str = Form(...), SpeechResult: str = Form("")):
    state = memory.load_session(CallSid) or _new_state()
    heard = SpeechResult.strip()

    if not heard:  # silence: retry once, then end
        state["silent"] += 1
        memory.save_session(CallSid, state)
        if state["silent"] >= 2:
            vr = VoiceResponse()
            _speak(vr, "I couldn't hear you, so I'll let your family know. Goodbye for now.")
            vr.hangup()
            bg.add_task(_finish, CallSid)
            return _twiml(vr)
        return _twiml(_say_and_listen("Sorry, I didn't catch that. Are you there?"))

    state["silent"] = 0
    state["transcript"].append({"role": "senior", "text": heard})
    state["turn"] += 1
    out = llm.next_turn(config.SENIOR_NAME, config.SENIOR_LANGUAGE, memory.load_history(_sid(), 7),
                        memory.get_questions(_sid()), state["transcript"], state["turn"])
    state["transcript"].append({"role": "ai", "text": out["say"]})
    if out["emergency"] and not state["urgent_sent"] and config.CAREGIVER_PHONE:
        state["urgent_sent"] = True
        bg.add_task(_alert_urgent, CallSid, heard)
    memory.save_session(CallSid, state)
    if not out["end"]:
        return _twiml(_say_and_listen(out["say"]))
    vr = VoiceResponse()
    _speak(vr, out["say"])
    vr.hangup()
    bg.add_task(_finish, CallSid)
    return _twiml(vr)


@app.post("/status")
def status(bg: BackgroundTasks, CallSid: str = Form(...), CallStatus: str = Form("")):
    """Twilio's end-of-call callback: covers hang-ups mid-call and unanswered calls."""
    if memory.load_session(CallSid) is None:  # never answered
        memory.save_session(CallSid, _new_state())
    bg.add_task(_finish, CallSid)
    return {"ok": True}


def _digits(p: str) -> str:
    return re.sub(r"\D", "", p or "")


@app.post("/sms")
def sms(From: str = Form(""), Body: str = Form("")):
    """Caregiver texts a question; it is asked on the next call."""
    mr = MessagingResponse()
    if config.CAREGIVER_PHONE and _digits(From) != _digits(config.CAREGIVER_PHONE):
        return Response(content=str(mr), media_type="application/xml")  # ignore strangers
    if Body.strip():
        memory.add_question(_sid(), Body)
        mr.message(f"Got it, I'll ask {config.SENIOR_NAME} on the next call.")
    return Response(content=str(mr), media_type="application/xml")
