"""Validates the overnight-drift ("close->open") market anomaly on quant_v7's
own real universe, at the same statistical rigor as every other go/no-go in
this project: real data, time-disjoint split robustness, bootstrap CI,
a tailored permutation null, realistic transaction costs, and a
buy-and-hold baseline -- not just the raw per-ticker summary table.

Motivating claim (user-supplied, citing Perreten & Wallmeier,
arXiv:2507.04481): overnight (close->open) returns are broadly positive and
statistically significant across most stocks, while intraday (open->close)
returns are close to flat -- a structural, market-wide phenomenon, not a
single-stock fluke.

Data: data/raw/{ticker}.parquet. data/ingestion.py pulls with
`auto_adjust=True`, so OHLC are split/dividend-adjusted consistently --
simple-return ratios (open_t / close_{t-1}) are safe across corporate
actions without extra adjustment logic.

Two universes checked, matching this project's own convention:
  - reports/universe_selection.txt: the 75 liquid names the live PEAD bot
    actually trades (execution-realistic).
  - the full data/raw/ set (~502 tickers): broad-market check, matching the
    cited paper's "market-wide, not single-stock" framing.

CAVEAT (survivorship bias, flagged by adversarial review): both universes
are built from CURRENT index/cache membership with backfilled history --
names that were removed or went under are not represented. This affects how
literally "market-wide" the full_universe result should be read (evidence
for names that survived to today, not a delisting-inclusive sample); it
does not differentially affect the overnight-vs-intraday GAP within the
names tested, since survivorship bias applies equally to both legs of the
same tickers.

METHODOLOGY FIXES (2026-08-21, after adversarial review -- see
to_simple()'s and null_swap_test()'s docstrings for the two real bugs found
and corrected: log-vs-simple-return compounding, and a pseudo-replication
flaw in the original per-row null-swap test that produced an artificially
small p-value).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from scipy import stats

from backtest.metrics import compute_metrics
from ml.validation import split_time_disjoint_panel
from risk.transaction_costs import COST_SWEEP_BPS, cost_as_return
from reports.run_pead_significance import bootstrap_sharpe_ci, sharpe_from_daily_returns

DATA_DIR = Path(__file__).parent.parent / "data" / "raw"
REPORTS_DIR = Path(__file__).parent
RNG_SEED = 20260822
N_BOOTSTRAP = 5000
N_NULL_SWAPS = 5000
MIN_OBS_PER_TICKER = 60  # ~3 trading months minimum before trusting a per-ticker t-stat


def load_universe(tickers: list[str]) -> pd.DataFrame:
    """One row per (ticker, trading day) with overnight/intraday/total LOG
    returns. Log returns are used because they're exactly additive
    (overnight + intraday == total), which the null-swap test below depends
    on. dropna on the first row per ticker (no prev_close) is correct, not
    a bug -- there is no overnight return defined for a ticker's first
    cached day."""
    frames = []
    for path in sorted(DATA_DIR.glob("*.parquet")):
        ticker = path.stem
        if tickers is not None and ticker not in tickers:
            continue
        df = pd.read_parquet(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        df["prev_close"] = df["close"].shift(1)
        valid = (df["prev_close"] > 0) & (df["open"] > 0) & (df["close"] > 0)
        df = df[valid].copy()
        df["overnight_ret"] = np.log(df["open"] / df["prev_close"])
        df["intraday_ret"] = np.log(df["close"] / df["open"])
        df["total_ret"] = np.log(df["close"] / df["prev_close"])
        df["ticker"] = ticker
        df = df.dropna(subset=["overnight_ret", "intraday_ret"])
        frames.append(df[["ticker", "timestamp", "overnight_ret", "intraday_ret", "total_ret"]])
    if not frames:
        raise RuntimeError("no ticker data loaded -- check DATA_DIR / universe list")
    return pd.concat(frames, ignore_index=True)


def per_ticker_table(panel: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Replicates the user-supplied summary table format: mean daily return
    (bps), % of stocks with positive mean, % significant positive/negative
    (two-sided t-stat threshold 1.96), computed independently per ticker
    then aggregated -- exactly the methodology implied by the pasted table,
    so the numbers are directly comparable."""
    rows = []
    for ticker, g in panel.groupby("ticker"):
        if len(g) < MIN_OBS_PER_TICKER:
            continue
        for leg in ("overnight_ret", "intraday_ret"):
            x = g[leg].to_numpy()
            t_stat, _ = stats.ttest_1samp(x, 0.0)
            rows.append({"ticker": ticker, "leg": leg, "mean_bps": float(x.mean() * 10_000),
                         "t_stat": float(t_stat), "n": len(x)})
    df = pd.DataFrame(rows)
    summary = {}
    for leg in ("overnight_ret", "intraday_ret"):
        sub = df[df["leg"] == leg]
        summary[leg] = {
            "n_tickers": int(len(sub)),
            "mean_daily_return_bps": float(sub["mean_bps"].mean()),
            "pct_positive_mean": float((sub["mean_bps"] > 0).mean() * 100),
            "pct_significant_positive": float((sub["t_stat"] > 1.96).mean() * 100),
            "pct_significant_negative": float((sub["t_stat"] < -1.96).mean() * 100),
        }
    return summary, df


