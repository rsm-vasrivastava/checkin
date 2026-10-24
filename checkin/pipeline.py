"""End-of-call pipeline shared by the live app and simulate.py: summarize, detect trends, save."""
from checkin import config, llm, memory


def finish_call(sid: str, name: str, language: str, transcript: list[dict],
                when: str | None = None) -> dict:
    history = memory.load_history(sid, 7)
    summary = llm.summarize(name, language, transcript)
    summary["trend_flags"] = llm.detect_trends(summary, history)
    memory.save_call(sid, summary, when)
    memory.clear_questions(sid)  # they were asked this call
    return summary


def format_summary_sms(name: str, s: dict, urgent: bool = False) -> str:
    """Short caregiver text. Plain ASCII-friendly so it works on any phone."""
    head = f"URGENT - CheckIn: {name} may need help now." if urgent else f"CheckIn: {name} ({s['urgency']})."
    parts = [head, s.get("summary_text", "")]
    if s.get("trend_flags"):
        parts.append("Trends: " + "; ".join(s["trend_flags"]) + ".")
    if config.NOTIFY_CHANNEL == "sms":  # only SMS has the two-way question loop
        parts.append("Reply to this text to send a question for the next call.")
    return " ".join(p for p in parts if p)[:600]


def notify_caregiver(name: str, summary: dict, urgent_already_sent: bool) -> None:
    """Alert the caregiver. urgent_already_sent avoids a second URGENT alert if we alerted mid-call."""
    from checkin import notify
    urgent = summary["urgency"] == "urgent" and not urgent_already_sent
    notify.send(f"CheckIn: {name} ({summary['urgency']})", format_summary_sms(name, summary, urgent),
                urgent=summary["urgency"] == "urgent")


def urgent_text(name: str, quote: str) -> str:
    return f'URGENT - CheckIn: {name} may need help now. They said: "{quote[:200]}". Please call them.'


def run_conversation(name, language, sid, speak, listen, on_emergency=None, when=None) -> dict:
    """The check-in call, independent of the front end (terminal, microphone; the phone path
    uses the same llm functions turn by turn). speak(text) outputs a line; listen() returns the
    senior's words, or "" for silence. Max turns, silence retry and the emergency path live here."""
    history, questions = memory.load_history(sid, 7), memory.get_questions(sid)
    transcript, silent = [], 0
    for turn in range(1, config.MAX_TURNS + 1):
        out = llm.next_turn(name, language, history, questions, transcript, turn)
        transcript.append({"role": "ai", "text": out["say"]})
        speak(out["say"])
        if out["emergency"] and on_emergency:
            on_emergency(next(t["text"] for t in reversed(transcript) if t["role"] == "senior"))
        if out["end"]:
            break
        reply = listen().strip()
        if not reply:  # no speech: retry once, then give up
            silent += 1
            if silent >= 2:
                break  # finish_call marks "no response" if the senior never spoke
            speak("Sorry, I didn't catch that.")
            continue
        silent = 0
        transcript.append({"role": "senior", "text": reply})
    return finish_call(sid, name, language, transcript, when=when)
