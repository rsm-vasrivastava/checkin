"""Place today's check-in call to SENIOR_PHONE. Needs the server running and PUBLIC_URL set (ngrok)."""
from checkin import config, twilio_client

if __name__ == "__main__":
    print("Calling", config.SENIOR_PHONE, "... call sid:", twilio_client.place_call(config.SENIOR_PHONE))
