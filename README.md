# CheckIn

**Track: No App.** A daily AI phone call that checks in on older adults living alone, remembers past calls, spots worrying trends, and keeps family in the loop by text.

> Runs on a local open-source model, so health conversations never leave the device.

## Problem and who it's for
Millions of older adults live alone. Missed medication, skipped meals, a creeping low mood or a fall can go unnoticed for days, and family far away can't tell the difference between "fine" and "not fine". CheckIn is for the older adult (who just answers the phone) and the family caregiver (who gets a short text).

## How it works
```
 Cron / trigger_call.py            Senior's any phone (landline OK)
        |                                   ^   |
        v                                   |   | speech
  POST /call --> Twilio places call --------+   v
                                       POST /voice, /gather   (stateless webhooks)
                                                |
                          local model (Ollama) writes each 1-2 sentence reply
                          (meds, meals, mood, pain; caregiver questions; follow-ups
                           from recent calls; max 6 turns)
                                                |
                                      call ends (or POST /status)
                                                v
              summarize -> {meds_taken, ate, mood, pain_or_fall, concerns,
                            urgency, summary_text}  -> data/<senior>.json
                                                |
                       trend detection vs last 7 calls -> trend_flags
                                                v
             SMS to caregiver (URGENT immediately on a fall / chest pain / breathing)
                                                ^
   Caregiver replies by SMS -> POST /sms -> "questions for next call" queue
```

## Why it requires no screen
The senior uses a phone call, nothing else. The caregiver uses text messages, nothing else: summaries come in as SMS and questions go back as SMS. No app, no login, no dashboard.

## Scalability
Works on any phone, including landlines and flip phones, with zero install. Webhooks are stateless (per-call state is a small file keyed by the Twilio CallSid), storage is plain JSON, and a call costs only telephony plus a small local model. Spanish and Hindi are supported by setting `SENIOR_LANGUAGE` (speech recognition, voice, and the model's replies all switch).

## Innovation
Not a one-off robocall: CheckIn has longitudinal memory (it follows up on "your knee" from yesterday) and a two-way caregiver loop over SMS (family texts a question, it is asked on the next call and the answer comes back in the summary). Trends such as "pain reported 6 days in a row" give family an early warning before anything is urgent.

## Real-world impact
Targets medication adherence, loneliness and early detection for older adults living alone, and gives remote caregivers a daily, low-effort signal instead of anxiety. Because the model runs locally, sensitive health conversations are not sent to a cloud AI provider (the phone carrier still carries the call and texts).

## Setup
Requires Python 3.13, [Ollama](https://ollama.com), and (for live calls) a Twilio account and ngrok.
```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
ollama pull llama3.2            # then keep `ollama serve` running
cp .env.example .env            # fill in your values; never commit .env
```
To use Claude instead, set `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=...`, and `pip install anthropic`.

## Demo
**Mock mode (no Twilio, works offline):**
```bash
.venv/bin/python simulate.py                 # one call; you type the senior's replies
.venv/bin/python simulate.py --question "Did you call your sister?"
.venv/bin/python simulate.py --days 7        # a scripted week -> trend flags (about 1 minute)
```
**Live call:**
```bash
.venv/bin/uvicorn checkin.app:app --port 8000
ngrok http 8000                               # put the https URL in PUBLIC_URL in .env
# Twilio console: set the number's incoming-SMS webhook to  <PUBLIC_URL>/sms  (HTTP POST)
.venv/bin/python trigger_call.py              # or: curl -X POST http://localhost:8000/call
```
On a Twilio trial account, verify both the senior's and caregiver's numbers first. Text the Twilio number from the caregiver's phone to queue a question.

## Safety design and limitations
- Never gives medical advice: it says "I'll let your family know."
- A fall, chest pain or trouble breathing triggers a fixed script (not model-generated) that says it is alerting family and suggests 911, then ends the call and sends an URGENT SMS immediately. Detection is a keyword list, so it can miss phrasings and can false-alarm.
- Max 6 turns; ends politely on goodbye/stop; no speech twice in a row ends the call and is recorded as "no response" (urgency "watch").
- Limitations: it is **not** a medical or emergency service and must not replace one. Small local models make mistakes, so we validate output and backstop key fields with keyword rules (English only so far; Spanish and Hindi are largely untested). Trend counting is rule-based code, not the model. One senior per deployment, no Twilio signature validation, no scheduler (use cron to hit `/call`), and call/SMS content still passes through the phone carrier and Twilio.

## How we used AI coding tools
We built this with Claude Code as a pair programmer (full detail in [AI_LOG.md](AI_LOG.md)). It wrote the first version of every module; we tested everything against fake models before real ones. Things we caught: a missing-key error hidden by a "never go silent" fallback, a mislabelled "no response" case, a too-broad "fall" emergency keyword, and, after switching to a local model, wrong trend counts and invented patterns from llama3.2. That led us to move counting and urgency into plain code and keep the model for conversation and extraction.

## Future work
Scheduler and multiple seniors; Twilio signature validation; tested Spanish/Hindi; a better local model; a weekly digest; escalation to a second caregiver if the first doesn't respond; confusion/cognitive-change detection from speech.
