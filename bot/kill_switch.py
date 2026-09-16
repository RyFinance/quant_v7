"""Kill switch + hard capital cap -- the bottom of the risk stack.

Mirrors polymarket_arb/polymarket_arb/config.py's `emergency_stop_file` /
`risk.py`'s `RiskState.emergency_triggered()` pattern directly: presence of
a sentinel file on disk hard-blocks all new order placement. That pattern
transfers to equities/PEAD with zero adaptation -- "does a file exist" has
no venue-specific semantics at all.

Two independent hard blocks live here, both checked at the very top of
risk_gate.evaluate() before anything else:

  1. KILL_SWITCH sentinel file. Engaged by writing the file (a human, an
     operator script, or -- deliberately -- NOT this bot's own autonomous
     code; see engage_kill_switch's docstring for the one exception, a
     capital-drawdown breach, which is a safety trip wire, not "going
     live"). Cleared only by deleting the file, which this package never
     does programmatically outside of tests.
  2. Hard capital drawdown cap: total paper P&L drawdown from the paper
     account's high-water mark, as a fraction of starting capital. Pure
     math over numbers the caller already has -- no I/O, no network,
     mirrors risk/limits.py's HARD FAIL-SAFE stance (first failing check
     blocks, no partial sizing).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

STATE_DIR = Path(__file__).parent / "state"
KILL_SWITCH_FILE = STATE_DIR / "KILL_SWITCH"

# Hard ceiling on paper-portfolio drawdown from its high-water mark before
# the kill switch trips automatically. This is the one case where the bot's
# OWN code is allowed to write the kill-switch file -- it is a safety trip
# wire (stop doing further damage in paper mode), never a live-trading
# enablement path, and the file it writes is the same halt sentinel a human
# operator would use, so a human always has to clear it before any single
# new paper order can go out again.
DEFAULT_MAX_DRAWDOWN_PCT = 0.20


@dataclass(frozen=True)
class KillSwitchStatus:
    engaged: bool
    reason: str | None
    engaged_at: float | None


def is_kill_switch_engaged() -> bool:
    """True iff the KILL_SWITCH sentinel file exists. Never raises."""
    try:
        return KILL_SWITCH_FILE.exists()
    except OSError:
        # Fail closed: if we can't even stat the file, treat as engaged
        # rather than silently proceeding as if it were clear.
        return True


def read_kill_switch_status() -> KillSwitchStatus:
    if not is_kill_switch_engaged():
        return KillSwitchStatus(engaged=False, reason=None, engaged_at=None)
    try:
        payload = json.loads(KILL_SWITCH_FILE.read_text())
        return KillSwitchStatus(
            engaged=True,
            reason=payload.get("reason"),
            engaged_at=payload.get("engaged_at"),
        )
    except (OSError, json.JSONDecodeError):
        return KillSwitchStatus(engaged=True, reason="unreadable sentinel file", engaged_at=None)


def engage_kill_switch(reason: str) -> None:
    """Write the sentinel file. Idempotent.

    Callers in this codebase: (a) a human/operator script calling this
    directly, (b) risk_gate's own drawdown-cap trip wire. Never called from
    any code path that also submits orders in the same breath -- engaging
    the switch and placing an order are mutually exclusive by construction
    (risk_gate checks the switch BEFORE any sizing/order logic runs).
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"reason": reason, "engaged_at": time.time()}
    KILL_SWITCH_FILE.write_text(json.dumps(payload, indent=2))


def disengage_kill_switch() -> None:
    """Remove the sentinel file. This is the explicit, human-driven
    'resume' action -- nothing in the bot's autonomous code path calls
    this. Safe to call when already clear."""
    try:
        KILL_SWITCH_FILE.unlink()
    except FileNotFoundError:
        pass


@dataclass(frozen=True)
class DrawdownCheck:
    breached: bool
    detail: str
    drawdown_pct: float


def check_capital_drawdown_cap(
    current_nav: float,
    high_water_mark: float,
    max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT,
) -> DrawdownCheck:
    """Pure math, no I/O. `high_water_mark` is the highest NAV the paper
    account has ever reached; drawdown is measured from there (not from
    starting capital), matching the industry-standard definition and
    mirroring risk/limits.py's HARD FAIL-SAFE stance -- a single breach
    blocks, it doesn't get averaged away."""
    if high_water_mark <= 0:
        return DrawdownCheck(breached=False, detail="no positive high-water mark yet", drawdown_pct=0.0)
    drawdown_pct = max(0.0, (high_water_mark - current_nav) / high_water_mark)
    breached = drawdown_pct >= max_drawdown_pct
    detail = (
        f"drawdown {drawdown_pct:.2%} from HWM {high_water_mark:.2f} "
        f"(current {current_nav:.2f}) vs cap {max_drawdown_pct:.2%}"
    )
    return DrawdownCheck(breached=breached, detail=detail, drawdown_pct=drawdown_pct)
