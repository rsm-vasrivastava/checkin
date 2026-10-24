"""Voice mode: a spoken check-in through the Mac's microphone and speaker. No Twilio, no keys, no cloud.

  python voice_mode.py                      # talk to CheckIn
  python voice_mode.py --question "Did you call your sister?"

Output: macOS `say`. Input: sounddevice (mic) + faster-whisper (offline speech-to-text).
Same conversation flow, limits and safety rules as the phone call (checkin.pipeline.run_conversation).
Phone calls are the production design; this is the free front end for demos and testing.
"""
import argparse
import subprocess
import time

import numpy as np
import sounddevice as sd

from checkin import config, memory, notify, pipeline

RATE = 16000
BLOCK = 0.1            # seconds per audio block
START_WAIT = 7         # give up if nobody starts talking within this many seconds
END_SILENCE = 1.4      # stop after this much quiet following speech
MAX_SECONDS = 20       # hard cap on one answer

# macOS voice and Whisper language code per senior language.
VOICES = {"en": ("Samantha", "en"), "es": ("Paulina", "es"), "hi": ("Lekha", "hi")}

_whisper = None


def speak(text: str, language: str) -> None:
    print(f"\n  CheckIn: {text}")
    subprocess.run(["say", "-v", VOICES.get(language, VOICES["en"])[0], text], check=False)


def _model(language: str):
    """Load Whisper once. English-only 'base.en' is faster; other languages need multilingual 'base'."""
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        print("  (loading speech model; the first run downloads it once)")
        _whisper = WhisperModel("base.en" if language == "en" else "base", compute_type="int8")
    return _whisper


def record() -> np.ndarray | None:
    """Record one answer: wait for speech, stop after a pause. None if nobody spoke."""
    chunks, started, quiet_for, waited, noise = [], False, 0.0, 0.0, None
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=int(RATE * BLOCK)) as stream:
        while True:
            block, _ = stream.read(int(RATE * BLOCK))
            block = block[:, 0]
            level = float(np.sqrt(np.mean(block ** 2)))
            if noise is None:  # first block calibrates the room's noise floor
                noise = level
            loud = level > max(0.015, noise * 3)
            if loud:
                started, quiet_for = True, 0.0
            if started:
                chunks.append(block)
                quiet_for += 0 if loud else BLOCK
                if quiet_for >= END_SILENCE or len(chunks) * BLOCK >= MAX_SECONDS:
                    break
            else:
                waited += BLOCK
                if waited >= START_WAIT:
                    return None
    return np.concatenate(chunks)


def listen(language: str) -> str:
    """Record and transcribe. Returns "" for silence or unintelligible audio."""
    print("  (listening...)")
    audio = record()
    if audio is None:
        return ""
    segments, _ = _model(language).transcribe(audio, language=VOICES.get(language, VOICES["en"])[1],
                                              beam_size=1, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    print(f"  {config.SENIOR_NAME}: {text}")
    return text


def alert_urgent(name: str, quote: str) -> None:
    """Alert the caregiver as soon as an emergency is mentioned."""
    try:
        notify.send("URGENT - CheckIn", pipeline.urgent_text(name, quote), urgent=True)
        print("  [urgent alert sent to caregiver]")
    except Exception as e:
        print(f"  [urgent alert FAILED: {e}]")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--name", default=config.SENIOR_NAME if config.SENIOR_NAME != "Friend" else "Margaret")
    p.add_argument("--lang", default=config.SENIOR_LANGUAGE)
    p.add_argument("--question", action="append", default=[], help="queue a caregiver question")
    p.add_argument("--no-notify", action="store_true", help="don't send alerts (just print the summary)")
    a = p.parse_args()

    sid = memory.senior_id(config.SENIOR_PHONE)
    for q in a.question:
        memory.add_question(sid, q)
    urgent_sent = []

    def on_emergency(quote: str) -> None:
        if not a.no_notify and notify.configured() and not urgent_sent:
            urgent_sent.append(1)
            alert_urgent(a.name, quote)

    _model(a.lang)  # load before the call starts so there is no awkward pause mid-conversation
    summary = pipeline.run_conversation(a.name, a.lang, sid, lambda t: speak(t, a.lang),
                                        lambda: listen(a.lang), on_emergency=on_emergency)
    print("\n--- Summary ---")
    print(summary_json(summary))
    if a.no_notify:
        return
    if not notify.configured():
        print(f"(no caregiver alert: NOTIFY_CHANNEL={config.NOTIFY_CHANNEL} is not configured in .env)")
        return
    try:
        pipeline.notify_caregiver(a.name, summary, bool(urgent_sent))
        print(f"Caregiver alerted via {config.NOTIFY_CHANNEL}.")
    except Exception as e:
        print(f"Caregiver alert failed: {e}")


def summary_json(s: dict) -> str:
    import json
    return json.dumps(s, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
