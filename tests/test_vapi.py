"""Vapi inbound: the only publicly exposed app (checkin.vapi_app). No network."""
import pytest
from fastapi.testclient import TestClient

from checkin import config, llm, memory, notify

SID = "15551110000"
H = {"X-Vapi-Secret": "s3cret"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "SENIOR_PHONE", "+1 (555) 111-0000")
    monkeypatch.setattr(config, "SENIOR_NAME", "Margaret")
    monkeypatch.setattr(config, "VAPI_SECRET", "s3cret")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://x.ngrok.app")
    monkeypatch.setattr(config, "NOTIFY_CHANNEL", "ntfy")
    monkeypatch.setattr(config, "NTFY_TOPIC", "tt")
    sent = []
    monkeypatch.setattr(notify, "send", lambda title, body, urgent=False, level=None: sent.append((title, body, urgent or level == "urgent")))
    monkeypatch.setattr(llm, "call_model", lambda *a, **k: '{"meds_taken": true, "mood": "ok", "urgency": "ok", "summary_text": "Fine."}')
    from checkin.vapi_app import app
    c = TestClient(app)
    c.sent = sent
    return c


def post(c, msg, headers=H):
    return c.post("/vapi/end", json={"message": msg}, headers=headers)


def test_rejects_missing_or_wrong_secret(client):
    assert client.post("/vapi/end", json={}).status_code == 401
    assert post(client, {}, {"X-Vapi-Secret": "nope"}).status_code == 401
    assert post(client, {}, {"Authorization": "Bearer s3cret"}).status_code == 200


def test_refuses_everything_when_no_secret_configured(client, monkeypatch):
    monkeypatch.setattr(config, "VAPI_SECRET", "")
    assert client.post("/vapi/end", json={}, headers={"X-Vapi-Secret": ""}).status_code == 401


def test_nothing_else_is_exposed(client):
    for path in ["/", "/call", "/sms", "/voice", "/gather", "/status", "/docs", "/openapi.json", "/redoc"]:
        assert client.get(path).status_code in (404, 405), path
        assert client.post(path, data={}).status_code in (404, 405), path


def test_assistant_request_returns_assistant_with_fresh_memory(client):
    memory.save_call(SID, {"summary_text": "knee sore", "trend_flags": ["pain reported 3 days in a row"], "urgency": "watch"})
    memory.add_question(SID, "Did you call your sister?")
    r = post(client, {"type": "assistant-request", "call": {"id": "C1", "customer": {"number": "+15551110000"}}})
    a = r.json()["assistant"]
    prompt = a["model"]["messages"][0]["content"]
    assert "pain reported 3 days in a row" in prompt and "sister" in prompt and llm.PAIN_QUESTION in prompt
    assert a["server"]["url"] == "https://x.ngrok.app/vapi/end" and a["server"]["headers"]["X-Vapi-Secret"] == "s3cret"
    assert "end-of-call-report" in a["serverMessages"] and a["model"]["tools"] == [{"type": "endCall"}]
    assert "this is CheckIn" in a["firstMessage"]  # inbound wording, not "calling for your daily check-in"


def test_assistant_request_refuses_other_callers(client):
    r = post(client, {"type": "assistant-request", "call": {"id": "C2", "customer": {"number": "+19998887777"}}})
    assert r.json() == {"error": "Sorry, this line is private."}


def test_live_urgent_alert_once_then_report_saved_without_second_urgent_prefix(client):
    def tr(role, t, typ="final"):
        return {"type": "transcript", "role": role, "transcriptType": typ, "transcript": t, "call": {"id": "C3"}}
    post(client, tr("user", "I fell", "partial")); post(client, tr("assistant", "did you fall?"))
    assert client.sent == []
    post(client, tr("user", "I fell in the kitchen")); post(client, tr("user", "I fell again"))
    assert len(client.sent) == 1 and client.sent[0][2] is True
    report = {"type": "end-of-call-report", "endedReason": "hangup", "call": {"id": "C3"}, "artifact": {"messages": [
        {"role": "system", "message": "prompt"}, {"role": "assistant", "message": "Hello"}, {"role": "user", "message": "I fell in the kitchen"}]}}
    assert post(client, report).json() == {}
    assert memory.load_history(SID)[-1]["urgency"] == "urgent"
    assert len(client.sent) == 2 and not client.sent[1][1].startswith("URGENT")
    post(client, report)  # Vapi may retry: must not save twice
    assert len(memory.load_history(SID)) == 1


def test_unanswered_call_is_recorded_as_no_response(client):
    post(client, {"type": "end-of-call-report", "endedReason": "customer-did-not-answer", "call": {"id": "C4"}, "artifact": {"messages": []}})
    assert memory.load_history(SID)[-1]["concerns"] == ["No response to the call"]


def test_outbound_assistant_is_the_inbound_assistant_except_for_the_greeting(client):
    """vapi_call.py (outbound) and the inbound assistant-request must never drift apart."""
    import vapi_call
    memory.save_call(SID, {"summary_text": "knee sore", "trend_flags": ["pain reported 3 days in a row"], "urgency": "watch"})
    h, q = memory.load_history(SID), memory.get_questions(SID)
    out = vapi_call.build_request("Margaret", "en", h, q)
    inbound = vapi_call.build_assistant("Margaret", "en", h, q, inbound=True)
    assert [k for k in out["assistant"] if out["assistant"][k] != inbound[k]] == ["firstMessage"]
    assert "daily check-in" in out["assistant"]["firstMessage"]
    assert out["customer"]["number"] == "+1 (555) 111-0000" and set(out) == {"assistant", "customer", "phoneNumberId"}
    assert out["assistant"]["server"]["headers"]["X-Vapi-Secret"] == "s3cret"
