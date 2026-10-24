# AI_LOG: how we used AI coding tools

We used Claude Code (Sonnet 5.5) as our pair programmer. Entries are appended after each milestone.

## Milestone 1: skeleton
- **Asked:** Create the repo skeleton, .gitignore, .env.example, requirements and stubs.
- **Produced:** Folder layout, config.py, requirements.txt, README and AI_LOG stubs.
- **Changed/rejected:** (fill in)
- **Bugs caught:** (fill in)

## Milestone 2: llm.py, memory.py, simulate.py
- **Asked:** Build the Claude calls (next_turn, summarize, detect_trends), JSON-file memory with a question queue, and a terminal mock-call (`simulate.py`) as our backup demo.
- **Produced:** `llm.py`, `memory.py`, `simulate.py`, plus `pipeline.py` (end-of-call summarize, trend detection and save, shared by the simulator and the live app so the two can't drift).
- **Design choices:** An emergency-word list overrides the model's urgency (fall, chest pain, trouble breathing, in EN/ES/HI) so a safety rule never depends on the model getting it right. `max turns` is enforced in code, not just in the prompt. If the model reply can't be parsed, the call ends politely instead of going silent.
- **Bugs the AI introduced that we caught (found by testing with a fake model, before any API key was available):**
  1. A missing `ANTHROPIC_API_KEY` was swallowed by the "never leave the line silent" fallback, so the simulator looked like it worked. It now fails loudly.
  2. A call whose scripted replies ran out was labelled "no response" even though the senior had spoken. "No response" now only applies when the senior never spoke.
- **Not yet verified:** the real model's output quality; no API key has been tested yet.

## Milestones 4-5: Twilio voice loop, caregiver SMS, inbound SMS queue
- **Asked:** Build the webhooks (/call, /voice, /gather, /status, /sms), outbound/inbound SMS, and the urgent alert.
- **Produced:** `app.py`, `twilio_client.py`, `trigger_call.py`, SMS formatting/notify in `pipeline.py`. Conversation state is a small file per CallSid, so any server instance can handle any webhook. Only the configured caregiver number can add questions.
- **Rejected/changed:** The AI's first urgent-alert code mutated the session dict inside a background task after it had been saved, which was fragile. We moved the `urgent_sent` flag into the request handler and made the SMS task reset it on failure.
- **Verified:** with FastAPI's test client and a fake model and fake Twilio only (voice loop, silence retry, urgent SMS then a single summary SMS, unanswered call, caregiver question queue, stranger ignored).
- **NOT yet verified:** a live call over ngrok, real Twilio speech recognition, and the real model's wording. Those need keys and a phone.
