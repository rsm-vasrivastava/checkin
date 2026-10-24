"""Mock mode: run a full CheckIn call in the terminal (no Twilio).

  python simulate.py              # one interactive call, you type the senior's replies
  python simulate.py --days 7     # simulate a week of scripted calls to demo trend detection
"""
import argparse
import json

from checkin import config, llm, memory, pipeline

SIM_ID = "simulated"

# One scripted senior's week: a knee that keeps hurting, mood sliding, a skipped pill.
WEEK = [
    ["Good morning! Yes I took my pills and had oatmeal. Feeling good.", "No pain, thank you dear.", "Bye bye."],
    ["Hello. Took my pills, had toast. Doing fine.", "Oh my knee is a bit sore today, nothing much.", "Okay, goodbye."],
    ["I took my pills. Just had tea, not very hungry. My knee still hurts when I climb stairs.", "A little tired.", "Goodbye."],
    ["I forgot my morning pills, I'll take them later. Knee is the same. Feeling a bit down, it is quiet here.", "No.", "Bye."],
    ["I did not take my pills yet. Not hungry. The knee is bad today and I feel lonely.", "I don't know.", "Okay."],
    ["Pills? I think so. I only had a cracker. My knee hurts a lot and I just feel sad.", "Not really.", "Bye."],
    ["I skipped my pills again, I don't see the point. Knee is still painful. I did not eat much.", "No.", "Goodbye."],
]


def say(text: str) -> None:
    print(f"\n  CheckIn: {text}")


def run_call(name: str, language: str, sid: str, replies: list[str] | None = None,
             when: str | None = None, quiet: bool = False) -> dict:
    """One call. replies=None -> read from the keyboard; else use the scripted replies."""
    history, questions = memory.load_history(sid, 7), memory.get_questions(sid)
    transcript, silent = [], 0
    for turn in range(1, config.MAX_TURNS + 1):
        out = llm.next_turn(name, language, history, questions, transcript, turn)
        transcript.append({"role": "ai", "text": out["say"]})
        if not quiet:
            say(out["say"])
        if out["end"]:
            break
        if replies is None:
            reply = input(f"  {name}: ").strip()
        else:
            reply = replies.pop(0) if replies else "Goodbye."
            if not quiet:
                print(f"  {name}: {reply}")
        if not reply:  # no speech: retry once, then give up
            silent += 1
            if silent >= 2:
                break  # finish_call marks 'no response' if the senior never spoke
            transcript.append({"role": "ai", "text": "(no speech detected, asked again)"})
            continue
        silent = 0
        transcript.append({"role": "senior", "text": reply})
    return pipeline.finish_call(sid, name, language, transcript, when=when)


def show(summary: dict, date: str | None = None) -> None:
    print(f"\n--- Summary{' ' + date if date else ''} ---")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def run_week(days: int, name: str, language: str) -> None:
    memory.reset(SIM_ID)
    print(f"Simulating {days} days of calls for {name} (scripted replies, real Claude)...")
    for d in range(days):
        date = f"Day {d + 1}"
        print(f"\n=== {date} ===")
        s = run_call(name, language, SIM_ID, replies=list(WEEK[d % len(WEEK)]), when=date, quiet=True)
        print(f"urgency={s['urgency']} mood={s['mood']} | {s['summary_text']}")
        print(f"trend flags: {s['trend_flags'] or 'none'}")
    print("\nDone. Flags on the last day are what the caregiver would get by SMS.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, help="simulate N days of scripted calls")
    p.add_argument("--name", default=config.SENIOR_NAME if config.SENIOR_NAME != "Friend" else "Margaret")
    p.add_argument("--lang", default=config.SENIOR_LANGUAGE)
    p.add_argument("--question", action="append", default=[], help="queue a caregiver question")
    a = p.parse_args()
    if a.days:
        return run_week(a.days, a.name, a.lang)
    sid = memory.senior_id(config.SENIOR_PHONE)
    for q in a.question:
        memory.add_question(sid, q)
    show(run_call(a.name, a.lang, sid))


if __name__ == "__main__":
    main()
