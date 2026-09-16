"""Liveness heartbeat -- mirrors polymarket_arb/polymarket_arb/alerting.py's
`Heartbeat` class (a timestamp file touched on every successful cycle,
read back externally by a separate watchdog process). Noted in bot/PLAN.md
as "not built -- no running process exists to watch yet"; now that
run_cycle.py is scheduled to actually run unattended, this is that piece.

Deliberately touched only at the END of a successful run_cycle() call, not
at the start -- a process that crashes mid-cycle (the exact failure mode
step 2 is guarding against) must NOT refresh the heartbeat, or the
watchdog would see a fresh timestamp and conclude everything is fine while
the bot is actually dead or stuck.
"""
from __future__ import annotations

import time
from pathlib import Path

STATE_DIR = Path(__file__).parent / "state"
HEARTBEAT_FILE = STATE_DIR / "heartbeat.txt"


def touch_heartbeat(path: Path | None = None) -> None:
    # `path` resolves HEARTBEAT_FILE dynamically inside the function body,
    # NOT as a `path: Path = HEARTBEAT_FILE` default parameter -- a def-time
    # default is bound ONCE at import time, so a caller who later does
    # `bot.heartbeat.HEARTBEAT_FILE = some_other_path` (as
    # live_backtest/run_historical_replay.py does, to isolate the replay
    # from the real production heartbeat file) would NOT actually redirect
    # this function -- a real bug an adversarial review caught 2026-08-19
    # (harmless in that specific case only because a second, independent
    # patch happened to bypass it; not something to rely on twice). This
    # mirrors bot/kill_switch.py's KILL_SWITCH_FILE pattern, which already
    # got this right.
    path = path if path is not None else HEARTBEAT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{time.time():.3f}")


def read_heartbeat_age_seconds(path: Path | None = None) -> float:
    """Seconds since the heartbeat was last touched. `inf` if the file has
    never been written -- a missing heartbeat is exactly as stale as an
    infinitely-old one for the watchdog's purposes."""
    path = path if path is not None else HEARTBEAT_FILE
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return float("inf")


def read_heartbeat_timestamp(path: Path | None = None) -> float | None:
    path = path if path is not None else HEARTBEAT_FILE
    try:
        return float(path.read_text().strip())
    except (OSError, ValueError):
        return None
