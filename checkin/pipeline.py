"""End-of-call pipeline shared by the live app and simulate.py: summarize, detect trends, save."""
from checkin import llm, memory


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
    parts.append("Reply to this text to send a question for the next call.")
    return " ".join(p for p in parts if p)[:600]


def notify_caregiver(name: str, summary: dict, urgent_already_sent: bool) -> None:
    """Text the caregiver. urgent_already_sent avoids a second URGENT text if we alerted mid-call."""
    from checkin import config, twilio_client
    if not config.CAREGIVER_PHONE:
        return
    urgent = summary["urgency"] == "urgent" and not urgent_already_sent
    twilio_client.send_sms(config.CAREGIVER_PHONE, format_summary_sms(name, summary, urgent))
