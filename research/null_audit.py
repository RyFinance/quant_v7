"""Re-grade every recorded out-of-sample result as a bounded or vacuous null (no new data or trials).

Run: PYTHONPATH=. .venv/bin/python -m research.null_audit
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.common.inference import annual_sharpe, null_kind, sharpe_ci, sharpe_ci_iid
from research.options_signals.signals import french_daily

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "reports"
OUT = R / "null_audit"
CONSEQUENTIAL = 0.5  # a sleeve worth holding; the project target is 2.0


def rf() -> pd.Series:
    return french_daily()["rf"]


def excess(ret: pd.Series) -> pd.Series:
    r = rf().reindex(ret.index.union(rf().index)).ffill().reindex(ret.index).fillna(0)
    return ret - r


def load(path, col="return", start=None, end=None, subtract_rf=True):
    d = pd.read_csv(path, index_col=0, parse_dates=True)
    s = d[col].astype(float)
    if start:
        s = s.loc[start:]
    if end:
        s = s.loc[:end]
    return excess(s) if subtract_rf else s


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []

    def add(family, name, window, x, reported=None, note=""):
        x = x.dropna()
        sr = annual_sharpe(x.to_numpy(), 252)
        ci = sharpe_ci(x.to_numpy(), 252, block=21)
        rows.append({"family": family, "result": name, "window": window, "years": round(len(x) / 252, 1),
                     "sharpe": round(sr, 2), "reported": reported, "ci95_lo": round(ci[0], 2), "ci95_hi": round(ci[1], 2),
                     "verdict": null_kind(ci, CONSEQUENTIAL), "rules_out_target_2": ci[1] < 2.0, "note": note})

    ho = pd.read_csv(R / "multiasset/holdout/holdout_returns.csv", index_col=0, parse_dates=True)
    rep = json.loads((R / "multiasset/holdout/results.json").read_text())
    for c in ho.columns:
        add("multi-asset hold-out", c, "2018-01..2026-09", ho[c], note="excess returns as saved")
    pead = load(R / "pead_2004_2014/model.csv")
    add("PEAD hold-out", "pead_model", "2004..2014", pead, reported=0.52)
    ctl = load(R / "pead_2004_2014/all_events_control.csv")
    add("PEAD hold-out", "all_events_control", "2004..2014", ctl)
    for c in ["low_vol_long", "liquid_equal_weight", "defensive_momentum_blend", "residual_momentum", "low_beta_spread", "SPY_control"]:
        add("higher_sharpe evaluation", c, "2024-01..2025-06", load(R / f"higher_sharpe/{c}.csv", start="2024-01-02", end="2025-06-27"))
    for c in ["LQD_IEF", "EFA_EEM", "GLD_SLV", "SPY_QQQ", "fixed_blend"]:
        f = R / f"etf_convergence_20260918/{c}_base.csv"
        add("ETF convergence validation", c, "2014..2017", load(f, start="2014-01-01", end="2017-12-31"))
    for c in ["london_reversal", "new_york_continuation"]:
        f = R / f"fx_session_20260918/{c}_base_daily.csv"
        add("FX session validation", c, "2014..2017", load(f, start="2014-01-01", end="2017-12-31", subtract_rf=False),
            note="rf = 0 definition")
    crypto = json.loads((R / "multiasset/crypto/holdout_results.json").read_text())
    for name, v in crypto["all_candidates"].items():
        ci = sharpe_ci_iid(v["sharpe"], v["years"])
        rows.append({"family": "crypto hold-out", "result": name, "window": "2022..2026-09", "years": v["years"],
                     "sharpe": v["sharpe"], "reported": v["sharpe"], "ci95_lo": round(ci[0], 2), "ci95_hi": round(ci[1], 2),
                     "verdict": null_kind(ci, CONSEQUENTIAL), "rules_out_target_2": ci[1] < 2.0,
                     "note": "iid interval: daily series not saved"})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "null_audit.csv", index=False)
    print(df.drop(columns=["note"]).to_string(index=False))


if __name__ == "__main__":
    main()
