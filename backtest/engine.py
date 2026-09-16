"""Part H -- full backtest engine. Wires every prior phase together:

  signal (C1) -> ML filter calibrated probability (D) -> Kelly size (E1)
  -> risk limits (E2) -> adaptive TP/SL exit simulation (E3) -> transaction
  cost (E4) -> circuit breaker gating on NEW entries only (F, read-only
  here -- this module never touches circuit_breaker's trigger logic, it
  only reads the daily tier that Phase 5's calibration run already
  computed and persisted to reports/circuit_breaker_daily_production.csv).

Position outcomes are precomputed once per candidate signal (vectorized
across all rows, 5 sequential day-steps) using the SAME adaptive exit
logic as Part E3, walking real day-by-day residual-return paths rather
than reusing the fixed-5-day `position_return` label from Part C2 --
Part C2's label answers "was this signal profitable if held exactly 5
days," this backtest answers "what actually happens if we trade it with
real TP/SL exits," which is the economically relevant question for a
real P&L simulation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from loguru import logger

from risk.adaptive_exits import adaptive_exit_thresholds
from risk.kelly import fractional_kelly_size
from risk.limits import RiskLimits, check_risk_limits
from risk.transaction_costs import cost_as_return

HOLDING_PERIOD = 5


def precompute_position_outcomes(
    candidates: pd.DataFrame,
    residual_returns: pd.DataFrame,
    holding_period: int = HOLDING_PERIOD,
) -> pd.DataFrame:
    """Adds `exit_day` (1..holding_period) and `realized_return` (signed,
    direction-adjusted, BEFORE transaction costs) to every candidate row by
    walking each position's real forward residual-return path against
    Part E3's adaptive TP/SL thresholds."""
    df = candidates.copy()
    direction = np.sign(df["signal"].to_numpy())

    cum_by_day = {}
    for o in range(1, holding_period + 1):
        trailing = residual_returns.rolling(o).sum().shift(-o)
        long = trailing.stack().rename(f"cum_{o}").reset_index()
        long.columns = ["date", "ticker", f"cum_{o}"]
        df = df.merge(long, on=["date", "ticker"], how="left")
        cum_by_day[o] = df[f"cum_{o}"].to_numpy() * direction  # direction-adjusted cumulative return

    n = len(df)
    exit_day = np.full(n, holding_period, dtype=int)
    realized_return = cum_by_day[holding_period].copy()
    still_open = np.ones(n, dtype=bool)

    entry_deviation = df["deviation"].to_numpy()
    cluster_std = df["cluster_std_return"].to_numpy()

    for o in range(1, holding_period + 1):
        tighten = 1.0 - (1.0 - 0.5) * (o / holding_period)  # matches risk.adaptive_exits._tighten_factor
        tp = 0.5 * np.abs(entry_deviation) * tighten
        sl = 2.0 * np.abs(cluster_std) * tighten
        cum = cum_by_day[o]
        hit_tp = still_open & (cum >= tp)
        hit_sl = still_open & (cum <= -sl)
        hit = hit_tp | hit_sl
        exit_day[hit] = o
        realized_return[hit] = cum[hit]
        still_open &= ~hit

    df["exit_day"] = exit_day
    df["realized_return"] = realized_return
    df = df.drop(columns=[f"cum_{o}" for o in range(1, holding_period + 1)])
    df = df.dropna(subset=["realized_return"])
    return df


@dataclass
class Trade:
    entry_date: object
    exit_date_offset: int
    ticker: str
    direction: int
    size_fraction: float
    gross_return: float
    net_return: float
    pnl_contribution: float


@dataclass
class BacktestResult:
    daily_nav: pd.Series
    daily_returns: pd.Series
    trades: list[Trade]
    n_trades: int
    n_candidates: int
    n_blocked_by_circuit_breaker: int
    n_blocked_by_risk_limits: int
    n_blocked_by_no_conviction: int


