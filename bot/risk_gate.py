"""The single choke point every paper order must pass through.

Reuses, does not reimplement:
  * kill_switch.is_kill_switch_engaged / check_capital_drawdown_cap  (bot/)
  * risk.limits.check_risk_limits                                   (quant_v7 Phase 4/5)
  * risk.kelly.fractional_kelly_size                                (quant_v7 Phase 4/5)
  * circuit_breaker.breaker.CircuitBreakerState                     (quant_v7 Phase 4/5)
  * circuit_breaker.triggers / market_correlation                   (quant_v7 Phase 4/5)

Check order (HARD FAIL-SAFE, first failure blocks -- mirrors
polymarket_arb/risk.py:3's stance, already mirrored once in this project by
risk/limits.py's own docstring):

  1. kill switch sentinel file
  2. capital drawdown cap (auto-engages the kill switch on breach)
  3. circuit breaker tier (blocks new entries unless ARMED)
  4. risk/limits.check_risk_limits (position / exposure / daily-loss caps)
  5. Kelly size > 0 (no_conviction -- the filter doesn't like this trade)

STRUCTURAL ENFORCEMENT: `evaluate()` is the only function in this package
that can mint an *approval token*. `PaperExecutionClient.place_order`
(bot/execution.py) requires one and calls `consume_approval()`, which pops
the token from a single-use, in-process set. A token that was never minted
by a real, passing `evaluate()` call -- including one fabricated by hand --
is not in the set and is rejected; a token that WAS minted can be spent
exactly once. This makes "place a paper order without passing through the
gate" not just discouraged by convention but actually rejected at runtime.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from circuit_breaker.breaker import CircuitBreakerState, ResponseTier
from circuit_breaker.calibration_config import DEFAULT_THRESHOLDS
from circuit_breaker.market_correlation import rolling_raw_correlation_mean_abs
from circuit_breaker.triggers import (
    check_correlation_spike_trigger,
    check_infrastructure_trigger,
    check_magnitude_trigger,
)
from data.ingestion import load_universe
from quality.monitor import run_quality_checks
from risk.kelly import fractional_kelly_size
from risk.limits import RiskLimits, check_risk_limits
from schemas.reason_codes import DecisionReason

from bot.alerting import (
    ALERT_CIRCUIT_BREAKER_HALT,
    ALERT_DRAWDOWN_CAP_TRIPPED,
    ALERT_KILL_SWITCH_ENGAGED,
    ALERT_RISK_BLOCKED,
    BotAlerter,
    build_alerter,
)
from bot.kill_switch import (
    DEFAULT_MAX_DRAWDOWN_PCT,
    check_capital_drawdown_cap,
    engage_kill_switch,
    is_kill_switch_engaged,
)

REPORTS_DIR = Path(__file__).parent.parent / "reports"

# Single-use approval tokens minted by evaluate(), spent by consume_approval().
# In-process only (module-level set) -- this is scaffolding for a single-run
# paper bot, not a distributed system; a fresh process starts with none valid.
_VALID_TOKENS: set[str] = set()


@dataclass(frozen=True)
class RiskGateDecision:
    allowed: bool
    reason: DecisionReason | None
    detail: str
    size_fraction: float = 0.0
    approval_token: str | None = None


def consume_approval(token: str | None) -> bool:
    """Single-use check: True iff `token` was minted by a passing evaluate()
    call and has not already been spent. Pops it either way it's found."""
    if token is None:
        return False
    if token in _VALID_TOKENS:
        _VALID_TOKENS.discard(token)
        return True
    return False


