"""Task 12: run the full Phase 2 pipeline across the whole historical
universe and produce a real report -- cluster count over time, stability,
and any anomalies (e.g. a period where cluster count collapses -- flagged,
not explained away).

Primary series (daily, full history): residual returns -> rolling 60-day
correlation -> explained-variance(90%) cluster count (spec default) ->
spectral clustering -> ARI-based stability vs. the prior day.

Secondary comparison (monthly sample, ~21-trading-day step): SPONGE-sym
clustering run alongside spectral on the same snapshots, plus the
Marchenko-Pastur cluster-count alternative, so the two "if time allows"
methods are exercised and compared without tripling the runtime of the
full daily run.

Outputs (all under quant_v7/reports/):
  - cluster_count_timeseries.csv   (date, k_ev, n_tickers, ari_vs_prev)
  - method_comparison.csv          (date, k_ev, k_mp, ari_spectral_vs_sponge)
  - pipeline_summary.json          (headline numbers + detected anomalies)
  - data_quality.jsonl / cluster_stability.jsonl (structured logs, written
    incrementally by quality.monitor / clustering.stability as they run)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.metrics import adjusted_rand_score

from data.ingestion import load_universe
from quality.monitor import run_quality_checks
from clustering.residual_returns import build_residual_returns
from clustering.correlation import rolling_correlation_matrices
from clustering.cluster_count import explained_variance_k, marchenko_pastur_k
from clustering.clustering import spectral_cluster, sponge_sym_cluster
from clustering.stability import compute_stability_series, stability_dataframe

REPORTS_DIR = Path(__file__).parent
LOOKBACK = 60
COMPARISON_STEP = 21  # ~1 trading month, for the spectral-vs-SPONGE-sym comparison sample


def main():
    t0 = time.time()
    with open(REPORTS_DIR / "universe_selection.txt") as f:
        lines = f.read().strip().split("\n")
    selection_rule, tickers = lines[0], lines[1].split(",")
    logger.info(f"universe: {len(tickers)} tickers")

    universe_data = load_universe(tickers, data_dir=REPORTS_DIR.parent / "data" / "raw")
    logger.info(f"loaded {len(universe_data)}/{len(tickers)} tickers from disk")

    quality_report = run_quality_checks(universe_data)

    residuals = build_residual_returns(universe_data, lookback=LOOKBACK, start="2015-01-01")

    logger.info("building full daily rolling correlation + cluster-count + spectral-clustering series...")
    snaps = rolling_correlation_matrices(residuals, lookback=LOOKBACK, step=1)

    dated_results = []
    rows = []
    for snap in snaps:
        k_ev, _ = explained_variance_k(snap.matrix, threshold=0.90)
        k_ev = max(2, min(k_ev, len(snap.tickers) - 1))
        cr = spectral_cluster(snap.matrix, snap.tickers, k=k_ev)
        dated_results.append((snap.date, cr))
        rows.append({"date": snap.date, "k_ev": k_ev, "n_tickers": len(snap.tickers)})

    stability_points = compute_stability_series(dated_results)
    stability_df = stability_dataframe(stability_points)
    timeseries_df = pd.DataFrame(rows).merge(stability_df[["date", "ari_vs_prev"]], on="date", how="left")
    timeseries_df.to_csv(REPORTS_DIR / "cluster_count_timeseries.csv", index=False)
    logger.info(f"wrote cluster_count_timeseries.csv ({len(timeseries_df)} rows)")

    logger.info(f"building method-comparison sample (spectral vs SPONGE-sym, every {COMPARISON_STEP} snapshots)...")
    comparison_rows = []
    for snap in snaps[::COMPARISON_STEP]:
        k_ev, _ = explained_variance_k(snap.matrix, threshold=0.90)
        k_ev = max(2, min(k_ev, len(snap.tickers) - 1))
        k_mp, lambda_max = marchenko_pastur_k(snap.matrix, n_obs=LOOKBACK)
        k_mp = max(2, min(k_mp, len(snap.tickers) - 1))

        sc = spectral_cluster(snap.matrix, snap.tickers, k=k_ev)
        sp = sponge_sym_cluster(snap.matrix, snap.tickers, k=k_ev)
        ari = float(adjusted_rand_score(sc.labels, sp.labels))
        comparison_rows.append({
            "date": snap.date, "n_tickers": len(snap.tickers),
            "k_ev": k_ev, "k_mp": k_mp, "mp_lambda_max": lambda_max,
            "ari_spectral_vs_sponge": ari,
        })
    comparison_df = pd.DataFrame(comparison_rows)
    comparison_df.to_csv(REPORTS_DIR / "method_comparison.csv", index=False)
    logger.info(f"wrote method_comparison.csv ({len(comparison_df)} rows)")

    # Anomaly detection: flag any date where k_ev drops >=40% relative to its
    # trailing 30-snapshot median (a "cluster count collapse"), and any date
    # with ari_vs_prev < 0 (worse-than-random agreement with the prior day).
    ts = timeseries_df.copy()
    ts["k_ev_trailing_median"] = ts["k_ev"].rolling(30, min_periods=10).median()
    ts["collapse_flag"] = ts["k_ev"] < 0.6 * ts["k_ev_trailing_median"]
    collapse_dates = ts.loc[ts["collapse_flag"], "date"].astype(str).tolist()
    negative_ari_dates = ts.loc[ts["ari_vs_prev"] < 0, "date"].astype(str).tolist()

    summary = {
        "universe_size": len(tickers),
        "universe_selection_rule": selection_rule,
        "tickers_ingested": len(universe_data),
        "data_date_range": [str(residuals.index.min().date()), str(residuals.index.max().date())],
        "correlation_lookback_days": LOOKBACK,
        "n_correlation_snapshots": len(snaps),
        "k_ev_stats": {
            "min": int(ts["k_ev"].min()), "max": int(ts["k_ev"].max()),
            "mean": float(ts["k_ev"].mean()), "median": float(ts["k_ev"].median()),
        },
        "ari_vs_prev_stats": {
            "mean": float(ts["ari_vs_prev"].mean(skipna=True)),
            "median": float(ts["ari_vs_prev"].median(skipna=True)),
            "pct_below_0.5": float((ts["ari_vs_prev"] < 0.5).mean(skipna=True)),
        },
        "anomalies": {
            "cluster_count_collapse_dates": collapse_dates,
            "n_collapse_events": len(collapse_dates),
            "negative_ari_dates_sample": negative_ari_dates[:20],
            "n_negative_ari_events": len(negative_ari_dates),
        },
        "data_quality": {
            "tickers_with_gaps": len(quality_report.gaps),
            "stale_feed_tickers": len(quality_report.stale),
        },
        "method_comparison_sample_size": len(comparison_df),
        "mean_ari_spectral_vs_sponge": float(comparison_df["ari_spectral_vs_sponge"].mean()),
        "runtime_seconds": round(time.time() - t0, 1),
    }
    with open(REPORTS_DIR / "pipeline_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"pipeline complete in {summary['runtime_seconds']}s. summary written to pipeline_summary.json")
    return summary


if __name__ == "__main__":
    summary = main()
    print(json.dumps(summary, indent=2, default=str))
