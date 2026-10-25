"""ntfy alert formatting: title, priority (urgent 5 / watch 4 / ok 3), emoji tag, short body with bullets."""
import pytest

from checkin import config, notify, pipeline


@pytest.fixture
def posts(monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_CHANNEL", "ntfy")
    monkeypatch.setattr(config, "NTFY_TOPIC", "tt")
    seen = []

    class R:
        def raise_for_status(self): pass
    monkeypatch.setattr(notify.requests, "post", lambda url, data=None, headers=None, timeout=None: (seen.append((url, data.decode(), headers)), R())[1])
    return seen


@pytest.mark.parametrize("level,priority,tag", [("urgent", "5", "red_circle"), ("watch", "4", "yellow_circle"), ("ok", "3", "green_circle")])
def test_priority_and_tag_per_level(posts, level, priority, tag):
    notify.send("CheckIn: Margaret", "hello", level=level)
    url, body, h = posts[-1]
    assert url == "https://ntfy.sh/tt" and h["Title"] == "CheckIn: Margaret"
    assert h["Priority"] == priority and h["Tags"] == tag


def test_old_urgent_flag_still_means_urgent_and_default_is_ok(posts):
    notify.send("t", "b", urgent=True); assert posts[-1][2]["Priority"] == "5"
    notify.send("t", "b"); assert posts[-1][2]["Priority"] == "3"


def test_non_ascii_title_is_encoded_not_mangled(posts):
    notify.send("CheckIn: José", "b", level="ok")
    title = posts[-1][2]["Title"]
    assert title.isascii() and title.startswith("=?UTF-8?B?")
    import base64
    assert base64.b64decode(title[len("=?UTF-8?B?"):-2]).decode() == "CheckIn: José"


def test_summary_alert_is_short_with_flags_as_bullets(posts):
    s = {"urgency": "watch", "summary_text": "Margaret's knee hurts.", "trend_flags": ["pain reported 3 days in a row", "missed meds 2 times this week"]}
    pipeline.notify_caregiver("Margaret", s, urgent_already_sent=False)
    _, body, h = posts[-1]
    assert body == "Margaret's knee hurts.\n• pain reported 3 days in a row\n• missed meds 2 times this week"
    assert h["Title"] == "CheckIn: Margaret" and h["Priority"] == "4" and h["Tags"] == "yellow_circle"
    assert "Reply" not in body  # ntfy is one-way


def test_urgent_summary_prefix_only_if_not_already_alerted(posts):
    s = {"urgency": "urgent", "summary_text": "Fell.", "trend_flags": []}
    pipeline.notify_caregiver("Margaret", s, urgent_already_sent=False)
    assert posts[-1][1] == "URGENT: Fell." and posts[-1][2]["Priority"] == "5"
    pipeline.notify_caregiver("Margaret", s, urgent_already_sent=True)
    assert posts[-1][1] == "Fell."  # the mid-call alert already said URGENT


def test_sms_channel_text_is_unchanged(monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_CHANNEL", "sms"); monkeypatch.setattr(config, "CAREGIVER_PHONE", "+1555")
    sms = []
    monkeypatch.setattr(notify.twilio_client, "send_sms", lambda to, body: sms.append(body))
    pipeline.notify_caregiver("Margaret", {"urgency": "ok", "summary_text": "Fine.", "trend_flags": ["x"]}, False)
    assert sms == ["CheckIn: Margaret (ok). Fine. Trends: x. Reply to this text to send a question for the next call."]
