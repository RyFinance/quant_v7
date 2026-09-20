"""Pre-registered out-of-sample test: the production PEAD model on 2004-2014.

Implements research/PREREGISTRATION_pead_2004_2014.md as amended by
research/PREREGISTRATION_pead_2004_2014_AMENDMENT_1.md, and nothing else. It
refuses to run if either document no longer matches the SHA-256 recorded in
research/preregistrations.jsonl when it was written, so the rules cannot drift
after results are seen.

Every feature is built with the SAME functions and the SAME price source the
production model was trained with -- yfinance official daily bars,
auto-adjusted -- via earnings/sue.py, earnings/signal.py, earnings/labeling.py,
earnings/features.py and clustering/residual_returns.py. Amendment 1 moved
prices off the LSE vault, whose daily bars are UTC-day extended-hours bars
whose close already contains after-hours earnings reactions.

Run: PYTHONPATH=. .venv/bin/python -m research.pead_2004_2014
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from backtest.research import block_sharpe_difference, simulate_weights
from bot.earnings_watcher import load_validated_universe
from bot.signal_pipeline import MODEL_PATH
from clustering.residual_returns import compute_residual_returns
from earnings.features import PEAD_FEATURE_COLUMNS, build_pead_feature_matrix
from earnings.ingestion import load_universe_earnings
from earnings.labeling import build_labeled_pead_signals
from earnings.signal import build_pead_signal
from earnings.sue import build_universe_sue
from research.higher_sharpe import cash_rates, stats
from risk.kelly import fractional_kelly_size

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/pead_2004_2014"
PREREG = ROOT / "research/PREREGISTRATION_pead_2004_2014.md"
AMENDMENTS = [ROOT / "research/PREREGISTRATION_pead_2004_2014_AMENDMENT_1.md"]
REGISTRY = ROOT / "research/preregistrations.jsonl"
PRICE_CACHE = ROOT / "data/yf_2003_2015"

TEST_START, TEST_END = "2004-01-01", "2014-12-31"
PRICE_START, PRICE_END = "2003-01-01", "2015-03-31"  # warmup before, 20-session holds after
HALVES = {"2004-2008": ("2004-01-01", "2008-12-31"), "2009-2014": ("2009-01-01", "2014-12-31")}
HOLD = 20
POSITION_CAP, GROSS_CAP = 0.05, 1.00  # the live configuration
KELLY_FRACTION = 0.25
COST_BPS, BORROW = 10.0, 0.03


def verify_preregistration() -> str:
    """The original and every amendment must match their registered digests."""
    registered = {Path(r["file"]).name: r for r in
                  (json.loads(line) for line in REGISTRY.read_text().splitlines() if line.strip())}
    for doc in [PREREG, *AMENDMENTS]:
        rec = registered.get(doc.name)
        if rec is None or rec["sha256"] != hashlib.sha256(doc.read_bytes()).hexdigest():
            raise SystemExit(f"{doc.name} changed since it was registered; write a NEW amendment instead")
    return registered[PREREG.name]["registered_at"]


def official_panels(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """yfinance official-session daily bars, split- and dividend-adjusted, 2003-2015.
    Downloaded once into data/yf_2003_2015/ and reused, so reruns are identical."""
    import yfinance as yf
    PRICE_CACHE.mkdir(parents=True, exist_ok=True)
    wanted = sorted(set(tickers) | {"SPY"})
    missing = [t for t in wanted if not (PRICE_CACHE / f"{t}.parquet").exists()]
    for i in range(0, len(missing), 50):
        chunk = missing[i:i + 50]
        raw = yf.download(chunk, start=PRICE_START, end=PRICE_END, auto_adjust=True,
                          progress=False, group_by="ticker", threads=True)
        for t in chunk:
            try:
                d = (raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw).dropna(how="all")
            except KeyError:
                continue
            if d.empty:
                continue
            d = d.copy()
            d.columns = [str(c).lower() for c in d.columns]
            d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
            d.rename_axis("date").reset_index().to_parquet(PRICE_CACHE / f"{t}.parquet", index=False)
    opens, closes, volumes = {}, {}, {}
    for t in wanted:
        path = PRICE_CACHE / f"{t}.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path).set_index("date").sort_index().loc[PRICE_START:PRICE_END]
        if d.empty:
            continue
        opens[t], closes[t], volumes[t] = d["open"], d["close"], d["volume"]
    frame = lambda x: pd.DataFrame(x).sort_index()
    return {"open": frame(opens), "close": frame(closes), "volume": frame(volumes)}


def build_events(closes: pd.DataFrame, spy: pd.Series) -> pd.DataFrame:
    """Training's own pipeline, end to end, on the 2003-2015 price panel."""
    returns = closes.pct_change(fill_method=None).dropna(how="all")
    residual = compute_residual_returns(returns, spy, lookback=60)
    earnings = load_universe_earnings(list(closes.columns))
    sue = build_universe_sue(earnings)
    signal = build_pead_signal(sue, residual)
    labeled = build_labeled_pead_signals(residual, signal)
    ranking = pd.read_csv(ROOT / "reports/expanded_universe_liquidity_ranking.csv")
    features = build_pead_feature_matrix(labeled, residual, ranking)
    features["date"] = pd.to_datetime(features["date"])
    features = features[(features["date"] >= TEST_START) & (features["date"] <= TEST_END)]
    return features.reset_index(drop=True)


