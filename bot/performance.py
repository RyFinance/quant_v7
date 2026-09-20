"""Daily mark-to-market NAV of the paper account, and the T-bill rate its
excess returns are measured against.

Why this exists: PaperExecutionClient.nav() is cash-basis -- starting capital
plus realised P&L, open positions carried at cost. A return series built on it
moves only on exit days, so it is autocorrelated and understates volatility,
and with the risk-free rate at 0 the reported Sharpe came out about twice the
true one (reports/pead_audit/REPORT.md: 1.34-1.44 reported, about 0.70 marked
daily in excess of T-bills). Every Sharpe the bot reports -- the dashboard and
live_backtest/compute_final_metrics.py -- is computed from the series built
here instead. nav() itself is unchanged: position sizing and the risk gate
still use it (see its docstring).

Marked NAV on day D = cash + every open position at its latest close on or
before D, which is the cash-basis NAV plus each open position's unrealised P&L
at that close. Conventions:
  * Unrealised P&L uses close_position's gross formula, so closing a position
    at its mark realises exactly the P&L it was last marked at.
  * The 10 bps round trip is charged at the close (execution.py), so an open
    position is marked gross of it: the marked NAV steps down by that cost on
    the exit day and equals the cash-basis NAV once every position is closed.
  * A position is never marked with a price dated before its entry. With no
    usable price it is carried at cost; with only an older one, that price is
    carried forward. Either way the day counts as a stale mark.
  * Idle cash earns nothing, exactly as in the paper account. Excess returns
    over T-bills therefore include the drag of uninvested cash (the audit's
    0.70 benchmark credits idle cash with the T-bill rate; this does not).

Risk-free rate: the Ken French daily RF column (1-month T-bill, simple daily
rate), cached at reports/higher_sharpe/inputs/french_daily.zip and read with
research.options_signals.signals.french_daily. The file is published monthly
with a lag, so days after its last date carry the last published rate
forward, the same rule research.options_signals.signals.rate_series uses. It
is quoted to 0.01% a day, so a single month's rate can be off by up to about
1.3% a year.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.metrics import BacktestMetrics, compute_metrics
from bot.execution import unrealized_pnl


@dataclass
class LedgerTrade:
    ticker: str
    direction: str
    entry_date: pd.Timestamp | None
    entry_price: float | None
    notional: float
    exit_date: pd.Timestamp | None = None
    realized_pnl: float | None = None


def _day(value) -> pd.Timestamp | None:
    return pd.Timestamp(value).normalize() if value else None


def read_jsonl(path: Path) -> list[dict]:
    """Every parseable line of a JSONL file; [] when the file is missing."""
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def ledger_trades(records: Iterable[dict]) -> list[LedgerTrade]:
    """One LedgerTrade per open, in ledger order. Each close is matched to the
    most recent unmatched open of its ticker (a ticker is never open twice at
    once -- place_order refuses). A close with no open still carries its
    realised P&L, as it does in PaperExecutionClient.from_ledger."""
    trades: list[LedgerTrade] = []
    open_by_ticker: dict[str, LedgerTrade] = {}
    for record in records:
        event = record.get("event")
        if event == "open":
            trade = LedgerTrade(
                ticker=record["ticker"], direction=record["direction"], entry_date=_day(record.get("entry_date")),
                entry_price=float(record["fill_price"]), notional=float(record["notional"]),
            )
            trades.append(trade)
            open_by_ticker[trade.ticker] = trade
        elif event == "close":
            trade = open_by_ticker.pop(record.get("ticker"), None)
            if trade is None:
                trade = LedgerTrade(ticker=record.get("ticker"), direction=record.get("direction"), entry_date=None,
                                    entry_price=None, notional=float(record.get("notional") or 0.0))
                trades.append(trade)
            trade.exit_date = _day(record.get("exit_date"))
            trade.realized_pnl = float(record.get("realized_pnl") or 0.0)
    return trades


def _clean_prices(closes: pd.DataFrame) -> pd.DataFrame:
    closes = closes.copy()
    closes.index = pd.DatetimeIndex(pd.to_datetime(closes.index)).normalize()
    return closes[~closes.index.duplicated(keep="last")].sort_index()


def daily_marked_nav(records: Iterable[dict], closes: pd.DataFrame, calendar, starting_capital: float) -> pd.DataFrame:
    """Rebuild the account day by day from its ledger.

    `closes` is a date x ticker frame of closing prices (NaN where there is
    none). Returns one row per `calendar` day with the end-of-day
    cash_basis_nav (what nav() reported), marked_nav, unrealized_pnl,
    open_positions and stale_marks (open positions marked with a price older
    than that day, or carried at cost)."""
    cal = pd.DatetimeIndex(pd.to_datetime(calendar)).normalize().unique().sort_values()
    closes = _clean_prices(closes) if len(closes.columns) else closes
    realized = np.zeros(len(cal))
    unrealized = np.zeros(len(cal))
    n_open = np.zeros(len(cal), dtype=int)
    stale = np.zeros(len(cal), dtype=int)

    for trade in ledger_trades(records):
        if trade.realized_pnl is not None:
            realized[cal >= trade.exit_date if trade.exit_date is not None else slice(None)] += trade.realized_pnl
        if trade.entry_date is None or not trade.entry_price:
            continue
        held = cal >= trade.entry_date
        if trade.exit_date is not None:
            held &= cal < trade.exit_date
        if not held.any():
            continue
        days = cal[held]
        px = closes[trade.ticker].dropna() if trade.ticker in closes.columns \
            else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        px = px[px.index >= trade.entry_date]
        if len(px):
            i = px.index.searchsorted(days, side="right") - 1
            found = i >= 0
            j = np.clip(i, 0, None)
            mark = np.where(found, px.to_numpy()[j], trade.entry_price)
            fresh = found & (px.index.to_numpy()[j] == days.to_numpy())
        else:
            mark = np.full(len(days), trade.entry_price)
            fresh = np.zeros(len(days), dtype=bool)
        unrealized[held] += unrealized_pnl(trade.direction, trade.notional, trade.entry_price, mark)
        n_open[held] += 1
        stale[held] += (~fresh).astype(int)

    cash_basis = starting_capital + realized
    return pd.DataFrame({
        "cash_basis_nav": cash_basis, "marked_nav": cash_basis + unrealized, "unrealized_pnl": unrealized,
        "open_positions": n_open, "stale_marks": stale,
    }, index=cal)


_CLOSES: dict[Path, tuple[tuple[int, int], pd.Series]] = {}


def cached_closes(tickers: Iterable[str], price_dir: Path) -> pd.DataFrame:
    """Daily closes from the parquet bar cache (data/raw), date x ticker.
    Tickers with no cache file are left out. Each file is parsed once per
    modification (the dashboard asks every poll)."""
    series = {}
    for ticker in sorted(set(tickers)):
        path = price_dir / f"{ticker}.parquet"
        try:
            stat = path.stat()
        except OSError:
            continue
        key = (stat.st_mtime_ns, stat.st_size)
        hit = _CLOSES.get(path)
        if hit is None or hit[0] != key:
            try:
                bars = pd.read_parquet(path, columns=["timestamp", "close"]).dropna()
            except (OSError, ValueError):
                continue
            s = bars.set_index(pd.to_datetime(bars["timestamp"]).dt.normalize())["close"].astype(float)
            hit = (key, s[~s.index.duplicated(keep="last")])
            _CLOSES[path] = hit
        series[ticker] = hit[1]
    return pd.DataFrame(series).sort_index()


def recorded_marks(cycle_records: Iterable[dict]) -> pd.DataFrame:
    """The per-position prices run_cycle recorded ("marks"), date x ticker.
    When a day was run more than once, the latest run wins."""
    rows: dict[pd.Timestamp, dict[str, float]] = {}
    for record in sorted(cycle_records, key=lambda r: r.get("ts", 0.0)):
        marks = record.get("marks")
        if not marks or record.get("session_open") is False or not record.get("as_of_date"):
            continue
        rows[_day(record["as_of_date"])] = {t: float(p) for t, p in marks.items()}
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame.from_dict(rows, orient="index").sort_index()


def price_panel(cached: pd.DataFrame, recorded: pd.DataFrame) -> pd.DataFrame:
    """Recorded marks where the bot took one, cached closes elsewhere."""
    if recorded.empty:
        return _clean_prices(cached) if len(cached.columns) else cached
    if cached.empty:
        return _clean_prices(recorded)
    return _clean_prices(recorded).combine_first(_clean_prices(cached))


_FRENCH_RF: dict[float, pd.Series] = {}


def _french_rf() -> pd.Series:
    from research.options_signals.signals import FRENCH, french_daily

    key = FRENCH.stat().st_mtime
    if key not in _FRENCH_RF:
        _FRENCH_RF.clear()
        _FRENCH_RF[key] = french_daily()["rf"].sort_index()
    return _FRENCH_RF[key]


def risk_free_last_published() -> pd.Timestamp:
    """Last day the cached French file has a rate for."""
    return _french_rf().index.max()


def daily_risk_free(calendar) -> pd.Series:
    """Simple daily T-bill return on each calendar day; the last published
    rate is carried forward past the file's end. Raises if a day precedes the
    file."""
    cal = pd.DatetimeIndex(pd.to_datetime(calendar)).normalize()
    rf = _french_rf()
    out = rf.reindex(cal.union(rf.index)).ffill().reindex(cal)
    if out.isna().any():
        raise ValueError(f"no T-bill rate on or before {out[out.isna()].index[0].date()}")
    out.index = pd.DatetimeIndex(calendar)
    return out.rename("rf")


def daily_returns(nav: pd.Series, starting_capital: float) -> pd.Series:
    """Simple daily returns of a NAV series; the first day is measured from
    starting capital."""
    nav = nav.sort_index().astype(float)
    if nav.empty:
        return nav
    previous = nav.shift(1)
    previous.iloc[0] = starting_capital
    return nav / previous - 1.0


def excess_metrics(nav: pd.Series, starting_capital: float, n_trades: int,
                   avg_position_size: float = 0.0) -> tuple[BacktestMetrics, pd.Series, pd.Series]:
    """compute_metrics on a daily NAV series with Sharpe and Sortino taken in
    excess of the daily T-bill rate. Returns (metrics, returns, rf)."""
    returns = daily_returns(nav, starting_capital)
    rf = daily_risk_free(returns.index)
    return compute_metrics(returns, n_trades, avg_position_size, daily_risk_free=rf), returns, rf