def portfolio_daily_returns(panel: pd.DataFrame, leg: str) -> pd.Series:
    """Equal-weight portfolio: mean return across whatever tickers have
    data on that calendar day (handles the real universe's uneven history
    lengths -- some tickers IPO'd or were added to data/raw/ later). Still
    in LOG-return space -- callers feeding this into compute_metrics /
    bootstrap_sharpe_ci (which use simple-return compounding formulas)
    must convert via to_simple() first."""
    return panel.groupby(panel["timestamp"].dt.normalize())[leg].mean().sort_index()


def to_simple(log_returns: pd.Series) -> pd.Series:
    """Converts a LOG-return series to SIMPLE (arithmetic) returns before
    handing it to compute_metrics / bootstrap_sharpe_ci / sharpe_from_daily_returns,
    all of which compound via (1+r).prod() -- correct only for simple
    returns. Fixed 2026-08-21 after adversarial review found every
    Sharpe/annualized-return/total-return/max-drawdown figure in this
    script's first version had been computed by feeding log returns
    directly into those simple-return formulas (log(1+r) != r, so
    (1+logret).prod() != exp(sum(logret))) -- a real, quantified bias
    (Sharpe understated ~0.06-0.09, total return understated up to ~24%
    over the full ~11.6y sample). expm1 is the exact inverse of the log1p
    implicit in log(open/close): simple_ret = exp(log_ret) - 1."""
    return np.expm1(log_returns)


