"""Parts F5-F6 -- response tiers, cooldown & re-arm logic.

Response tiers (F5):
  - ARMED: normal operation, no active halt.
  - HALT_NEW_ENTRIES (default response to ANY single trigger category
    firing): block new position entries; existing positions keep their
    normal exit logic (Part E3). This is the default per spec F5.
  - FULL_FLATTEN (reserved for CONFIRMED multi-trigger events -- 2 or more
    DISTINCT trigger categories firing on the SAME day, never a single
    soft signal escalated on its own): close everything.

Cooldown & re-arm (F6): re-arming requires `cooldown_confirmation_days`
CONSECUTIVE days with zero triggers firing, not a fixed timer that expires
regardless of continued turmoil. Every day that ANY trigger fires resets
the clean-day counter to zero -- so a choppy period that keeps
re-triggering never re-arms on a clock, only on genuine, sustained
quiet. This is the "explicit confirmation of stabilization" the spec asks
for, implemented as an actual re-check every day rather than a countdown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from circuit_breaker.alerts import (
    ALERT_FULL_FLATTEN,
    ALERT_HALT_NEW_ENTRIES,
    ALERT_REARMED,
    CircuitBreakerAlerter,
)
from circuit_breaker.triggers import TriggerEvent

DEFAULT_COOLDOWN_CONFIRMATION_DAYS = 3


class ResponseTier(str, Enum):
    ARMED = "armed"
    HALT_NEW_ENTRIES = "halt_new_entries"
    FULL_FLATTEN = "full_flatten"


@dataclass
class DayResult:
    date: object
    tier: ResponseTier
    fired_categories: list[str]
    clean_days_count: int


@dataclass
class CircuitBreakerState:
    cooldown_confirmation_days: int = DEFAULT_COOLDOWN_CONFIRMATION_DAYS
    alerter: CircuitBreakerAlerter = field(default_factory=CircuitBreakerAlerter)
    _tier: ResponseTier = field(default=ResponseTier.ARMED, init=False)
    _clean_days: int = field(default=0, init=False)
    history: list[DayResult] = field(default_factory=list, init=False)

    @property
    def tier(self) -> ResponseTier:
        return self._tier

    def process_day(self, date, trigger_events: list[TriggerEvent]) -> DayResult:
        fired = [e for e in trigger_events if e.fired]
        fired_categories = sorted({e.category.value for e in fired})
        n_distinct = len(fired_categories)

        if n_distinct == 0:
            if self._tier != ResponseTier.ARMED:
                self._clean_days += 1
                if self._clean_days >= self.cooldown_confirmation_days:
                    self.alerter.alert(ALERT_REARMED, f"circuit breaker re-armed after {self._clean_days} clean days",
                                        date=str(date))
                    self._tier = ResponseTier.ARMED
                    self._clean_days = 0
        else:
            self._clean_days = 0
            new_tier = ResponseTier.FULL_FLATTEN if n_distinct >= 2 else ResponseTier.HALT_NEW_ENTRIES
            if new_tier == ResponseTier.FULL_FLATTEN and self._tier != ResponseTier.FULL_FLATTEN:
                self.alerter.alert(ALERT_FULL_FLATTEN, f"full flatten: {n_distinct} categories fired simultaneously",
                                    date=str(date), categories=fired_categories,
                                    details=[e.detail for e in fired])
            elif new_tier == ResponseTier.HALT_NEW_ENTRIES and self._tier == ResponseTier.ARMED:
                self.alerter.alert(ALERT_HALT_NEW_ENTRIES, f"halt new entries: {fired_categories}",
                                    date=str(date), details=[e.detail for e in fired])
            # never downgrade tier just because today's trigger set is milder
            # than a still-open worse state (e.g. full_flatten yesterday,
            # single trigger today) -- re-arm is the only way down, and it
            # requires a clean run, not a lucky quiet day after a bad one.
            if new_tier == ResponseTier.FULL_FLATTEN or self._tier == ResponseTier.ARMED:
                self._tier = new_tier

        result = DayResult(date=date, tier=self._tier, fired_categories=fired_categories, clean_days_count=self._clean_days)
        self.history.append(result)
        return result
