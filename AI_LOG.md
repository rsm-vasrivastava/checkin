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

## Switch to a local model (Ollama, llama3.2)
- **Why:** we have no Anthropic API key. Asked the AI to replace the provider with Ollama over plain HTTP, keep one `call_model()` with `LLM_PROVIDER` (ollama default, anthropic optional), use `format: "json"` for structured output, validate everything, fall back to safe defaults.
- **What we saw when we ran `simulate.py --days 7` on llama3.2 (first attempt):** the model's own trend flags were wrong. It said "knee pain 3 days in a row" on day 7 when the pain had been reported for 6 days, and on day 2 it invented "missed meds 2 times" and "mood declining" before either had happened. Per-call extraction was also noisy: "I forgot my pills" came out as `null`, "I took my pills" as `false`, and "no pain" was stored as a pain description.
- **What we changed (and why):**
  1. Trend detection now counts streaks and misses in plain code over the validated fields. The model only does per-call extraction. Honest tradeoff: the "AI compares calls" part is now rules, because the small model could not count.
  2. Added a keyword backstop in `summarize()` for meds, meals, pain and mood taken from the senior's own words, and urgency is derived from those fields in code.
  3. `next_turn()` now returns plain text (1-2 sentences, trimmed in code); ending the call and the emergency script (EN/ES/HI) are decided in code, not by the model.
- **Result:** after tuning, the week's flags match the scripted ground truth: pain 6 days in a row, missed meds and low mood growing. Normal and fall conversations ran end to end against the local model.
- **Caught on review:** the first emergency word list included bare "fall", which would have sent an URGENT text for "I fall asleep early"; narrowed it. 
- **Still imperfect:** the extraction is non-deterministic (e.g. day-3 mood flipped between "ok" and "good" across runs) and the backstop regexes are English-only; Spanish and Hindi are untested.

## Voice mode (free front end) and ntfy alerts
- **Why:** we may not have a Twilio number (cost). Asked the AI for a spoken check-in through the Mac's mic and speaker, plus free caregiver alerts via ntfy.sh, keeping the Twilio path working.
- **Produced:** `voice_mode.py` (macOS `say` out; `sounddevice` mic + offline `faster-whisper` in), `notify.py` (`send()` dispatches by `NOTIFY_CHANNEL`: sms or ntfy), and `pipeline.run_conversation()`, a front-end-independent conversation loop that `simulate.py` and `voice_mode.py` now share. The Twilio webhooks were moved onto `notify.send()`.
- **Choices:** picked offline Whisper over the free Google web recognizer because audio would otherwise leave the device, which contradicts our privacy claim. Silence/end-of-speech detection is a simple loudness threshold calibrated on the first 0.1 s.
- **Verified:** the ntfy request (URL, urgent vs default priority, UTF-8 body) with a mocked HTTP call; speech-to-text on synthetic `say` audio ("I took my pills this morning and my knee hurts a little." came back exactly); the mic can be opened and captures audio; `main()` end to end with scripted speech (silence retry, urgent alert sent once then summary); and all the earlier Twilio tests still pass.
- **Bug the AI introduced, caught by reading the test output:** the ntfy summary still ended with "Reply to this text to send a question", but ntfy is one-way. The footer is now SMS-only.
- **Not verified:** a real spoken conversation (needs a human at the mic, so we have not heard `say` + mic + Whisper working together on a live call), a real ntfy delivery to a phone, and Spanish/Hindi voices. Echo from the speaker into the mic is possible on laptop speakers; headphones are safer.
