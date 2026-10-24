"""Settings loaded from .env."""
import os
from dotenv import load_dotenv

load_dotenv()

TWILIO_SID = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN", "")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CAREGIVER_PHONE = os.getenv("CAREGIVER_PHONE", "")
SENIOR_PHONE = os.getenv("SENIOR_PHONE", "")
SENIOR_NAME = os.getenv("SENIOR_NAME", "Friend")
SENIOR_LANGUAGE = os.getenv("SENIOR_LANGUAGE", "en")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()  # "ollama" (local, no key) or "anthropic"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
MODEL = os.getenv("CHECKIN_MODEL", "claude-sonnet-5-5")  # used only when LLM_PROVIDER=anthropic
MAX_TURNS = 6
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Caregiver alerts: "sms" (Twilio, production) or "ntfy" (free push). Defaults to sms when Twilio is configured.
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
NOTIFY_CHANNEL = os.getenv("NOTIFY_CHANNEL", "sms" if TWILIO_SID else "ntfy").lower()

# Vapi (hosted phone-call front end). Vapi runs the live conversation; memory, trends and alerts stay our code.
VAPI_API_KEY = os.getenv("VAPI_API_KEY", "")
VAPI_PHONE_NUMBER_ID = os.getenv("VAPI_PHONE_NUMBER_ID", "")
VAPI_WEBHOOK_SECRET = os.getenv("VAPI_WEBHOOK_SECRET", "")  # shared secret Vapi sends back on /vapi/end
VAPI_MODEL_PROVIDER = os.getenv("VAPI_MODEL_PROVIDER", "openai")
VAPI_MODEL = os.getenv("VAPI_MODEL", "gpt-4o-mini")
