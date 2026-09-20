"""Item 4: backtest the LIVE CODE PATH (bot/run_cycle.py, unmodified) against
pinned historical data. Every day in the replay window calls the real
`run_cycle()` function -- real risk_gate.evaluate(), real
PaperExecutionClient/ledger writes, real PositionManager holding-period
exits, real heartbeat touch -- with ONLY the underlying live data calls
swapped for pinned-historical equivalents (live_backtest/historical_providers.py)
via monkeypatching, the same technique this project's own tests already use.

REPLAY WINDOW: exactly the out-of-sample holdout window
(holdout_a+b+c) the CACHED model (bot/state/model/pead_model_expanded.joblib)
was validated on -- i.e. dates strictly AFTER the train+validation cutoff
that same model was fit on (recomputed fresh here via the identical
split_time_disjoint_panel call fit_or_load() itself uses, not assumed from
memory, so this can't silently drift out of sync with the real cached
model). Replaying over the TRAINING window would be in-sample and
meaningless; this replay window is the same one
reports/run_pead_expanded_validation.py already validated the raw signal
against -- this run instead validates the ORCHESTRATION code on top of it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from loguru import logger

import bot.execution as execution_module
import bot.risk_gate as risk_gate_module
import bot.earnings_watcher as earnings_watcher_module
import bot.kill_switch as kill_switch_module
import bot.heartbeat as heartbeat_module
import bot.run_cycle as run_cycle_module
import bot.signal_pipeline as signal_pipeline_module
from bot.execution import PaperExecutionClient
from bot.position_manager import PositionManager
from earnings.labeling import HOLDING_PERIOD_DAYS
from ml.validation import split_time_disjoint_panel

from live_backtest.historical_providers import (
    historical_breaker_tier,
    historical_close_price,
    historical_earnings_history_for_sue,
    historical_recently_reported,
    historical_trailing_return,
)

DATA_DIR = Path(__file__).parent.parent / "data"
REPORTS_DIR = Path(__file__).parent.parent / "reports"
REPLAY_STATE_DIR = REPORTS_DIR.parent / "live_backtest" / "state"
REPLAY_LEDGER = REPLAY_STATE_DIR / "replay_ledger.jsonl"
REPLAY_CYCLE_LOG = REPLAY_STATE_DIR / "replay_cycle_log.jsonl"
REPLAY_KILL_SWITCH = REPLAY_STATE_DIR / "REPLAY_KILL_SWITCH"  # deliberately NEVER bot/state/KILL_SWITCH
REPLAY_HEARTBEAT = REPLAY_STATE_DIR / "replay_heartbeat.txt"  # deliberately NEVER bot/state/heartbeat.txt
REPLAY_ALERTS = REPLAY_STATE_DIR / "replay_alerts.jsonl"
PRIMARY_LABEL = "label_cost_adjusted"


def compute_replay_window() -> tuple[pd.Timestamp, pd.Timestamp]:
    """Recomputed fresh from the CURRENT data file (not hardcoded), so the
    boundary itself can't drift from a stale assumption.

    DOCUMENTED LIMITATION (softened from an earlier overclaim -- found by
    adversarial review): recomputing this fresh only guarantees the
    boundary matches CURRENT data. It does NOT, by itself, guarantee the
    CACHED model (bot/state/model/pead_model_expanded.joblib) was fit on
    that same current data -- fit_or_load() has no provenance check, it
    unconditionally trusts MODEL_PATH.exists(). If
    data/pead_labeled_features_expanded.parquet were ever regenerated
    (e.g. reports/run_pead_expanded_pipeline.py rerun) WITHOUT also
    deleting the cached joblib to force a refit, this function's freshly
    computed boundary could silently diverge from the boundary the STALE
    cached model was actually fit on -- a real train-into-holdout leak
    risk, not just a cosmetic mismatch. The mtime check below is a
    lightweight, real (not just asserted) guard against exactly that
    scenario -- it does not prove correctness, but it does catch the
    concrete "data file regenerated after the model was last fit" case."""
    data_path = DATA_DIR / "pead_labeled_features_expanded.parquet"
    df = pd.read_parquet(data_path)
    parts, partitions = split_time_disjoint_panel(df, holding_period=20, min_rows_per_partition=100)
    holdout_a = next(p for p in partitions if p.name == "holdout_a")
    holdout_c = next(p for p in partitions if p.name == "holdout_c")
    start = pd.Timestamp(holdout_a.start)
    end = pd.Timestamp(holdout_c.end)
    logger.info(f"replay window (out-of-sample for the cached model): {start.date()} -> {end.date()}")

    model_path = signal_pipeline_module.MODEL_PATH
    if model_path.exists() and data_path.stat().st_mtime > model_path.stat().st_mtime:
        raise RuntimeError(
            f"{data_path} was modified AFTER {model_path} was cached -- the cached model may have been "
            f"fit on different (older) data than this function just computed the replay window against. "
            f"Delete {model_path} and let fit_or_load() refit on the current data before running a replay."
        )
    return start, end


def get_trading_dates(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    breaker_df = pd.read_csv(REPORTS_DIR / "circuit_breaker_daily_production.csv", parse_dates=["date"])
    dates = breaker_df[(breaker_df["date"] >= start) & (breaker_df["date"] <= end)]["date"].sort_values()
    return list(dates)


def install_historical_monkeypatches(as_of_holder: dict):
    """Patches every live-data call bot/run_cycle.py's real code path makes,
    routed through a mutable `as_of_holder` dict so a single set of patches
    can be installed once and simply have `as_of_holder["date"]` updated
    each simulated day, rather than re-patching every iteration.

    ALSO isolates every piece of PRODUCTION STATE the real path touches
    (kill-switch sentinel file, heartbeat file, alerts log) to
    live_backtest/state/ paths -- critically, this replay's own simulated
    NAV genuinely can breach the drawdown cap and genuinely engage ITS OWN
    kill switch (that mechanism is real state evolving from real replayed
    trades, not something to fake), but that must NEVER be able to write
    to bot/state/KILL_SWITCH, the REAL production bot's sentinel file. A
    version of this harness without this isolation would risk a historical
    replay accidentally halting the live, real, currently-scheduled bot.
    """
    import bot.alerting as bot_alerting_module
    from bot.alerting import BotAlerter

    def patched_get_current_price(ticker: str) -> float:
        return historical_close_price(ticker, as_of_holder["date"])

    def patched_current_breaker_tier(lookback_days: int = 60, universe_tickers=None):
        return historical_breaker_tier(as_of_holder["date"])

    def patched_get_recently_reported(self, days_back: int = 3, now=None):
        return historical_recently_reported(self.tickers, as_of_holder["date"], days_back=days_back)

    def patched_fetch_ticker_earnings_live(ticker: str):
        return historical_earnings_history_for_sue(ticker, as_of_holder["date"])

    def patched_trailing_return(ticker: str, window_days: int, as_of: pd.Timestamp):
        return historical_trailing_return(ticker, window_days, as_of)

    def patched_build_alerter():
        return BotAlerter(webhook_url="", alerts_path=REPLAY_ALERTS)

    execution_module.get_current_price = patched_get_current_price
    risk_gate_module.current_breaker_tier = patched_current_breaker_tier
    run_cycle_module.current_breaker_tier = patched_current_breaker_tier
    earnings_watcher_module.EarningsWatcher.get_recently_reported = patched_get_recently_reported
    # Replay days are pinned historical trading days: no live price refresh
    # (which would write data/raw), no staleness alarm for a patched feed.
    run_cycle_module.prepare_market_session = lambda tickers, as_of: (True, "replay: pinned historical trading day")
    earnings_watcher_module.EarningsWatcher.feed_looks_stale = lambda self, now=None: False
    signal_pipeline_module.fetch_ticker_earnings_live = patched_fetch_ticker_earnings_live
    signal_pipeline_module._trailing_return = patched_trailing_return

    # -- production-state isolation (see docstring) --
    # risk_gate.py imports is_kill_switch_engaged/engage_kill_switch as
    # FUNCTIONS (not the KILL_SWITCH_FILE constant itself), and those
    # functions look up KILL_SWITCH_FILE as a global inside bot.kill_switch's
    # OWN namespace at call time -- so patching it there is sufficient;
    # there is no separate binding in risk_gate_module to also patch.
    kill_switch_module.KILL_SWITCH_FILE = REPLAY_KILL_SWITCH
    # Also isolate STATE_DIR (bot/kill_switch.py's engage_kill_switch calls
    # STATE_DIR.mkdir(parents=True, exist_ok=True) before writing the file) --
    # currently a no-op in production since bot/state/ already exists, but
    # leaving it unpatched means a real filesystem call against the
    # production directory executes from this harness whenever a simulated
    # drawdown trips the kill switch, contradicting this function's own
    # "must NEVER touch bot/state/" intent. Found by adversarial review.
    kill_switch_module.STATE_DIR = REPLAY_STATE_DIR
    heartbeat_module.HEARTBEAT_FILE = REPLAY_HEARTBEAT
    run_cycle_module.touch_heartbeat = lambda: heartbeat_module.touch_heartbeat(REPLAY_HEARTBEAT)
    bot_alerting_module.build_alerter = patched_build_alerter
    risk_gate_module.build_alerter = patched_build_alerter
    execution_module.build_alerter = patched_build_alerter
    run_cycle_module.build_alerter = patched_build_alerter
    run_cycle_module.UPCOMING_EARNINGS_FILE = REPLAY_STATE_DIR / "replay_upcoming_earnings.json"


def run_replay(force_fresh: bool = True) -> dict:
    REPLAY_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    if force_fresh:
        REPLAY_LEDGER.unlink(missing_ok=True)
        REPLAY_CYCLE_LOG.unlink(missing_ok=True)

    start, end = compute_replay_window()
    dates = get_trading_dates(start, end)
    logger.info(f"replaying {len(dates)} real trading days through the live run_cycle() code path")

    as_of_holder = {"date": dates[0]}
    install_historical_monkeypatches(as_of_holder)
    # fit_or_load() caches to disk keyed by a fixed path (bot/state/model/
    # pead_model_expanded.joblib -- the REAL production model the live bot
    # loads) -- reuse the SAME cached model the real live bot uses (already
    # fit on train+validation only, per compute_replay_window's docstring)
    # rather than refitting. REFUSE to be the one to CREATE that cache: if
    # it's missing, fit_or_load()'s cache-miss branch would fit fresh AND
    # joblib.dump the result to that production path -- since ensemble
    # fitting isn't guaranteed bit-identical across runs, this replay
    # harness would then silently determine which model weights the real
    # live bot trades real (paper) capital against next, with no human in
    # the loop. Found by adversarial review; fail loudly instead.
    if not signal_pipeline_module.MODEL_PATH.exists():
        raise RuntimeError(
            f"refusing to run the historical replay: {signal_pipeline_module.MODEL_PATH} does not exist. "
            f"This harness must never be the one to fit and cache the production model -- run the real bot "
            f"(python3 -m bot.run_cycle) or bot.signal_pipeline.fit_or_load() directly first, outside this "
            f"replay, so the cache is created deliberately and not as a side effect of a backtest."
        )
    pipeline = signal_pipeline_module.fit_or_load()
    cached_pipeline_getter = lambda force_refit=False: pipeline  # avoid re-loading from disk every single day
    signal_pipeline_module.fit_or_load = cached_pipeline_getter
    run_cycle_module.fit_or_load = cached_pipeline_getter  # run_cycle imported the name via `from ... import`, separate binding

    run_cycle_module.CYCLE_LOG_FILE = REPLAY_CYCLE_LOG

    reports = []
    for i, date in enumerate(dates):
        as_of_holder["date"] = date
        report = run_cycle_module.run_cycle(as_of_date=str(date.date()), ledger_path=REPLAY_LEDGER)
        reports.append(report)
        if (i + 1) % 100 == 0:
            logger.info(f"[{i+1}/{len(dates)}] {date.date()}: nav={report.nav_after:.2f}")

    final_nav = reports[-1].nav_after if reports else None
    logger.info(f"replay complete: {len(dates)} days, final NAV={final_nav}")
    return {
        "n_days_replayed": len(dates), "start": str(start.date()), "end": str(end.date()),
        "final_nav": final_nav, "ledger_path": str(REPLAY_LEDGER), "cycle_log_path": str(REPLAY_CYCLE_LOG),
    }


if __name__ == "__main__":
    summary = run_replay()
    print(json.dumps(summary, indent=2, default=str))