def score(features: pd.DataFrame) -> pd.DataFrame:
    pipeline = joblib.load(MODEL_PATH)  # never refit: this is the production model
    raw = pipeline.ensemble.predict_proba(features[PEAD_FEATURE_COLUMNS])
    out = features.copy()
    out["probability"] = pipeline.calibrator.transform(raw)
    out["size"] = fractional_kelly_size(out["probability"].to_numpy(), pipeline.payoff.b, KELLY_FRACTION, POSITION_CAP)
    return out


def targets_from_events(closes: pd.DataFrame, events: pd.DataFrame, size_col: str | None) -> pd.DataFrame:
    """Signed weight per event, set on its effective date (the engine fills at the
    NEXT open) and held for HOLD sessions. A name already held ignores new events.
    size_col=None trades every event at the position cap (the all-events control)."""
    targets = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    by_date = {d: g for d, g in events.groupby("date")}
    book: dict[str, tuple[int, float]] = {}
    for i, date in enumerate(closes.index):
        book = {t: v for t, v in book.items() if v[0] > i}
        group = by_date.get(date)
        if group is not None:
            for e in group.itertuples():
                if e.ticker not in targets.columns or e.ticker in book or not np.isfinite(e.signal) or e.signal == 0:
                    continue
                size = POSITION_CAP if size_col is None else float(getattr(e, size_col))
                if size <= 0:
                    continue
                book[e.ticker] = (i + HOLD, float(np.sign(e.signal)) * size)
        for t, (_, w) in book.items():
            targets.loc[date, t] = w
    return targets


def run(panels, targets, rf):
    return simulate_weights(panels["open"], panels["close"], targets, TEST_START, TEST_END,
                            cost_bps=COST_BPS, gross_cap=GROSS_CAP, position_cap=POSITION_CAP,
                            borrow_rate=BORROW, cash_returns=rf)