def simulate_portfolio(
    outcomes: pd.DataFrame,
    calibrated_proba: np.ndarray,
    payoff_ratio_b: float,
    breaker_tier_by_date: dict,
    cost_bps: float = 10.0,
    kelly_fraction_mult: float = 0.25,
    risk_limits: RiskLimits = RiskLimits(),
    min_conviction_proba: float = 0.5,
) -> BacktestResult:
    """Event-driven simulation. `breaker_tier_by_date` maps date -> one of
    'armed'/'halt_new_entries'/'full_flatten' (Phase 5's real, already-computed
    daily state -- this function only reads it, never recomputes triggers).
    New entries are allowed only when tier == 'armed'. This build has no
    portfolio state that needs an active FULL_FLATTEN unwind simulated
    (positions here are pre-committed 5-day holds decided at entry, not
    continuously-open positions that would need forced liquidation logic --
    a full execution-engine-level flatten simulation is Part G, explicitly
    out of scope for this build)."""
    df = outcomes.copy()
    df["proba"] = calibrated_proba
    df["size_fraction"] = fractional_kelly_size(df["proba"].to_numpy(), payoff_ratio_b, kelly_fraction_mult,
                                                 risk_limits.max_position_pct)

    dates_sorted = sorted(df["date"].unique())
    date_to_idx = {d: i for i, d in enumerate(dates_sorted)}
    cost = cost_as_return(cost_bps)

    trades: list[Trade] = []
    daily_pnl = {d: 0.0 for d in dates_sorted}
    daily_exposure_used = {d: 0.0 for d in dates_sorted}  # exposure consumed by positions opened that day, held for `exit_day` days

    n_blocked_cb = n_blocked_risk = n_blocked_conviction = 0

    grouped = {d: g.sort_values("proba", ascending=False) for d, g in df.groupby("date")}

    for date in dates_sorted:
        day_candidates = grouped.get(date, df.iloc[0:0])
        tier = breaker_tier_by_date.get(date, "armed")
        current_exposure = daily_exposure_used[date]  # exposure already committed by earlier-entered, still-open positions
        daily_realized_pnl_pct = 0.0  # running P&L for THIS day's daily-loss check, resets each day per Part E2

        for _, row in day_candidates.iterrows():
            if row["size_fraction"] <= 0 or row["proba"] < min_conviction_proba:
                n_blocked_conviction += 1
                continue
            if tier != "armed":
                n_blocked_cb += 1
                continue
            check = check_risk_limits(row["size_fraction"], current_exposure, daily_realized_pnl_pct, risk_limits)
            if not check.allowed:
                n_blocked_risk += 1
                continue

            net_return = row["realized_return"] - cost
            pnl_contribution = row["size_fraction"] * net_return
            current_exposure += row["size_fraction"]

            trades.append(Trade(
                entry_date=date, exit_date_offset=int(row["exit_day"]), ticker=row["ticker"],
                direction=int(np.sign(row["signal"])), size_fraction=float(row["size_fraction"]),
                gross_return=float(row["realized_return"]), net_return=float(net_return),
                pnl_contribution=float(pnl_contribution),
            ))

            base_idx = date_to_idx[date]
            exit_idx = base_idx + int(row["exit_day"])
            if exit_idx < len(dates_sorted):
                exit_date = dates_sorted[exit_idx]
                daily_pnl[exit_date] = daily_pnl.get(exit_date, 0.0) + pnl_contribution
            for k in range(1, int(row["exit_day"]) + 1):
                idx = base_idx + k
                if idx < len(dates_sorted):
                    daily_exposure_used[dates_sorted[idx]] = daily_exposure_used.get(dates_sorted[idx], 0.0) + row["size_fraction"]

    daily_returns = pd.Series({d: daily_pnl.get(d, 0.0) for d in dates_sorted}).sort_index()
    nav = (1 + daily_returns).cumprod()

    logger.info(f"backtest: {len(trades)} trades executed, {n_blocked_cb} blocked by circuit breaker, "
                f"{n_blocked_risk} blocked by risk limits, {n_blocked_conviction} blocked by low conviction")

    return BacktestResult(
        daily_nav=nav, daily_returns=daily_returns, trades=trades, n_trades=len(trades),
        n_candidates=len(df), n_blocked_by_circuit_breaker=n_blocked_cb,
        n_blocked_by_risk_limits=n_blocked_risk, n_blocked_by_no_conviction=n_blocked_conviction,
    )
