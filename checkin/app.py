"""FastAPI webhooks: /call, /voice, /gather, /status, /sms (filled in at milestones 4-5)."""
from fastapi import FastAPI

app = FastAPI(title="CheckIn")


@app.get("/")
def health():
    return {"ok": True}