def current_breaker_tier(
    lookback_days: int = 60,
    universe_tickers: list[str] | None = None,
) -> tuple[str, dict]:
    """Recompute TODAY's circuit breaker tier from the latest real cached
    universe data by replaying circuit_breaker's own trigger + state-machine
    functions forward from a fresh CircuitBreakerState -- NOT a re-derivation
    of the trigger math (that stays in circuit_breaker/triggers.py and
    breaker.py; this function only calls it), and NOT a static read of the
    calibration-time snapshot (reports/circuit_breaker_daily_production.csv),
    since a live bot needs the tier as of the most recent cached trading day,
    not the tier as of whenever the calibration report was last regenerated.

    Speed (F2) is intentionally NOT evaluated here: it needs real intraday
    (minute-bar) data, which this bot's daily-bar data pipeline (Phase 1)
    does not carry live. Magnitude (F1), structural/correlation (F3), and
    infrastructure (F4) are evaluated exactly as calibration_config.py
    documents. This is a real, if partial, gate -- not a stub -- and the
    omission is the same one circuit_breaker/calibration_config.py already
    documents as an accepted limitation for F2 generally.

    Returns (tier_value, detail) where detail carries the fired categories
    and the date the tier was computed as of. Fails closed to
    'halt_new_entries' (never silently ARMED) if there isn't enough cached
    history to evaluate.
    """
    if universe_tickers is None:
        selection_path = REPORTS_DIR / "universe_selection.txt"
        universe_tickers = selection_path.read_text().strip().split("\n")[1].split(",")

    data = load_universe(universe_tickers)
    if not data:
        return "halt_new_entries", {"reason": "no cached universe data available"}

    closes = {t: df.set_index(pd.to_datetime(df["timestamp"]))["close"] for t, df in data.items()}
    panel = pd.DataFrame(closes).sort_index().tail(lookback_days + DEFAULT_THRESHOLDS.speed_window_minutes + 5)
    rets = panel.pct_change(fill_method=None)
    if len(rets) < 2:
        return "halt_new_entries", {"reason": "insufficient cached history to evaluate triggers"}
    index_ret = rets.mean(axis=1)

    corr_series = rolling_raw_correlation_mean_abs(panel, lookback=min(60, max(2, len(panel) - 1)))
    if corr_series.empty:
        return "halt_new_entries", {"reason": "insufficient history for correlation trigger"}

    as_of = corr_series.index[-1]
    day_rets = rets.loc[as_of].dropna()
    mag_event = check_magnitude_trigger(
        day_rets, index_ret.loc[as_of],
        DEFAULT_THRESHOLDS.magnitude_single_asset_threshold, DEFAULT_THRESHOLDS.magnitude_index_threshold,
    )
    struct_event = check_correlation_spike_trigger(corr_series.loc[as_of], DEFAULT_THRESHOLDS.correlation_spike_threshold)
    quality_report = run_quality_checks(data)
    infra_event = check_infrastructure_trigger(
        len(quality_report.stale), len(universe_tickers), DEFAULT_THRESHOLDS.stale_fraction_threshold,
    )

    breaker = CircuitBreakerState()
    result = breaker.process_day(as_of, [mag_event, struct_event, infra_event])
    detail = {
        "as_of": str(as_of), "fired_categories": result.fired_categories,
        "magnitude_detail": mag_event.detail, "structural_detail": struct_event.detail,
        "infrastructure_detail": infra_event.detail,
    }
    return result.tier.value, detail


def evaluate(
    ticker: str,
    calibrated_proba: float,
    payoff_ratio_b: float,
    current_total_exposure_pct: float,
    current_daily_pnl_pct: float,
    paper_nav: float,
    paper_high_water_mark: float,
    limits: RiskLimits = RiskLimits(),
    kelly_fraction_mult: float = 0.25,
    max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT,
    breaker_tier: str | None = None,
    alerter: BotAlerter | None = None,
) -> RiskGateDecision:
    """The ONLY function in this package that can mint an approval token.
    Every check is pure math or a call into an existing reused module -- no
    order-placement side effect happens here."""
    alerter = alerter or build_alerter()

    # 1) kill switch -- checked first, unconditionally.
    if is_kill_switch_engaged():
        alerter.alert(ALERT_KILL_SWITCH_ENGAGED, f"kill switch engaged -- order for {ticker} blocked",
                      ticker=ticker)
        return RiskGateDecision(False, DecisionReason.RISK_BLOCKED, "kill switch engaged")

    # 2) hard capital drawdown cap -- auto-engages the kill switch on breach
    #    (a safety trip wire, never a live-enablement path; see kill_switch.py).
    drawdown = check_capital_drawdown_cap(paper_nav, paper_high_water_mark, max_drawdown_pct)
    if drawdown.breached:
        engage_kill_switch(f"capital drawdown cap breached: {drawdown.detail}")
        alerter.alert(ALERT_DRAWDOWN_CAP_TRIPPED, f"drawdown cap tripped, kill switch engaged: {drawdown.detail}",
                      ticker=ticker, drawdown_pct=drawdown.drawdown_pct)
        return RiskGateDecision(False, DecisionReason.RISK_BLOCKED, drawdown.detail)

    # 3) circuit breaker tier -- blocks NEW entries unless ARMED (existing
    #    positions' exits are never gated here -- see position_manager.py).
    tier = breaker_tier
    if tier is None:
        tier, _ = current_breaker_tier()
    if tier != ResponseTier.ARMED.value:
        alerter.alert(ALERT_CIRCUIT_BREAKER_HALT, f"circuit breaker tier={tier} -- new entry for {ticker} blocked",
                      ticker=ticker, tier=tier)
        return RiskGateDecision(False, DecisionReason.CIRCUIT_BREAKER_HALT, f"circuit breaker tier={tier}")

    # 4) Kelly size, then E2 hard limits over the proposed size.
    size_fraction = float(fractional_kelly_size(calibrated_proba, payoff_ratio_b, kelly_fraction_mult, limits.max_position_pct))
    if size_fraction <= 0.0:
        return RiskGateDecision(False, DecisionReason.NO_CONVICTION, "Kelly size <= 0 (no edge / below threshold)")

    check = check_risk_limits(size_fraction, current_total_exposure_pct, current_daily_pnl_pct, limits)
    if not check.allowed:
        alerter.alert(ALERT_RISK_BLOCKED, f"risk limits blocked order for {ticker}: {check.detail}",
                      ticker=ticker, size_fraction=size_fraction)
        return RiskGateDecision(False, check.reason, check.detail or "risk limit breached", size_fraction)

    token = secrets.token_hex(16)
    _VALID_TOKENS.add(token)
    return RiskGateDecision(True, DecisionReason.EXECUTED, "approved", size_fraction, token)
