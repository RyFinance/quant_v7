"""Bot-level alerting -- mirrors circuit_breaker/alerts.py's
`CircuitBreakerAlerter`, which itself deliberately mirrors
polymarket_arb/polymarket_arb/alerting.py's `WebhookAlerter`: config-gated
no-op webhook (empty URL -- this build has none configured, paper-only),
always-on local JSONL log written synchronously with fsync for durability,
dedup window per alert kind so a flapping condition doesn't spam a channel.

Kept as its own small module (not importing circuit_breaker.alerts
directly) for the same reason circuit_breaker/alerts.py gave for not
importing polymarket_arb directly -- separate concerns, trivial to merge
later if desired -- but the shape, field names, and dedup mechanics are
copied deliberately.

Bot-specific event kinds (position lifecycle + every risk-stack halt):
  * ALERT_POSITION_OPENED     -- a paper order was filled and a position opened.
  * ALERT_POSITION_CLOSED     -- a paper position was closed (holding-period exit).
  * ALERT_RISK_BLOCKED        -- risk_gate blocked an order (limits or Kelly-zero).
  * ALERT_CIRCUIT_BREAKER_HALT -- risk_gate blocked because the breaker tier != armed.
  * ALERT_KILL_SWITCH_ENGAGED -- kill_switch.KILL_SWITCH file present at gate time.
  * ALERT_DRAWDOWN_CAP_TRIPPED -- kill_switch.check_capital_drawdown_cap breached
    and the bot auto-engaged the switch.
  * ALERT_EARNINGS_FEED_STALE -- no report anywhere in the universe for
    earnings_watcher.EARNINGS_FEED_STALE_DAYS; the data source has likely
    gone stale, so the bot is blind to new entries.
  * ALERT_DEAD_MANS_SWITCH    -- watchdog.py found no fresh heartbeat within
    the staleness threshold on a trading weekday (crash, machine off, or
    the scheduler itself broken -- the "one layer up" failure mode a bot
    crashing quietly can't detect about itself).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ALERTS_LOG_FILE = Path(__file__).parent / "state" / "bot_alerts.jsonl"

ALERT_POSITION_OPENED = "position_opened"
ALERT_POSITION_CLOSED = "position_closed"
ALERT_RISK_BLOCKED = "risk_blocked"
ALERT_CIRCUIT_BREAKER_HALT = "circuit_breaker_halt"
ALERT_KILL_SWITCH_ENGAGED = "kill_switch_engaged"
ALERT_DRAWDOWN_CAP_TRIPPED = "drawdown_cap_tripped"
ALERT_DEAD_MANS_SWITCH = "dead_mans_switch"
ALERT_EARNINGS_FEED_STALE = "earnings_feed_stale"


class BotAlerter:
    def __init__(self, webhook_url: str = "", dedup_window_s: float = 60.0, alerts_path: Path = ALERTS_LOG_FILE):
        self._url = webhook_url or ""
        self._dedup_window_s = dedup_window_s
        self._last_fired: dict[str, float] = {}
        self._alerts_path = alerts_path

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def _should_fire(self, kind: str) -> bool:
        return (time.monotonic() - self._last_fired.get(kind, 0.0)) >= self._dedup_window_s

    def alert(self, kind: str, message: str, **fields):
        self._write_record(kind, message, fields)
        if not self.enabled or not self._should_fire(kind):
            return
        self._last_fired[kind] = time.monotonic()
        # No webhook configured in this build (paper/research only). The
        # send path is intentionally absent rather than stubbed -- calling
        # out to a real webhook is exactly the kind of side effect this
        # paper-only bot should never perform silently on its own.

    def _write_record(self, kind: str, message: str, fields: dict):
        record = {"ts": time.time(), "kind": kind, "message": message, **fields}
        self._alerts_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._alerts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())


def build_alerter() -> BotAlerter:
    return BotAlerter(webhook_url="")  # no-op by design; see class docstring
