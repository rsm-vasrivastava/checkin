# AI_LOG: how we used AI coding tools

We used Claude Code (Sonnet 5.5) as our pair programmer. Entries are appended after each milestone.

## Milestone 1: skeleton
- **Asked:** Create the repo skeleton, .gitignore, .env.example, requirements and stubs.
- **Produced:** Folder layout, config.py, requirements.txt, README and AI_LOG stubs.
- **Changed/rejected:** The AI added `python-multipart` (FastAPI needs it to read Twilio's form-encoded webhooks), which was not in our brief. Our one-line existing README was replaced by a stub.
- **Bugs caught:** none at this stage; nothing had logic yet beyond imports.

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

## Vapi as the phone-call front end (time-box: working by 4:00 PM, else revert to voice mode)
- **Asked:** replace Twilio for the live call with Vapi: `vapi_call.py` (outbound call with an inline assistant built from our prompt, trend flags and queued questions), a `/vapi/end` webhook that runs the transcript through our own summarize/trend/save/alert code, and README/.env updates. Keep `voice_mode.py` and the Twilio code.
- **Process:** the AI was told not to guess field names, so it read Vapi's current docs before writing code (create-call, server events, server authentication, timeouts, hang-up tool). The docs pages are very large and the fetch tool only read part of them, so we only used field names that were explicitly confirmed (`phoneNumberId`, `customer.number`, `assistant.{firstMessage, model.{provider,model,messages,tools}, voice, transcriber, server.{url,headers}, serverMessages, maxDurationSeconds, silenceTimeoutSeconds, endCallMessage}`, the `endCall` tool, and the `end-of-call-report` / `transcript` message shapes).
- **Things the docs told us that changed the design:**
  1. For an inline (transient) assistant Vapi sends **no credential** on webhooks, so `/vapi/end` would be open to anyone. We added our own shared secret (`VAPI_WEBHOOK_SECRET`) sent back in `server.headers`, and the endpoint refuses everything if no secret is set.
  2. **Free Vapi numbers are inbound-only.** Outbound calls need a number imported from Twilio/Telnyx/DIDWW, so this does not remove the need for a telephony account. We kept going because the team may already have one, and flagged it in the setup notes.
  3. The conversation LLM now runs in Vapi's cloud, so the "never leaves the device" claim no longer holds for phone calls. We removed it for calls and say so in the README. Summaries are still generated by our own local model.
  4. Vapi cannot enforce "max 6 turns" in code the way our loop does; it is a prompt instruction plus a hard 5-minute cap and a 20 s silence timeout.
- **Safety added:** subscribing to live `transcript` messages lets our server fire an urgent alert the moment a final user transcript contains a fall / chest pain / breathing phrase, independent of the assistant's behaviour.
- **Verified (offline only):** the request builds (prompt contains name, trend flags, queued question and the emergency script); `/vapi/end` rejects missing or wrong secrets; partial and assistant transcripts are ignored; a final user emergency alerts exactly once; the end-of-call report is saved, the summary alert is sent without a second URGENT prefix, a repeated report is idempotent, and an unanswered call is recorded as "no response". Earlier Twilio, voice-mode and simulator tests still pass.
- **NOT verified:** a real Vapi call. No request has been sent to Vapi; the exact assistant field values (e.g. the OpenAI voice id `alloy`, the `gpt-4o-mini` model name, Deepgram language codes) came from docs/search snippets and may be rejected by the API, in which case `vapi_call.py` prints Vapi's error.
- **Bug the AI introduced, caught by a failing test:** our test script for the Twilio path relied on `.env` for the alert channel. Once `.env` set `NOTIFY_CHANNEL=ntfy`, the test sent its fake alerts (including a fake "URGENT ... I fell in the kitchen") to the real ntfy topic instead of a stub. The tests now pin the channel and topic. This is a reminder that AI-written tests must not read real config.

## Bug caught in live voice-mode testing: concerns ignored, false "doing well", odd pain question
- **What we saw (live test):** the senior said "I was having problem in listening to them" (possible hearing difficulty). The summary had `concerns: []` and the closing said she was "doing well". One question was also odd ("accidents while talking to your family") instead of a clear pain/falls question.
- **Asked:** any problem, difficulty or complaint must go into `concerns` with urgency at least "watch"; the closing must thank, acknowledge what was shared and say family will get an update; every call must ask pain/falls as its own clear question; add "problem hearing", "can't hear", "trouble listening", "dizzy", "confused" to the backstop and to tests.
- **Produced:** `detect_concerns()` backstop (hearing/dizziness/confusion labels plus generic "problem/trouble/difficulty" sentences, with "no problem" / "can't complain" excluded); urgency >= watch whenever concerns exist; a fixed question order (meds, meals, pain/falls, family) with the question text spoken by code; a code-built closing when anything came up; the Vapi prompt updated to match. First real tests in the repo: `tests/` (pytest, 26 tests, no network, never touches real data or alerts).
- **What the fake-model tests missed, found only by running the real llama3.2 (the AI's first version was wrong):**
  1. Asking the model to "ask the next thing" was not enough: it skipped the medication question and asked off-script, and once bundled a meals question in front of the pain question. We changed it so code appends the exact question and the model only writes a one-sentence reaction.
  2. The model listed negations as concerns ("No pain", "No falls"), which, because concerns now force "watch", flagged a healthy call. Negations are filtered.
  3. The model invented a concern ("Eating breakfast") and wrote the same concern twice in different words. Model concerns must now be grounded in words the senior said, and near-duplicates are collapsed.
  4. "I feel dizzy" was also being recorded as pain because `dizzy` was in the pain word list. Removed.
- **Verified:** mutation check (disabling concern detection makes 13 tests fail); real-model runs of a healthy call (no concerns, urgency ok) and the live-test sentence (concern "Difficulty hearing", urgency watch, honest closing), repeated 3 times.
- **Still imperfect:** the backstop is English-only; Spanish/Hindi get fixed questions but only the generic closing. The model's one-sentence reactions can still be overly cheerful or slightly off.

## First real Vapi request (outbound call attempt)
- **Result 1, caught only by the real API:** HTTP 400 `assistant.model.each value in tools.property description should not exist`. The Vapi docs page we used showed a `description` field on the `endCall` tool, but the API rejects it inside `model.tools`. We removed it. Lesson: docs pages summarized by a tool are not a substitute for the API's own validation errors.
- **Result 2:** after that fix the request passed schema validation, then Vapi refused to start the call: "Numbers bought on Vapi have a daily outbound call limit. Import your own Twilio numbers to scale without limits." This is an account/number limit, not a code bug, so no call was placed and we did not retry in a loop.
- **Verified before the attempt:** the ngrok tunnel reaches our server, and `/vapi/end` returns 401 without the shared secret.
- **Not verified:** a completed Vapi call, the `/vapi/end` webhook receiving a real report, and the urgent-alert path on a real call.

## Inbound Vapi: a real call works
- **Asked:** switch to INBOUND (the senior calls our free Vapi number), configure the number via the API, protect `/vapi/end` with a shared secret, and don't expose `/call` or anything else publicly.
- **Design (after reading the docs):** set the number's `server.url` and clear `assistantId`; Vapi then POSTs an `assistant-request` for each call and we answer within its 7.5 s limit with a fresh inline assistant (so trend flags and queued questions are never stale). Only a new minimal app (`vapi_app.py`, one route, API docs disabled) is tunneled; the AI's first version had put the Vapi route inside the main app, which would have exposed `/call` and `/sms` through ngrok. The caller is checked against `SENIOR_PHONE`.
- **Verified live:** `vapi_setup.py` configured the number; a real call was answered by name; transcripts and the end-of-call report reached `/vapi/end` (3 assistant-requests, 48 transcript events, 1 report, all 200, 0 server errors); the call was saved (`meds true, ate true, mood good, urgency ok`) and the session marked finished. Through the public URL: no secret -> 401; `/`, `/call`, `/docs` -> 404.
- **Caught on the way:** the Vapi docs page for the dynamic-assistant guide 404'd, so the `assistant-request` request/response format came from the events page; the live call confirmed it. 33 tests pass (`tests/test_vapi.py` covers secret checks, nothing-else-exposed, fresh memory in the prompt, stranger refused, live urgent alert once, idempotent report).
- **Rough edges seen in the live transcript:** Vapi's own model split a question ("Did you take ... / Margaret?") and ended with an awkward half-sentence; the 6-turn limit is a prompt instruction, not enforced in code; the team confirmed the summary alert arrived via ntfy on a phone, and the urgent path has since been verified on a real call (below). The hearing-difficulty case has not been tested on a real call.
- **Urgent path verified on a real call:** the senior said "I fell in the kitchen today"; the final user transcript reached `/vapi/end` mid-call (15:51:34), the team received the URGENT ntfy while the call was live, the assistant ended the call itself (`assistant-ended-call`), and the saved summary was `urgency: urgent` with `pain_or_fall: "fell in the kitchen"` and a matching concern. The post-call summary alert also arrived. One wrinkle: the summary text said she "is feeling low", which she never said, i.e. the local model over-reads; the structured urgency and pain fields were right.

## Human decisions and review (written by the team)

### Tools we used

- **Claude Code** (Sonnet 5.5) in the Ghostty terminal wrote and tested almost all the code.
- **Claude (chat)** helped us pick a track, plan the project around the judging criteria, and write the Claude Code prompts.
- We gave Claude Code one detailed spec up front, covering the track rules, judging criteria, milestones and safety rules, instead of asking for features piece by piece.

### What was distinctive about our approach

- **Mock mode first:** we had Claude Code build a terminal simulator before any phone integration, so the core logic was testable and we always had a working backup demo.
- **AI for conversation, code for safety:** the small local model miscounted trends (it said "pain 3 days" when the script had 6, and invented missed meds). We kept the AI for understanding speech and moved trend counting, urgency and the emergency script into plain code. Safety decisions shouldn't depend on a model guessing.
- **Humans tested it live:** automated tests passed, but when we spoke to voice mode ourselves, we caught bugs the tests missed.
- **Three front ends, one brain:** the same memory, trend and safety logic runs behind a real phone call (Vapi), a speaker-based voice mode, and a terminal simulator. That gave us a working fallback at every stage.

### Decisions we made when plans changed

- **No API key → local model.** We had no Anthropic API key, so we switched to Llama 3.2 running locally through Ollama. Side benefit: the AI conversation stays on our machine.
- **Twilio required payment → voice mode plus ntfy.** Twilio's trial account no longer includes a phone number, so we built a speaker-based voice mode with free push alerts to the caregiver, and kept the Twilio phone code as the production design.
- **Real phone calls via Vapi, flipped to inbound.** Twilio wanted payment, and outbound calling through Vapi wasn't free either. We found that a free Vapi number could *receive* calls, so we flipped the design: the senior calls CheckIn instead of CheckIn calling her. Vapi handles the phone line and speech; our own code receives the transcript and does the summary, trend memory and caregiver alert. We verified it on real calls: a normal check-in, and an emergency where the urgent alert reached the caregiver's phone while the call was still live.
- **Security choice:** our server is exposed to the internet through ngrok during the demo, so we protected the Vapi webhook with a shared secret and kept every other endpoint private. We shut the tunnel down whenever we weren't testing.

### Bugs we caught

- **Summary over-reading:** on the real emergency call, the summary text said the caller was "feeling low," which she never said. The structured fields that drive alerts (urgency, fall) were correct, so the alert was right. This is a limitation of the small local model, and it's why alert decisions come from the structured fields and code rules, not the free-text summary.
- **Missed hearing concern.** In a live test, "Margaret" said she had trouble hearing her family. The AI ignored it, told her she was "doing well," and logged no concerns. We had Claude Code fix it so any reported difficulty becomes a concern, and add tests for it.
- **Silent failure.** A missing API key was hidden by a fallback, so the simulator looked like it worked when it didn't. It now fails with a clear error.
- **False alarms.** After the fix, phrases like "No pain" were wrongly logged as concerns. This was caught and filtered.
- We asked Claude Code to prove the tests work: disabling concern detection made 13 of 22 tests fail.

### What we'd do differently

- Check phone-service and API costs and trial limits before the event. We lost about an hour discovering that Twilio's trial no longer includes a number and that we had no LLM API key.
- Test the riskiest dependency (a real phone call) in the first 30 minutes, and decide on the fallback early.

## Missed check-in alert and clearer ntfy alerts (after the `working-demo` tag)
- **Asked:** add `check_missed.py` (alert once per day if there is no completed call by `CHECKIN_DEADLINE`, with a `--now` flag, safe to run repeatedly) and clearer ntfy alerts (title, priority 5/4/3, emoji tags, a short body with trend flags as bullets), with tests, without touching the Vapi call flow, `vapi_setup.py` or `voice_mode.py`.
- **Produced:** `check_missed.py`; an `alerts` marker in the history file for once-a-day alerts; `notify.send(..., level=)` with priority/tag per level and RFC 2047 encoding for non-ASCII titles (`urgent=True` still works, so `voice_mode.py` was not edited); `pipeline.format_ntfy_body()`; 23 new tests (56 total).
- **Design points:** the alert is recorded only after a successful send, so a failure is retried; a "no response" record does not count as a completed call; SMS text is unchanged (a test pins it).
- **Caught while verifying:** running the real CLI with `CHECKIN_DEADLINE=6pm` still printed "nothing to do" because the deadline was only parsed when needed; a typo would have stayed hidden until the day it mattered. It is now validated first (with a test). Our own earlier Vapi test also needed its `notify.send` stub updated for the new `level` argument.
- **Not verified:** a real missed-day ntfy delivery on a phone (only the dry-run against real data, and mocked sends in tests), cron scheduling, and the exact look of the colored tags in the ntfy app. The deadline uses the machine's local time.

## Outbound Vapi call works
- **Asked:** check whether outbound calling works now, without breaking the inbound flow (`working-demo` tag as the safe state); review `vapi_call.py` for compatibility, give one test command, stop on a limit error.
- **Review result:** `vapi_call.py` shares `build_assistant()` with the inbound path, so the assistant differs only in the greeting. The only change needed was a stale docstring (it still pointed at `app.py`). We added a test that fails if the outbound and inbound assistants differ in anything but the greeting. `vapi_setup.py`, `vapi_app.py`, `voice_mode.py` and the inbound config were not touched.
- **Result (human-run):** the team placed one outbound test call to the senior's phone and it worked. The earlier "daily outbound limit" refusal did not recur this time. We do not know whether it is a per-day limit that had reset, so the README says free numbers have a daily outbound limit and keeps inbound as the reliable path. The history shows the call was processed and saved (urgency and concerns recorded) by `/vapi/end`.
- **Earlier README and `.env.example` text that said outbound was blocked was updated** so the docs match what we saw.
