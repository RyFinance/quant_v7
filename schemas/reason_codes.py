"""Part I3's Enum reason-code pattern, reused from the quant_v6 roadmap
(NO_CONVICTION, REGIME_UNCERTAIN, RISK_BLOCKED, EXECUTED) with
CIRCUIT_BREAKER_HALT added per this spec's own Part I3 list. Shared across
risk/, circuit_breaker/, and backtest/ so every stage of the pipeline
tags its decisions with the same vocabulary instead of each module
inventing its own ad hoc strings.
"""
from __future__ import annotations

from enum import Enum


class DecisionReason(str, Enum):
    NO_CONVICTION = "no_conviction"          # ML filter probability too close to 50/50 to size a trade
    REGIME_UNCERTAIN = "regime_uncertain"     # reserved for a future regime-detection gate (not built this phase)
    RISK_BLOCKED = "risk_blocked"             # Part E2 risk limit breached
    CIRCUIT_BREAKER_HALT = "circuit_breaker_halt"  # Part F trigger active
    EXECUTED = "executed"
