"""Execution clients.

Judgment call from the polymarket_arb read-through (see bot/PLAN.md): the
CLOB order-book / dual-leg-fill model in polymarket_arb/execution.py does
NOT transfer -- there is no "combined YES+NO ask" concept for a single-name
equity long/short PEAD trade, no partial-fill hedge-or-exit dance across
two legs of the SAME trade. What DOES transfer is the *shape* of a
broker-API-style execution-client abstraction with an explicit paper vs.
live split, exactly like polymarket_arb/config.py's `dry_run` /
`paper_trade` / `live` distinction and
polymarket_arb/clients/trading_client.py's PAPER_TRADE fill simulation
(walk a REST book to a synthetic fill, log identically to a real fill).
Here there is no order book to walk -- equities paper-fills are simulated
against the last real trade price instead.

`PaperExecutionClient` is a working simulator: it fetches a REAL current
price via yfinance for the requested ticker and "fills" the order
immediately at that price (no book, no slippage model -- documented
simplification, see class docstring). `LiveExecutionClient` is an explicit
NotImplementedError stub; see its docstring for why it will stay that way
until a human takes the go-live step described in bot/PLAN.md.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal

import yfinance as yf

from risk.transaction_costs import ROUND_TRIP_COST_BPS_DEFAULT

from bot.alerting import ALERT_POSITION_CLOSED, ALERT_POSITION_OPENED, BotAlerter, build_alerter
from bot.risk_gate import RiskGateDecision, consume_approval

STATE_DIR = Path(__file__).parent / "state"
LEDGER_FILE = STATE_DIR / "paper_ledger.jsonl"

Direction = Literal["long", "short"]


def get_current_price(ticker: str) -> float:
    """Real current (or most-recent-close) price via yfinance. No network
    mocking, no synthetic fallback -- if yfinance has nothing, this raises,
    and the caller must not fabricate a fill price."""
    t = yf.Ticker(ticker)
    price = None
    try:
        fi = t.fast_info
        price = float(fi.get("lastPrice") if hasattr(fi, "get") else fi.last_price)
    except Exception:
        price = None
    if price is None or math.isnan(price) or price <= 0:
        hist = t.history(period="5d", interval="1d")
        if hist.empty:
            raise RuntimeError(f"no real price data available for {ticker!r} (yfinance returned nothing)")
        price = float(hist["Close"].iloc[-1])
    return price


@dataclass
class PaperPosition:
    ticker: str
    direction: Direction
    entry_price: float
    entry_date: str  # ISO date the position was opened
    size_fraction: float  # fraction of paper NAV committed at entry
    notional: float
    open: bool = True
    exit_price: float | None = None
    exit_date: str | None = None
    realized_pnl: float | None = None


def unrealized_pnl(direction: Direction, notional, entry_price, mark):
    """P&L of an open position if it were closed at `mark`, before the exit
    cost -- close_position's gross formula, term for term. Works on floats or
    numpy arrays of marks."""
    sign = 1.0 if direction == "long" else -1.0
    pct_move = sign * (mark - entry_price) / entry_price
    return notional * pct_move


@dataclass
class MarkedNav:
    """Account value with open positions at their latest price, alongside the
    cash-basis nav() it extends."""
    nav: float
    cash_basis_nav: float
    unrealized_pnl: float
    marks: dict[str, float] = field(default_factory=dict)  # ticker -> price used
    unmarked: list[str] = field(default_factory=list)  # open, no price: carried at cost


@dataclass
class PaperFill:
    ticker: str
    direction: Direction
    fill_price: float
    size_fraction: float
    notional: float
    ts: float
    mode: str = "paper"


class PaperExecutionClient:
    """Simulates fills against REAL market data and tracks an in-memory +
    JSONL-persisted paper position/fill ledger. Never touches a real
    brokerage or exchange account -- there is no code path here that can.

    Simplification (documented, not silent): fills happen at the current
    real last-trade price with zero slippage/spread modeling. The validated
    PEAD backtest (reports/run_pead_backtest.py) also does not model
    execution slippage beyond a flat transaction-cost bps assumption, so
    this matches the fidelity level of the thing that was actually
    validated rather than inventing a fancier microstructure model this
    strategy was never backtested against.

    COSTS (added 2026-09-17): the round trip is charged on the CLOSE, against
    the entry and exit notionals, at risk/transaction_costs.py's 10 bps -- the
    same assumption the cost-adjusted training label and every research
    backtest in this repo already use. Before this, the paper account was the
    only thing here quoting returns gross of fees, which overstated it by
    roughly 0.4%/yr at the bot's current turnover. Charging at the close (not
    half at entry) keeps the invariant the whole system is built on: cash-basis
    NAV changes on a close event and nowhere else, so from_ledger, the
    dashboard's stats and its equity curve all stay correct without each
    re-deriving a cost model. An open position is therefore marked before its
    exit cost.
    """

    def __init__(
        self,
        starting_capital: float = 100_000.0,
        ledger_path: Path = LEDGER_FILE,
        alerter: BotAlerter | None = None,
        round_trip_cost_bps: float = ROUND_TRIP_COST_BPS_DEFAULT,
    ):
        self.round_trip_cost_bps = round_trip_cost_bps
        self.starting_capital = starting_capital
        self.cash = starting_capital
        self.realized_pnl = 0.0
        self.high_water_mark = starting_capital
        self.positions: dict[str, PaperPosition] = {}
        self._ledger_path = ledger_path
        self.alerter = alerter or build_alerter()

    # -- multi-process continuity ------------------------------------------
    @classmethod
    def from_ledger(
        cls,
        starting_capital: float = 100_000.0,
        ledger_path: Path = LEDGER_FILE,
        alerter: "BotAlerter | None" = None,
    ) -> "PaperExecutionClient":
        """Reconstruct a client's full state (open positions, realized P&L,
        high-water mark) by replaying `ledger_path` from scratch.

        Each cron-driven cycle of this bot is a FRESH Python process -- there
        is no long-lived in-memory PaperExecutionClient sitting between runs.
        The JSONL ledger `place_order`/`close_position` already write is the
        only durable record, so it doubles as an event log: replaying every
        "open" then "close" record in order reproduces exactly the state a
        continuously-running process would have. This is event-sourcing, not
        a new state file -- one less thing that can drift out of sync with
        the ledger itself.
        """
        client = cls(starting_capital=starting_capital, ledger_path=ledger_path, alerter=alerter)
        if not ledger_path.exists():
            return client

        with open(ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record["event"] == "open":
                    client.positions[record["ticker"]] = PaperPosition(
                        ticker=record["ticker"], direction=record["direction"],
                        entry_price=record["fill_price"], entry_date=record.get("entry_date", ""),
                        size_fraction=record["size_fraction"], notional=record["notional"], open=True,
                    )
                elif record["event"] == "close":
                    position = client.positions.get(record["ticker"])
                    if position is not None:
                        position.open = False
                        position.exit_price = record["exit_price"]
                        position.exit_date = record["exit_date"]
                        position.realized_pnl = record["realized_pnl"]
                    client.realized_pnl += record["realized_pnl"]
                    client.high_water_mark = max(client.high_water_mark, client.starting_capital + client.realized_pnl)
        return client

    # -- accounting -----------------------------------------------------
    def nav(self) -> float:
        """Cash-basis NAV: starting capital + realized P&L. Open positions
        are carried at cost (not marked-to-market intraday) -- consistent
        with the fixed-holding-period, no-adaptive-exit design (see
        position_manager.py / PLAN.md): nothing reacts to interim price
        moves, so there is no decision this bot makes that depends on a
        live mark, only the recorded entry and the eventual exit price.

        This is deliberately still the NAV that sizes and gates trades:
        place_order's notional, current_total_exposure_pct, the daily-loss
        check and the drawdown kill switch (with high_water_mark) all read it.
        Switching them to marked_nav() would change position sizes, when the
        exposure cap binds and when the kill switch trips -- i.e. the trades
        themselves. It is NOT a performance measure: a return series built on
        it moves only on exit days, is autocorrelated and understates
        volatility (reports/pead_audit/REPORT.md). Performance is measured on
        marked_nav(), recorded every session by run_cycle, via
        bot/performance.py."""
        return self.starting_capital + self.realized_pnl

    def marked_nav(self, price_for: Callable[[str], float] | None = None) -> MarkedNav:
        """Cash plus every open position at its latest price: nav() plus each
        position's unrealized_pnl. `price_for` defaults to get_current_price,
        the same source fills use (the session's close when run_cycle calls
        this after the close; the pinned close in the historical replays,
        which patch this module's get_current_price). A position whose price
        cannot be fetched is carried at cost and listed in `unmarked` --
        marking never raises. Read-only: changes no state and no ledger."""
        price_for = price_for or get_current_price
        marks: dict[str, float] = {}
        unmarked: list[str] = []
        unrealized = 0.0
        for ticker, position in self.positions.items():
            if not position.open:
                continue
            try:
                price = float(price_for(ticker))
            except Exception:
                price = float("nan")
            if not math.isfinite(price) or price <= 0 or not position.entry_price:
                unmarked.append(ticker)
                continue
            marks[ticker] = price
            unrealized += unrealized_pnl(position.direction, position.notional, position.entry_price, price)
        cash_basis = self.nav()
        return MarkedNav(nav=cash_basis + unrealized, cash_basis_nav=cash_basis, unrealized_pnl=unrealized,
                         marks=marks, unmarked=sorted(unmarked))

    def current_total_exposure_pct(self) -> float:
        nav = self.nav()
        if nav <= 0:
            return 1.0
        return sum(p.notional for p in self.positions.values() if p.open) / nav

    def _append_ledger(self, record: dict) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())

    # -- orders -----------------------------------------------------------
    def place_order(
        self,
        ticker: str,
        direction: Direction,
        decision: RiskGateDecision,
        entry_date: str,
    ) -> PaperFill:
        """Requires a PASSING RiskGateDecision with a live approval token
        (see bot/risk_gate.py). The token is consumed here -- a decision
        object can only ever fund exactly one order, even if a caller tried
        to reuse it."""
        if not decision.allowed or not consume_approval(decision.approval_token):
            raise PermissionError(
                f"place_order for {ticker} rejected: no valid risk-gate approval "
                f"(reason={decision.reason}, detail={decision.detail!r})"
            )
        if ticker in self.positions and self.positions[ticker].open:
            raise ValueError(f"{ticker} already has an open paper position")

        price = get_current_price(ticker)
        notional = decision.size_fraction * self.nav()
        position = PaperPosition(
            ticker=ticker, direction=direction, entry_price=price, entry_date=entry_date,
            size_fraction=decision.size_fraction, notional=notional,
        )
        self.positions[ticker] = position
        fill = PaperFill(
            ticker=ticker, direction=direction, fill_price=price,
            size_fraction=decision.size_fraction, notional=notional, ts=time.time(),
        )
        self._append_ledger({"event": "open", "entry_date": entry_date, **asdict(fill)})
        self.alerter.alert(
            ALERT_POSITION_OPENED, f"paper position opened: {ticker} {direction} @ {price:.2f}",
            ticker=ticker, direction=direction, fill_price=price, notional=round(notional, 2),
        )
        return fill

    def close_position(self, ticker: str, exit_date: str, reason: str = "holding_period_exit") -> float:
        """Fetch a real current price and close the position at it. Returns
        realized P&L for this position (in dollars). Updates NAV/HWM."""
        position = self.positions.get(ticker)
        if position is None or not position.open:
            raise ValueError(f"no open paper position for {ticker}")

        exit_price = get_current_price(ticker)
        sign = 1.0 if position.direction == "long" else -1.0
        pct_move = sign * (exit_price - position.entry_price) / position.entry_price
        gross_pnl = position.notional * pct_move
        # One-way cost on each leg: entry notional plus the notional actually
        # sold/covered at the exit price.
        one_way = self.round_trip_cost_bps / 2 / 10_000.0
        exit_notional = position.notional * (exit_price / position.entry_price) if position.entry_price else position.notional
        cost = (position.notional + exit_notional) * one_way
        pnl = gross_pnl - cost

        position.open = False
        position.exit_price = exit_price
        position.exit_date = exit_date
        position.realized_pnl = pnl
        self.realized_pnl += pnl
        self.high_water_mark = max(self.high_water_mark, self.nav())

        self._append_ledger({
            "event": "close", "ticker": ticker, "direction": position.direction,
            "entry_price": position.entry_price, "exit_price": exit_price,
            "notional": position.notional, "realized_pnl": pnl, "reason": reason,
            "gross_pnl": gross_pnl, "cost": cost, "cost_bps_round_trip": self.round_trip_cost_bps,
            "exit_date": exit_date, "ts": time.time(),
        })
        self.alerter.alert(
            ALERT_POSITION_CLOSED,
            f"paper position closed: {ticker} pnl={pnl:.2f} net of {cost:.2f} costs ({reason})",
            ticker=ticker, exit_price=exit_price, realized_pnl=round(pnl, 2), cost=round(cost, 2), reason=reason,
        )
        return pnl


class LiveExecutionClient:
    """NOT IMPLEMENTED. Placing a real order against a real brokerage or
    exchange account is explicitly out of scope for this bot and for any
    agent (including Claude) acting autonomously on this codebase.

    Going live is a separate, explicit, HUMAN-DRIVEN step outside of any
    agent's autonomous action: it requires, at minimum, a real funded
    brokerage account, a broker API integration that this codebase does not
    contain, a human explicitly provisioning real credentials outside of
    any file this bot reads automatically, and a human explicitly flipping
    a switch this codebase does not define. See bot/PLAN.md's "what would
    be needed to go live" section (descriptive only). This class exists
    only so the execution-client abstraction is honest about having a paper
    and a live side, not to provide a live implementation.
    """

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError(
            "LiveExecutionClient is intentionally unimplemented. Going live requires "
            "a separate, explicit, human-driven step outside of any agent's autonomous "
            "action (real broker account + credentials + a human-flipped switch this "
            "codebase does not define) -- see bot/PLAN.md."
        )


def assert_paper_only_mode() -> None:
    """Runtime assertion that LiveExecutionClient is still an unimplemented
    stub. Callers that are about to report or act on a PAPER_TRADE mode
    label (e.g. the dashboard's bot-control panel) call this first, so that
    label can never silently go stale if a future change starts building
    out a live-order path. Raises RuntimeError (not AssertionError, so it
    survives `python -O`) if the invariant no longer holds -- callers must
    treat that as a hard stop, not a warning. Side-effect free either way:
    LiveExecutionClient.__init__ never does anything but raise, so calling
    this on every request is safe and cheap."""
    try:
        LiveExecutionClient()
    except NotImplementedError:
        return
    except Exception as exc:
        raise RuntimeError(
            f"paper-mode assertion failed: LiveExecutionClient() raised "
            f"{type(exc).__name__} instead of NotImplementedError -- refusing to "
            f"report or act on PAPER_TRADE mode until a human re-verifies no live-order "
            f"path has been wired up."
        ) from exc
    else:
        raise RuntimeError(
            "paper-mode assertion failed: LiveExecutionClient() did not raise -- it is "
            "no longer an unimplemented stub. Refusing to report or act on PAPER_TRADE "
            "mode until a human re-verifies no live-order path has been wired up."
        )
