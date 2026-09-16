"""Part F7 -- alerting. Directly mirrors polymarket_arb/polymarket_arb/alerting.py's
`WebhookAlerter`: config-gated no-op webhook (empty URL here -- this build
has none configured, paper/research only), always-on local JSONL log
written synchronously with fsync for durability, dedup window per alert
kind so a flapping trigger doesn't spam. Kept as its own small module
(not importing polymarket_arb directly -- these are separate projects)
but the shape, field names, and dedup mechanics are copied deliberately
so a future merge of the two alert streams is trivial.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

ALERTS_LOG_FILE = Path(__file__).parent.parent / "reports" / "circuit_breaker_alerts.jsonl"

ALERT_MAGNITUDE_TRIGGER = "magnitude_trigger"
ALERT_SPEED_TRIGGER = "speed_trigger"
ALERT_STRUCTURAL_TRIGGER = "structural_trigger"
ALERT_INFRASTRUCTURE_TRIGGER = "infrastructure_trigger"
ALERT_HALT_NEW_ENTRIES = "halt_new_entries"
ALERT_FULL_FLATTEN = "full_flatten"
ALERT_REARMED = "rearmed"


class CircuitBreakerAlerter:
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
        # no webhook configured in this build (paper/research only) -- the
        # send path is intentionally absent rather than stubbed, since
        # calling out to a real webhook is exactly the kind of side effect
        # this offline research build should never perform silently.

    def _write_record(self, kind: str, message: str, fields: dict):
        record = {"ts": time.time(), "kind": kind, "message": message, **fields}
        self._alerts_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._alerts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())


def build_alerter() -> CircuitBreakerAlerter:
    return CircuitBreakerAlerter(webhook_url="")  # no-op by design; see class docstring