def main() -> dict:
    registered_at = verify_preregistration()
    OUT.mkdir(parents=True, exist_ok=True)
    universe = load_validated_universe()
    panels = official_panels(universe)
    spy = panels["close"]["SPY"].pct_change(fill_method=None).dropna().rename("SPY")
    for key in ("open", "close", "volume"):  # SPY is the benchmark, never a traded name
        panels[key] = panels[key].drop(columns="SPY")
    rf = cash_rates()

    features = build_events(panels["close"], spy)
    scored = score(features)
    scored.to_parquet(OUT / "scored_events.parquet", index=False)
    traded = scored[scored["size"] > 0]

    model_path = run(panels, targets_from_events(panels["close"], traded, "size"), rf)
    control_path = run(panels, targets_from_events(panels["close"], scored, None), rf)
    model_path.to_csv(OUT / "model.csv")
    control_path.to_csv(OUT / "all_events_control.csv")

    spy_full = spy.reindex(model_path.index)
    result = {"preregistered_at": registered_at, "amendments": [a.name for a in AMENDMENTS],
              "events_scored": len(scored), "events_traded": len(traded),
              "tickers_with_prices": int(panels["close"].shape[1]),
              "model": stats(model_path, spy_full, rf), "all_events_control": stats(control_path, spy_full, rf),
              "halves": {}}
    for name, (a, b) in HALVES.items():
        result["halves"][name] = {"model": stats(model_path.loc[a:b], spy_full, rf),
                                  "all_events_control": stats(control_path.loc[a:b], spy_full, rf)}
    rfd = rf.reindex(model_path.index)
    diff = block_sharpe_difference(model_path["return"] - rfd, control_path["return"] - rfd, block=63)
    result["model_vs_control_sharpe_ci_95"] = diff

    # Feature drift versus the model's training data: a garbage-in check, not a criterion.
    train = pd.read_parquet(ROOT / "data/pead_labeled_features_expanded.parquet")
    result["feature_means"] = {c: {"training": float(train[c].mean()), "2004_2014": float(scored[c].mean())}
                               for c in PEAD_FEATURE_COLUMNS}

    criteria = {
        "alpha_hac_t_at_least_2": result["model"]["alpha_hac_t"] >= 2.0,
        "beats_all_events_control": diff["lower_95"] > 0,
        "positive_alpha_both_halves": all(h["model"]["alpha_annual"] > 0 for h in result["halves"].values()),
    }
    result["criteria"] = criteria
    result["passed"] = all(criteria.values())
    (OUT / "results.json").write_text(json.dumps(result, indent=2, default=float))
    write_report(result)
    return result


def write_report(r: dict) -> None:
    m, c = r["model"], r["all_events_control"]
    row = lambda name, s: (f"| {name} | {s['annualized_return']:.2%} | {s['annualized_std']:.2%} | {s['sharpe_ratio']:.2f} | "
                           f"{s['max_drawdown']:.1%} | {s['beta']:.2f} | {s['alpha_annual']:.2%} | {s['alpha_hac_t']:.2f} |")
    lines = [
        "# Pre-registered test: the production PEAD model on 2004–2014", "",
        f"Rules fixed in `research/PREREGISTRATION_pead_2004_2014.md`, registered {r['preregistered_at']}, before any",
        "result existed; Amendment 1 moved prices to yfinance official daily bars, also before any result.",
        "The model was never refit. Prices and SPY: yfinance, split- and dividend-adjusted.", "",
        f"**Outcome: {'PASS' if r['passed'] else 'FAIL'}**", "",
        "| Criterion | Result |", "|---|---|",
        *[f"| {k.replace('_', ' ')} | {'pass' if v else 'fail'} |" for k, v in r["criteria"].items()], "",
        f"{r['events_scored']:,} events scored, {r['events_traded']:,} traded by the model, "
        f"{r['tickers_with_prices']} tickers with prices.", "",
        "| Portfolio | CAGR | Vol | Excess Sharpe | Max DD | Beta | Alpha/yr | Alpha HAC t |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        row("Model (live config: 5% / 100% gross)", m), row("All-events control", c), "",
        "| Half | Model alpha/yr | Model alpha t | Control alpha/yr |", "|---|---:|---:|---:|",
        *[f"| {k} | {v['model']['alpha_annual']:.2%} | {v['model']['alpha_hac_t']:.2f} | "
          f"{v['all_events_control']['alpha_annual']:.2%} |" for k, v in r["halves"].items()], "",
        f"Model minus control excess Sharpe, 63-day block bootstrap 95%: "
        f"[{r['model_vs_control_sharpe_ci_95']['lower_95']:.2f}, {r['model_vs_control_sharpe_ci_95']['upper_95']:.2f}].", "",
        "## Reading it", "",
        "- The universe is today's S&P 500, which biases returns **upward** (failures and delistings are",
        "  missing). A fail is therefore robust; a pass is necessary but not sufficient.",
        "- Execution is next-open, more conservative than the live bot's same-close fill.",
        "- The circuit breaker is not replayed (no calibrated history before 2015).", "",
        "Reproduce: `PYTHONPATH=. .venv/bin/python -m research.pead_2004_2014`",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    res = main()
    print("PASSED" if res["passed"] else "FAILED", json.dumps(res["criteria"]))
    print({k: round(v, 3) if isinstance(v, float) else v for k, v in res["model"].items()
           if k in ("annualized_return", "sharpe_ratio", "alpha_annual", "alpha_hac_t", "beta", "max_drawdown")})
