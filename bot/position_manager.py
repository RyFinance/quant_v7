"""Manages open paper positions through the SAME fixed holding period the
validated PEAD backtest used.

reports/run_pead_backtest.py is explicit that PEAD's backtest deliberately
does NOT use adaptive TP/SL (risk/adaptive_exits.py, built for the
abandoned mean-reversion strategy's cluster-relative statistics, has no
PEAD equivalent -- see that file's own docstring). Positions are held the
full `earnings.labeling.HOLDING_PERIOD_DAYS` (20 trading days) and exited
at the end of that window. Inventing a different exit rule here (a trailing
stop, a vol-scaled TP, anything reactive to price) would NOT be backed by
the validated backtest and would silently change the strategy this bot is
supposed to be paper-trading. So: no adaptive exit logic exists in this
module, on purpose.

Trading-day counting uses a business-day approximation (pandas bdate_range),
the same simplification quality/monitor.py already uses and documents for
gap detection -- exact NYSE holiday-awareness would need
pandas_market_calendars, not worth the dependency for this scaffolding.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from earnings.labeling import HOLDING_PERIOD_DAYS

from bot.execution import PaperExecutionClient


def trading_days_elapsed(entry_date: str, as_of_date: str) -> int:
    """Business-day count between entry_date and as_of_date, inclusive of
    as_of_date, exclusive of entry_date (so same-day = 0 elapsed)."""
    entry = pd.Timestamp(entry_date).normalize()
    as_of = pd.Timestamp(as_of_date).normalize()
    if as_of <= entry:
        return 0
    return len(pd.bdate_range(entry + pd.Timedelta(days=1), as_of))


@dataclass
class ExitResult:
    ticker: str
    entry_date: str
    exit_date: str
    days_held: int
    realized_pnl: float


class PositionManager:
    """Thin wrapper around a PaperExecutionClient's position book. Owns only
    the "when does an open position's fixed holding period end" decision --
    it does not size, does not gate, does not choose entries. Those are
    risk_gate.py and signal_pipeline.py's jobs respectively."""

    def __init__(self, holding_period_days: int = HOLDING_PERIOD_DAYS):
        self.holding_period_days = holding_period_days

    def due_for_exit(self, execution_client: PaperExecutionClient, as_of_date: str) -> list[str]:
        """Tickers whose open position has reached (or passed) the fixed
        holding period as of `as_of_date`."""
        due = []
        for ticker, position in execution_client.positions.items():
            if not position.open:
                continue
            elapsed = trading_days_elapsed(position.entry_date, as_of_date)
            if elapsed >= self.holding_period_days:
                due.append(ticker)
        return due

    def process_exits(self, execution_client: PaperExecutionClient, as_of_date: str) -> list[ExitResult]:
        """Close every position whose holding period has elapsed, via the
        execution client's REAL current-price fill (see execution.py).
        Returns one ExitResult per closed position."""
        results = []
        for ticker in self.due_for_exit(execution_client, as_of_date):
            position = execution_client.positions[ticker]
            entry_date = position.entry_date
            days_held = trading_days_elapsed(entry_date, as_of_date)
            pnl = execution_client.close_position(ticker, exit_date=as_of_date, reason="holding_period_exit")
            results.append(ExitResult(
                ticker=ticker, entry_date=entry_date, exit_date=as_of_date,
                days_held=days_held, realized_pnl=pnl,
            ))
        return results
