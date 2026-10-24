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
