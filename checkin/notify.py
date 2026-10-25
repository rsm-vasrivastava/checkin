"""Caregiver alerts through one function, send(). NOTIFY_CHANNEL picks the transport:
  sms  - Twilio text to CAREGIVER_PHONE (production)
  ntfy - free push notification via ntfy.sh/<NTFY_TOPIC>, no account (voice-mode / demo path)
"""
import base64

import requests

from checkin import config, twilio_client


def configured() -> bool:
    """Is there somewhere to send alerts?"""
    return bool(config.NTFY_TOPIC) if config.NOTIFY_CHANNEL == "ntfy" else bool(config.CAREGIVER_PHONE)


# ntfy priority (1-5) and emoji tag per alert level. ntfy renders the tag as an emoji next to the title.
PRIORITY = {"urgent": 5, "watch": 4, "ok": 3}
TAGS = {"urgent": "red_circle", "watch": "yellow_circle", "ok": "green_circle"}


def send(title: str, body: str, urgent: bool = False, level: str | None = None) -> None:
    """Alert the caregiver. level is "urgent" | "watch" | "ok" (urgent=True is the older way to say urgent)."""
    level = level or ("urgent" if urgent else "ok")
    if config.NOTIFY_CHANNEL == "ntfy":
        _ntfy(title, body, level)
    else:
        twilio_client.send_sms(config.CAREGIVER_PHONE, body)


def _header(text: str) -> str:
    """HTTP headers must be ASCII; ntfy accepts RFC 2047 encoded-words for anything else (e.g. accented names)."""
    if text.isascii():
        return text
    return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode() + "?="


def _ntfy(title: str, body: str, level: str) -> None:
    if not config.NTFY_TOPIC:
        raise RuntimeError("NOTIFY_CHANNEL=ntfy but NTFY_TOPIC is not set")
    headers = {"Title": _header(title), "Priority": str(PRIORITY.get(level, 3)), "Tags": TAGS.get(level, "green_circle")}
    r = requests.post(f"https://ntfy.sh/{config.NTFY_TOPIC}", data=body.encode("utf-8"), headers=headers, timeout=10)
    r.raise_for_status()


if __name__ == "__main__":  # python -m checkin.notify  -> send a test alert on the configured channel
    send("CheckIn test", "CheckIn test alert: if you can read this, caregiver alerts work.", level="ok")
    print(f"sent via {config.NOTIFY_CHANNEL}")
