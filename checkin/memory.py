"""JSON-file storage: call history and the caregiver's question queue.

One file per senior at data/<senior_id>.json:
    {"calls": [summary, ...], "questions": ["...", ...]}
"""
import json
import os
import re
from datetime import datetime

from checkin import config


def senior_id(phone: str) -> str:
    """Stable id from a phone number (digits only)."""
    return re.sub(r"\D", "", phone or "") or "default"


def _path(sid: str) -> str:
    return os.path.join(config.DATA_DIR, f"{sid}.json")


def _load(sid: str) -> dict:
    try:
        with open(_path(sid)) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault("calls", [])
    data.setdefault("questions", [])
    return data


def _save(sid: str, data: dict) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_path(sid), "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_history(sid: str, n: int = 7) -> list[dict]:
    """The last n call summaries, oldest first."""
    return _load(sid)["calls"][-n:]


def save_call(sid: str, summary: dict, when: str | None = None) -> None:
    data = _load(sid)
    data["calls"].append({"date": when or datetime.now().strftime("%Y-%m-%d"), **summary})
    _save(sid, data)


def add_question(sid: str, text: str) -> None:
    data = _load(sid)
    data["questions"].append(text.strip())
    _save(sid, data)


def get_questions(sid: str) -> list[str]:
    return _load(sid)["questions"]


def clear_questions(sid: str) -> None:
    """Call after the senior has been asked (end of a completed call)."""
    data = _load(sid)
    data["questions"] = []
    _save(sid, data)


def reset(sid: str) -> None:
    if os.path.exists(_path(sid)):
        os.remove(_path(sid))
