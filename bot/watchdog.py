"""Dead-man's-switch: the "one layer up" check bot/PLAN.md flagged as
"not built -- no running process exists to watch yet." Now that
run_cycle.py is scheduled to run unattended (launchd, independent of any
chat session), THIS is what watches it: if no cycle has completed
successfully within `max_age_hours` on a trading weekday, something is
wrong (crash, machine asleep/off, the scheduler itself broken) and nobody
would otherwise notice -- the exact class of silent failure the stale
`get_earnings_dates()` endpoint bug was, one level down the stack.

Deliberately its own separate, more-frequently-scheduled job (see
bot/PLAN.md's launchd notes) rather than a check run_cycle.py performs on
itself -- a process that has crashed cannot be relied on to notice its own
absence.
"""
from __future__ import annotations

from datetime import datetime

from bot.alerting import ALERT_DEAD_MANS_SWITCH, BotAlerter, build_alerter
from bot.heartbeat import HEARTBEAT_FILE, read_heartbeat_age_seconds, read_heartbeat_timestamp

DEFAULT_MAX_AGE_HOURS = 26.0


def _is_weekday(now: datetime) -> bool:
    return now.weekday() < 5  # Mon=0 .. Fri=4


def check_dead_mans_switch(
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
    heartbeat_path=HEARTBEAT_FILE,
    alerter: BotAlerter | None = None,
) -> bool:
    """Returns True iff the switch fired (alert was written). Only
    evaluates on weekdays -- the scheduled cycle only runs Mon-Fri, so a
    stale weekend heartbeat is expected, not a failure, and would otherwise
    false-alarm every single week."""
    now = now or datetime.now()
    if not _is_weekday(now):
        return False

    alerter = alerter or build_alerter()
    age_seconds = read_heartbeat_age_seconds(heartbeat_path)
    age_hours = age_seconds / 3600.0
    if age_hours <= max_age_hours:
        return False

    last_ts = read_heartbeat_timestamp(heartbeat_path)
    last_seen = datetime.fromtimestamp(last_ts).isoformat() if last_ts is not None else "never"
    alerter.alert(
        ALERT_DEAD_MANS_SWITCH,
        f"no successful paper-trading cycle in {age_hours:.1f}h (threshold {max_age_hours}h) -- "
        f"last heartbeat: {last_seen}",
        age_hours=round(age_hours, 2), last_heartbeat=last_seen,
    )
    return True


if __name__ == "__main__":
    fired = check_dead_mans_switch()
    print("ALERT FIRED" if fired else "heartbeat OK")
