"""check_missed.py: alert once per day when there is no completed call and the deadline has passed."""
from datetime import datetime

import pytest

import check_missed
from checkin import config, memory, notify

SID, DAY = "15551110000", "2026-10-24"


@pytest.fixture
def sent(monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_CHANNEL", "ntfy")
    monkeypatch.setattr(config, "NTFY_TOPIC", "tt")
    out = []
    monkeypatch.setattr(notify, "send", lambda title, body, urgent=False, level=None: out.append((title, body, level)))
    return out


def at(h, m=0):
    return datetime(2026, 10, 24, h, m)


def run(now, deadline="18:00", **kw):
    return check_missed.check(SID, "Margaret", now, deadline, **kw)


def test_alerts_after_deadline_with_watch_priority_and_exact_message(sent):
    assert run(at(18, 1)) == "alerted"
    assert sent == [("CheckIn: Margaret", "No check-in from Margaret today. Consider calling her.", "watch")]


def test_no_alert_before_deadline_but_now_flag_overrides(sent):
    assert run(at(17, 59)) == "before-deadline" and sent == []
    assert run(at(9), force=True) == "alerted" and len(sent) == 1


def test_exactly_at_deadline_counts_as_passed(sent):
    assert run(at(18, 0)) == "alerted"


def test_safe_to_run_repeatedly_alerts_once_per_day(sent):
    assert [run(at(18, 5)), run(at(18, 20)), run(at(23))] == ["alerted", "already-alerted", "already-alerted"]
    assert len(sent) == 1
    tomorrow = datetime(2026, 10, 25, 19, 0)  # a new day alerts again
    assert check_missed.check(SID, "Margaret", tomorrow, "18:00") == "alerted" and len(sent) == 2


def test_no_alert_when_todays_call_completed(sent):
    memory.save_call(SID, {"concerns": [], "urgency": "ok", "summary_text": "ok"}, when=DAY)
    assert run(at(20)) == "completed" and sent == []


def test_yesterdays_call_does_not_count(sent):
    memory.save_call(SID, {"concerns": [], "urgency": "ok", "summary_text": "ok"}, when="2026-10-23")
    assert run(at(20)) == "alerted"


def test_a_no_response_record_is_not_a_completed_call(sent):
    memory.save_call(SID, {"concerns": ["No response to the call"], "urgency": "watch", "summary_text": "x"}, when=DAY)
    assert run(at(20)) == "alerted"


def test_failed_send_is_not_recorded_so_it_retries(monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_CHANNEL", "ntfy"); monkeypatch.setattr(config, "NTFY_TOPIC", "tt")
    def boom(*a, **k): raise RuntimeError("ntfy down")
    monkeypatch.setattr(notify, "send", boom)
    with pytest.raises(RuntimeError):
        run(at(19))
    assert not memory.alert_sent(SID, "missed", DAY)
    calls = []
    monkeypatch.setattr(notify, "send", lambda *a, **k: calls.append(1))
    assert run(at(19, 15)) == "alerted" and calls == [1]


def test_dry_run_sends_and_records_nothing(sent):
    assert run(at(19), dry_run=True) == "would-alert" and sent == []
    assert not memory.alert_sent(SID, "missed", DAY)


def test_no_channel_configured(monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_CHANNEL", "ntfy"); monkeypatch.setattr(config, "NTFY_TOPIC", "")
    assert run(at(19)) == "no-channel"


@pytest.mark.parametrize("bad", ["6pm", "25:00", "18:60", "", "18"])
def test_bad_deadline_is_a_clear_error(bad, sent):
    with pytest.raises(SystemExit):
        run(at(19), deadline=bad)


def test_bad_deadline_is_caught_even_when_nothing_else_needs_it(sent):
    memory.save_call(SID, {"concerns": [], "urgency": "ok", "summary_text": "ok"}, when=DAY)
    with pytest.raises(SystemExit):
        run(at(20), deadline="6pm")  # a call is already recorded, but the typo is still reported
