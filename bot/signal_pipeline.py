"""earnings/sue.py -> earnings/features.py -> a loaded/fitted ML filter ->
calibrated probability, for a FRESH (just-reported) earnings event.

MODEL PERSISTENCE (documented choice): there is no model-persistence
(pickle/joblib save) anywhere in quant_v7 today -- every `reports/run_*.py`
script fits the ensemble + calibrator fresh, in-process, from cached
parquet, every time it runs. Re-fitting on every bot invocation would be
correct but slow (day-of-earnings decisions do not need sub-second
latency, unlike the polymarket_arb bot this project started from -- see
bot/PLAN.md's "what transfers" judgment). `fit_or_load()` therefore adds a
minimal joblib persistence layer: fit once, cache to
`bot/state/model/pead_model.joblib`, reuse until the cache is deleted or
`force_refit=True`. This is new, minimal, and scoped to this package --
it does not change how reports/run_pead_ml_filter.py or
reports/run_pead_backtest.py work.

LIVE-SCORING DEVIATION (documented, not silent): the historical feature
build (earnings/features.py::build_pead_feature_matrix) computes
pre_earnings_return_5d/20d from RESIDUAL (market-beta-stripped) returns via
clustering/residual_returns.py's cached panel. That panel is a Phase-1/2
batch artifact computed over the full historical universe; there is no live
residual-return pipeline running in this scaffolding. For a fresh event
this module instead computes a RAW (non-residualized) trailing return from
real recently-fetched prices (data.ingestion.fetch_ticker_history) as a
momentum proxy. This is a real, working number from real data, but it is
NOT the same feature distribution the model was trained on -- flagged
here, and again in bot/PLAN.md, as a gap a real deployment would need to
close (e.g. by running the Phase-1/2 residual-return pipeline on a
schedule) before trusting this signal's probabilities at face value.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from loguru import logger

from data.ingestion import fetch_ticker_history
from earnings.features import PEAD_FEATURE_COLUMNS
from earnings.ingestion import fetch_ticker_earnings_live
from earnings.sue import SURPRISE_PCT_WINSOR_LIMIT, compute_sue
from ml.calibration import Calibrator, select_and_fit_calibrator
from ml.ensemble import FittedEnsemble, fit_weighted_ensemble
from ml.validation import split_time_disjoint_panel
from risk.kelly import PayoffRatio, estimate_payoff_ratio

from bot.earnings_watcher import ReportedEarnings

DATA_DIR = Path(__file__).parent.parent / "data"
REPORTS_DIR = Path(__file__).parent.parent / "reports"
MODEL_DIR = Path(__file__).parent / "state" / "model"
# Named _expanded so a stale small-sample-fit cache (from before the
# statistical re-validation) can never be silently reloaded -- a different
# training set gets a different cache file, not a quietly overwritten one.
MODEL_PATH = MODEL_DIR / "pead_model_expanded.joblib"

PRIMARY_LABEL = "label_cost_adjusted"
# Calendar days of history fetched to derive the 5d/20d trailing returns. Was 30,
# which is only ~20 trading days: any holiday in the window left too few bars and
# the event was silently skipped (17 of 72 reports in the 2026-07/09 season). The
# returns themselves always use the last 6/21 closes, so a wider fetch does not
# change their values.
MOMENTUM_LOOKBACK_DAYS = 45


@dataclass
class FittedPipeline:
    ensemble: FittedEnsemble
    calibrator: Calibrator
    payoff: PayoffRatio


def fit_or_load(force_refit: bool = False) -> FittedPipeline:
    """Fit the same D1-D4-rigor ensemble + calibrator + Kelly payoff ratio
    reports/run_pead_expanded_validation.py fits, from the SAME cached
    labeled dataset, OR load a previously fitted copy from bot/state/model/.

    Trains on data/pead_labeled_features_expanded.parquet -- the full
    503-ticker, ~18,700-event dataset that actually passed statistical
    validation (bootstrap CIs excluding zero + permutation p<0.05 on 2 of 3
    holdouts, 4/4 positive walk-forward years; see
    reports/PEAD_REVALIDATION_REPORT.md). The ORIGINAL 75-name dataset
    (data/pead_labeled_features.parquet) is deliberately NOT used here --
    its bootstrap CIs comfortably included zero on every holdout, i.e. it
    did not clear the bar this bot is supposed to be trading against.
    The TRADED universe stays the 75 liquid names (earnings_watcher.py) --
    only the fitted model's training data changed, not which tickers the
    bot watches."""
    if not force_refit and MODEL_PATH.exists():
        logger.info(f"loading cached PEAD model from {MODEL_PATH}")
        return joblib.load(MODEL_PATH)

    df = pd.read_parquet(DATA_DIR / "pead_labeled_features_expanded.parquet")
    parts, _ = split_time_disjoint_panel(df, holding_period=20, min_rows_per_partition=100)
    ensemble = fit_weighted_ensemble(parts, PEAD_FEATURE_COLUMNS, PRIMARY_LABEL)
    calibrator = select_and_fit_calibrator(ensemble, parts["validation"], PRIMARY_LABEL)
    payoff = estimate_payoff_ratio(parts["train"], PRIMARY_LABEL)

    pipeline = FittedPipeline(ensemble=ensemble, calibrator=calibrator, payoff=payoff)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH)
    logger.info(f"fit fresh PEAD model (payoff.b={payoff.b:.4f}), cached to {MODEL_PATH}")
    return pipeline


def _trailing_return(ticker: str, window_days: int, as_of: pd.Timestamp) -> float | None:
    """Raw (non-residualized) trailing return over the `window_days` TRADING
    days immediately before `as_of` (the earnings event's own date -- NOT
    wall-clock "now", so a just-reported event a few days old still gets the
    momentum window that actually precedes ITS announcement), from real
    recently-fetched prices. See module docstring for why this is a
    documented deviation from the historical (residualized) feature."""
    end = as_of.normalize()
    start = end - pd.Timedelta(days=MOMENTUM_LOOKBACK_DAYS)
    hist = fetch_ticker_history(ticker, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
    if hist.empty or len(hist) <= window_days:
        return None
    closes = hist.sort_values("timestamp")["close"]
    if closes.iloc[-(window_days + 1):].isna().any():
        return None
    return float(closes.iloc[-1] / closes.iloc[-(window_days + 1)] - 1.0)


def build_feature_row(event: ReportedEarnings) -> pd.DataFrame | None:
    """Real SUE (earnings/sue.py) + real feature extraction for ONE fresh,
    just-reported earnings event. Returns None (never a fabricated row) if
    any required real input is unavailable."""
    history = fetch_ticker_earnings_live(event.ticker)
    if history.empty:
        logger.warning(f"{event.ticker}: no earnings history available for SUE computation")
        return None
    sue_df = compute_sue(history)
    match = sue_df[sue_df["earnings_date"] == event.earnings_date]
    if match.empty or pd.isna(match.iloc[-1]["sue"]):
        logger.warning(f"{event.ticker}: SUE unavailable for {event.earnings_date} (insufficient trailing history)")
        return None
    sue_row = match.iloc[-1]

    ret_5d = _trailing_return(event.ticker, 5, event.earnings_date)
    ret_20d = _trailing_return(event.ticker, 20, event.earnings_date)
    if ret_5d is None or ret_20d is None:
        logger.warning(f"{event.ticker}: insufficient recent price history for momentum features")
        return None

    ranking = pd.read_csv(REPORTS_DIR / "universe_ranking.csv")
    ranking["dollar_volume_rank"] = ranking["avg_dollar_volume"].rank(ascending=False)
    rank_row = ranking[ranking["ticker"] == event.ticker]
    dollar_volume_rank = float(rank_row["dollar_volume_rank"].iloc[0]) if not rank_row.empty else float(len(ranking) + 1)

    row = {
        "signal": float(sue_row["sue"]),
        "abs_sue": float(abs(sue_row["sue"])),
        "surprise_pct_winsorized": float(np.clip(sue_row["surprise_pct"], -SURPRISE_PCT_WINSOR_LIMIT, SURPRISE_PCT_WINSOR_LIMIT)),
        "pre_earnings_return_5d": ret_5d,
        "pre_earnings_return_20d": ret_20d,
        "dollar_volume_rank": dollar_volume_rank,
    }
    return pd.DataFrame([row])[PEAD_FEATURE_COLUMNS]


@dataclass
class ScoredEvent:
    ticker: str
    earnings_date: pd.Timestamp
    sue: float
    calibrated_proba: float
    direction: str  # "long" if sue > 0 else "short"


def score_event(event: ReportedEarnings, pipeline: FittedPipeline) -> ScoredEvent | None:
    """Fresh event -> real features -> ensemble -> calibrated probability.
    Returns None if a real feature row could not be built (never scores on
    fabricated inputs)."""
    features = build_feature_row(event)
    if features is None:
        return None
    raw_proba = pipeline.ensemble.predict_proba(features)
    calibrated = pipeline.calibrator.transform(raw_proba)
    sue = float(features.iloc[0]["signal"])
    return ScoredEvent(
        ticker=event.ticker, earnings_date=event.earnings_date, sue=sue,
        calibrated_proba=float(calibrated[0]), direction="long" if sue > 0 else "short",
    )