def null_swap_test(panel: pd.DataFrame, n_swaps: int, rng: np.random.Generator) -> dict:
    """Tailored permutation null for THIS question. total_log_return =
    overnight + intraday EXACTLY for every (ticker, day) observation. Under
    the null hypothesis of no structural overnight/intraday asymmetry, the
    two legs of any single observation are exchangeable -- which of the two
    numbers gets called "overnight" is arbitrary. Randomly swap them and
    measure how often a leg-gap (mean(leg A) - mean(leg B)) at least as
    extreme as the REAL observed gap arises from pure random relabeling.

    DAY-BLOCKED, not per-row (fixed 2026-08-21 after adversarial review
    found a real pseudo-replication bug): overnight/intraday returns are
    heavily cross-sectionally correlated within a day -- a market-wide
    overnight gap (e.g. an overnight macro headline) moves nearly every
    ticker the same direction on the same day. An earlier version drew an
    independent Bernoulli swap per (ticker, day) ROW, treating ~1.4M
    pseudo-independent draws where the true independent unit is the ~2,900
    trading DAYS -- this collapsed the null distribution's spread and
    produced an artificially small p-value (verified: on liquid_75, the
    row-level version gives null_std=0.56bps/p=0.0; this day-blocked
    version gives a ~5x wider null and a materially different p-value on
    the same real data). One shared coin flip per calendar day is drawn and
    applied to every ticker observed that day.

    Implementation note: swapping day d's rows flips the sign of every
    (overnight_i - intraday_i) on that day, so
    sum(a-b) == sum_d[sign(d) * day_diff_sum[d]] EXACTLY (not an
    approximation) -- this lets the day-level resampling run as a single
    matrix-vector product instead of re-indexing the full row-level arrays
    on every draw."""
    panel = panel.copy()
    panel["date"] = panel["timestamp"].dt.normalize()
    diff = panel["overnight_ret"] - panel["intraday_ret"]
    day_diff_sum = diff.groupby(panel["date"]).sum().to_numpy()
    n_rows = len(panel)
    n_days = len(day_diff_sum)

    real_gap = float(day_diff_sum.sum() / n_rows)

    signs = rng.integers(0, 2, size=(n_swaps, n_days)) * 2 - 1  # +-1
    null_gaps = (signs @ day_diff_sum) / n_rows

    p_value = float(np.mean(np.abs(null_gaps) >= abs(real_gap)))
    return {
        "real_gap_bps": real_gap * 10_000,
        "null_mean_bps": float(null_gaps.mean() * 10_000),
        "null_std_bps": float(null_gaps.std() * 10_000),
        "empirical_p_value": p_value,
        "significant_at_5pct": p_value < 0.05,
        "methodology": "day-blocked swap (one shared coin flip per trading day, applied to every "
                        "ticker that day) -- corrects a pseudo-replication bug from an earlier "
                        "per-(ticker,day)-row version, found via adversarial review.",
        "n_days": int(n_days),
    }


def cost_sensitivity(daily_log_returns: pd.Series) -> dict:
    """Extracting ONLY the overnight component means selling every close
    and buying every open -- ONE round trip per trading day, unlike a
    buy-and-hold position which pays a round trip once. Applies
    risk/transaction_costs.py's real cost sweep (the same one used for
    every other strategy in this project) to that daily 100%-turnover
    structure.

    Converts to SIMPLE returns (to_simple()) before subtracting cost: a
    transaction cost is a fixed fraction of capital lost per round trip --
    a simple-return concept -- and compute_metrics' compounding formula is
    only correct for simple returns (see to_simple's docstring)."""
    daily_simple = to_simple(daily_log_returns)
    out = {}
    for cost_bps in sorted(set(COST_SWEEP_BPS + [10.0])):
        cost = cost_as_return(cost_bps)
        net = daily_simple - cost
        metrics = compute_metrics(net, n_trades=len(net), avg_position_size=1.0)
        out[f"{cost_bps:g}bps_round_trip"] = {
            "net_annualized_return": metrics.annualized_return,
            "net_sharpe_ratio": metrics.sharpe_ratio,
            "net_total_return": metrics.total_return,
            "net_max_drawdown": metrics.max_drawdown,
        }
    return out


def split_robustness(panel: pd.DataFrame, leg: str) -> dict:
    """Does the edge hold independently in EACH time-disjoint partition, or
    is it concentrated in one era? Reuses ml.validation.split_time_disjoint_panel
    (the same 5-way train/validation/holdout_a/b/c boundary scheme used for
    every ML-filter validation in this project) purely as a chronological
    partitioner here -- there is no model being trained, holding_period=1
    is used only to purge a 1-day gap at each partition boundary."""
    df = panel.rename(columns={"timestamp": "date"})
    parts, _partitions = split_time_disjoint_panel(df, date_col="date", holding_period=1, min_rows_per_partition=200)
    out = {}
    for name, part_df in parts.items():
        daily_log = portfolio_daily_returns(part_df.rename(columns={"date": "timestamp"}), leg)
        if len(daily_log) < 2:
            continue
        metrics = compute_metrics(to_simple(daily_log), n_trades=len(daily_log), avg_position_size=1.0)
        out[name] = {
            "n_days": int(len(daily_log)),
            "start": str(daily_log.index.min().date()), "end": str(daily_log.index.max().date()),
            "mean_bps": float(daily_log.mean() * 10_000),
            "sharpe_ratio": metrics.sharpe_ratio,
            "pct_positive_days": float((daily_log > 0).mean() * 100),
        }
    return out


