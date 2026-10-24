"""Thin Twilio wrappers: place_call() and send_sms()."""
from twilio.rest import Client

from checkin import config

_client = None


def _c() -> Client:
    global _client
    if _client is None:
        if not (config.TWILIO_SID and config.TWILIO_TOKEN and config.TWILIO_NUMBER):
            raise RuntimeError("Twilio credentials missing: set TWILIO_SID, TWILIO_TOKEN, TWILIO_NUMBER in .env")
        _client = Client(config.TWILIO_SID, config.TWILIO_TOKEN)
    return _client


def place_call(to: str) -> str:
    """Start an outbound check-in call; Twilio fetches TwiML from /voice once answered."""
    if not config.PUBLIC_URL:
        raise RuntimeError("PUBLIC_URL is not set (your ngrok https URL)")
    call = _c().calls.create(
        to=to, from_=config.TWILIO_NUMBER, url=f"{config.PUBLIC_URL}/voice",
        status_callback=f"{config.PUBLIC_URL}/status",
        status_callback_event=["completed"], timeout=30)
    return call.sid


def send_sms(to: str, body: str) -> None:
    _c().messages.create(to=to, from_=config.TWILIO_NUMBER, body=body)
