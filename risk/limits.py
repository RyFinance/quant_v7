"""Part E2 -- standard risk limits.

Mirrors polymarket_arb/risk.py's "HARD FAIL-SAFE" stance verbatim: any
single failed check ABORTS the proposed trade (no partial sizing, no
"reduce and retry"), the check function is pure math over numbers the
caller already has (no I/O, no network, safe to call in a hot loop), and
checks run in a fixed order so the failure reason is deterministic. That
module's checks were balance/staleness/liquidity/daily-cap/emergency-file;
ours are the three the spec names for E2 (max position %, max daily loss
%, max total exposure) since this build has no live balance/liquidity feed
to check against (paper-only, Part G was explicitly out of scope for
this build).
"""
from __future__ import annotations

from dataclasses import dataclass

from schemas.reason_codes import DecisionReason


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.10       # no single position > 10% of capital
    max_daily_loss_pct: float = 0.03      # halt new entries for the day past -3% daily P&L
    max_total_exposure_pct: float = 0.60  # never more than 60% of capital deployed at once


@dataclass(frozen=True)
class RiskCheckResult:
    allowed: bool
    reason: DecisionReason | None
    detail: str | None = None


def check_risk_limits(
    proposed_position_pct: float,
    current_total_exposure_pct: float,
    current_daily_pnl_pct: float,
    limits: RiskLimits = RiskLimits(),
) -> RiskCheckResult:
    """HARD FAIL-SAFE: first failing check blocks the trade outright."""
    if current_daily_pnl_pct <= -limits.max_daily_loss_pct:
        return RiskCheckResult(False, DecisionReason.RISK_BLOCKED,
                                f"daily loss {current_daily_pnl_pct:.2%} breached -{limits.max_daily_loss_pct:.2%} cap")
    if proposed_position_pct > limits.max_position_pct:
        return RiskCheckResult(False, DecisionReason.RISK_BLOCKED,
                                f"proposed position {proposed_position_pct:.2%} exceeds max {limits.max_position_pct:.2%}")
    if current_total_exposure_pct + proposed_position_pct > limits.max_total_exposure_pct:
        return RiskCheckResult(False, DecisionReason.RISK_BLOCKED,
                                f"total exposure {current_total_exposure_pct:.2%}+{proposed_position_pct:.2%} "
                                f"would exceed max {limits.max_total_exposure_pct:.2%}")
    return RiskCheckResult(True, None, None)