def run_for_universe(universe_name: str, tickers: list[str] | None) -> dict:
    logger.info(f"=== universe: {universe_name} ===")
    panel = load_universe(tickers)
    n_tickers = panel["ticker"].nunique()
    logger.info(f"{universe_name}: {n_tickers} tickers, {len(panel)} ticker-days, "
                f"{panel['timestamp'].min().date()} -> {panel['timestamp'].max().date()}")

    per_ticker_summary, _per_ticker_df = per_ticker_table(panel)
    logger.info(f"{universe_name} per-ticker summary: {json.dumps(per_ticker_summary, indent=2)}")

    overnight_daily = portfolio_daily_returns(panel, "overnight_ret")
    intraday_daily = portfolio_daily_returns(panel, "intraday_ret")
    total_daily = portfolio_daily_returns(panel, "total_ret")

    rng = np.random.default_rng(RNG_SEED)
    overnight_bootstrap = bootstrap_sharpe_ci(to_simple(overnight_daily), N_BOOTSTRAP, rng)
    intraday_bootstrap = bootstrap_sharpe_ci(to_simple(intraday_daily), N_BOOTSTRAP, np.random.default_rng(RNG_SEED))
    buy_and_hold_bootstrap = bootstrap_sharpe_ci(to_simple(total_daily), N_BOOTSTRAP, np.random.default_rng(RNG_SEED))

    null_test = null_swap_test(panel, N_NULL_SWAPS, np.random.default_rng(RNG_SEED))

    overnight_cost_sensitivity = cost_sensitivity(overnight_daily)
    buy_and_hold_metrics = compute_metrics(to_simple(total_daily), n_trades=1, avg_position_size=1.0)  # ~single entry, held

    overnight_split = split_robustness(panel, "overnight_ret")
    intraday_split = split_robustness(panel, "intraday_ret")

    return {
        "universe": universe_name,
        "n_tickers": int(n_tickers),
        "date_range": [str(panel["timestamp"].min().date()), str(panel["timestamp"].max().date())],
        "per_ticker_summary": per_ticker_summary,
        "portfolio_overnight_bootstrap_sharpe_ci": overnight_bootstrap,
        "portfolio_intraday_bootstrap_sharpe_ci": intraday_bootstrap,
        "buy_and_hold_bootstrap_sharpe_ci": buy_and_hold_bootstrap,
        "null_swap_test": null_test,
        "overnight_cost_sensitivity": overnight_cost_sensitivity,
        "buy_and_hold_metrics": {
            "annualized_return": buy_and_hold_metrics.annualized_return,
            "sharpe_ratio": buy_and_hold_metrics.sharpe_ratio,
            "max_drawdown": buy_and_hold_metrics.max_drawdown,
        },
        "overnight_split_robustness": overnight_split,
        "intraday_split_robustness": intraday_split,
    }


def main():
    liquid_universe_path = REPORTS_DIR / "universe_selection.txt"
    with open(liquid_universe_path) as f:
        lines = f.read().strip().split("\n")
        liquid_tickers = lines[1].split(",")

    results = {
        "liquid_75": run_for_universe("liquid_75 (live PEAD bot universe)", liquid_tickers),
        "full_universe": run_for_universe("full_universe (all cached tickers)", None),
    }

    out_path = REPORTS_DIR / "overnight_drift_validation.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"wrote {out_path}")
    return results


if __name__ == "__main__":
    main()
