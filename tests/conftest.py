"""Test isolation: never touch real data, real alerts or the network, whatever .env says."""
import pytest
import requests

from checkin import config, llm


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "NOTIFY_CHANNEL", "sms")
    monkeypatch.setattr(config, "NTFY_TOPIC", "")
    monkeypatch.setattr(config, "CAREGIVER_PHONE", "")
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")

    def blocked(*a, **k):
        raise RuntimeError("real HTTP blocked in tests")
    monkeypatch.setattr(requests, "post", blocked)
    monkeypatch.setattr(llm, "call_model", lambda *a, **k: "")  # each test installs its own fake


@pytest.fixture
def model(monkeypatch):
    """Install a fake model: model(summary_json=..., reply=...) -> list of (system, user) prompts seen."""
    def install(summary_json='{"meds_taken": true, "ate": true, "mood": "good", "pain_or_fall": null, '
                             '"concerns": [], "urgency": "ok", "summary_text": "She is doing well."}',
                reply="That's good."):
        seen = []

        def fake(system, user, max_tokens=300, json_mode=False):
            seen.append(user)
            return summary_json if json_mode else reply
        monkeypatch.setattr(llm, "call_model", fake)
        return seen
    return install
