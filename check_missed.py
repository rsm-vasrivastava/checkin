"""Missed check-in alert: if there is no completed call today and the deadline has passed, alert the caregiver.

  python check_missed.py            # normal: honours CHECKIN_DEADLINE (local time)
  python check_missed.py --now      # ignore the deadline, check immediately (for testing)
  python check_missed.py --dry-run  # say what would happen, send nothing, record nothing

Safe to run repeatedly (e.g. from cron every 15 minutes): it alerts at most once per day, and only
after the alert was actually sent. Example crontab line:
  */15 * * * *  cd /path/to/checkin && .venv/bin/python check_missed.py
"""
import argparse
import sys
from datetime import datetime

from checkin import config, memory, notify

NO_RESPONSE = "No response to the call"


def completed_today(sid: str, today: str) -> bool:
    """A call counts if it is dated today and the senior actually spoke (not a 'no response' record)."""
    return any(c.get("date") == today and NO_RESPONSE not in (c.get("concerns") or [])
               for c in memory.load_history(sid, 14))


def parse_deadline(text: str) -> tuple[int, int]:
    try:
        h, m = text.strip().split(":")
        if not (0 <= int(h) < 24 and 0 <= int(m) < 60):
            raise ValueError
        return int(h), int(m)
    except ValueError:
        raise SystemExit(f"CHECKIN_DEADLINE must look like 18:00 (24-hour, local time), got {text!r}")


def check(sid: str, name: str, now: datetime, deadline: str, force: bool = False, dry_run: bool = False) -> str:
    """Returns what happened: completed | before-deadline | already-alerted | no-channel | would-alert | alerted."""
    parse_deadline(deadline)  # validate first, so a typo is caught today and not on the day it matters
    today = now.strftime("%Y-%m-%d")
    if completed_today(sid, today):
        return "completed"
    if not force and (now.hour, now.minute) < parse_deadline(deadline):
        return "before-deadline"
    if memory.alert_sent(sid, "missed", today):
        return "already-alerted"
    if not notify.configured():
        return "no-channel"
    if dry_run:
        return "would-alert"
    notify.send(f"CheckIn: {name}", f"No check-in from {name} today. Consider calling her.", level="watch")
    memory.mark_alert_sent(sid, "missed", today)  # only after a successful send, so a failure is retried
    return "alerted"


MESSAGES = {
    "completed": "A check-in call is already recorded for today. Nothing to do.",
    "before-deadline": "The deadline has not passed yet. Nothing to do.",
    "already-alerted": "Already alerted about today's missed check-in. Nothing to do.",
    "no-channel": "No alert channel configured (set NTFY_TOPIC, or CAREGIVER_PHONE with NOTIFY_CHANNEL=sms).",
    "would-alert": "Would send the missed check-in alert (dry run: nothing sent).",
    "alerted": "Missed check-in alert sent.",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--now", action="store_true", help="ignore the deadline and check immediately")
    ap.add_argument("--dry-run", action="store_true", help="don't send or record anything")
    ap.add_argument("--name", default=config.SENIOR_NAME)
    a = ap.parse_args()
    try:
        result = check(memory.senior_id(config.SENIOR_PHONE), a.name, datetime.now(), config.CHECKIN_DEADLINE,
                       force=a.now, dry_run=a.dry_run)
    except Exception as e:  # e.g. ntfy unreachable: say so, exit non-zero so cron/the user notices
        sys.exit(f"Could not send the missed check-in alert: {e}")
    print(MESSAGES[result])


if __name__ == "__main__":
    main()
