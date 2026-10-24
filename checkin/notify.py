"""Caregiver alerts through one function, send(). NOTIFY_CHANNEL picks the transport:
  sms  - Twilio text to CAREGIVER_PHONE (production)
  ntfy - free push notification via ntfy.sh/<NTFY_TOPIC>, no account (voice-mode / demo path)
"""
import requests

from checkin import config, twilio_client


def configured() -> bool:
    """Is there somewhere to send alerts?"""
    return bool(config.NTFY_TOPIC) if config.NOTIFY_CHANNEL == "ntfy" else bool(config.CAREGIVER_PHONE)


def send(title: str, body: str, urgent: bool = False) -> None:
    if config.NOTIFY_CHANNEL == "ntfy":
        _ntfy(title, body, urgent)
    else:
        twilio_client.send_sms(config.CAREGIVER_PHONE, body)


def _ntfy(title: str, body: str, urgent: bool) -> None:
    if not config.NTFY_TOPIC:
        raise RuntimeError("NOTIFY_CHANNEL=ntfy but NTFY_TOPIC is not set")
    headers = {"Title": title.encode("ascii", "ignore").decode(),  # HTTP headers must be ASCII
               "Priority": "urgent" if urgent else "default",
               "Tags": "rotating_light" if urgent else "telephone"}
    r = requests.post(f"https://ntfy.sh/{config.NTFY_TOPIC}", data=body.encode("utf-8"), headers=headers, timeout=10)
    r.raise_for_status()


if __name__ == "__main__":  # python -m checkin.notify  -> send a test alert on the configured channel
    send("CheckIn test", "CheckIn test alert: if you can read this, caregiver alerts work.")
    print(f"sent via {config.NOTIFY_CHANNEL}")
