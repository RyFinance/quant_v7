"""The one hold-out run, 2018-01-01 to 2026-09-17, exactly as PREREGISTRATION_holdout.md says.

It refuses to run unless the pre-registration is registered (panel.holdout_unlocked)
and the code hashes match the ones written in it. Results go to reports/multiasset/holdout/.

Run: PYTHONPATH=. .venv/bin/python -m research.multiasset.holdout
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.multiasset import evaluate, panel, sleeves

OUT = evaluate.OUT / "holdout"
BOOK = ["fx_carry", "bond_carry", "vix_basis", "tsmom_broad", "overnight_intraday_reversal"]
ROUND3 = ["overnight_persistence", "intraday_persistence", "overnight_intraday_reversal"]
CODE_FILES = ["panel.py", "sleeves.py", "evaluate.py", "holdout.py"]


def file_hashes() -> dict[str, str]:
    here = Path(__file__).parent
    return {f: hashlib.sha256((here / f).read_bytes()).hexdigest() for f in CODE_FILES}


def check_registered() -> None:
    if not panel.holdout_unlocked():
        raise panel.HoldoutLocked("register PREREGISTRATION_holdout.md first")
    text = panel.HOLDOUT_PREREG.read_text()
    for f, h in file_hashes().items():
        if h not in text:
            raise RuntimeError(f"{f} changed since the pre-registration (sha256 {h[:12]}... not in it)")


def holdout_slice(r: pd.Series) -> pd.Series:
    return r[(r.index >= panel.HOLDOUT_START) & (r.index <= panel.HOLDOUT_END)]


def break_even_cost(res: pd.DataFrame) -> float:
    """One-way auction cost (bps) at which the round-3 sleeve's holdout net return is zero."""
    r = res.loc[(res.index >= panel.HOLDOUT_START) & (res.index <= panel.HOLDOUT_END)]
    per_unit = (r.gross_exposure * 2).sum()
    borrow = r.cost - r.gross_exposure * 2 * sleeves.AUCTION_COST
    return float((r.gross.sum() - borrow.sum()) / per_unit * 1e4) if per_unit else float("nan")


def main() -> dict:
    check_registered()
    OUT.mkdir(parents=True, exist_ok=True)
    end = panel.HOLDOUT_END
    rf = panel.risk_free(end)
    spy = panel.etf_returns(end)["SPY"] - rf

    full = {name: fn(end) for name, fn in sleeves.SLEEVES.items()}
    net = {name: evaluate.active(res) for name, res in full.items()}

    # primary: the pre-registered book, sleeves combined over their whole history, judged on the hold-out
    book = holdout_slice(evaluate.combine({k: net[k] for k in BOOK}))
    primary = evaluate.stats(book, rf, spy)

    sleeve_stats = {k: evaluate.stats(holdout_slice(v), rf, spy) for k, v in net.items()}

    # descriptive analyses named in the pre-registration
    desc = {}
    for c_bps in (1, 3):
        alt = sleeves.overnight_intraday_reversal(end, cost=c_bps / 1e4)
        alt_net = {**{k: net[k] for k in BOOK if k != "overnight_intraday_reversal"},
                   "overnight_intraday_reversal": evaluate.active(alt)}
        desc[f"book_auction_cost_{c_bps}bp"] = evaluate.stats(holdout_slice(evaluate.combine(alt_net)), rf, spy)
        for k in ROUND3:
            desc[f"{k}_at_{c_bps}bp"] = evaluate.stats(
                holdout_slice(evaluate.active(sleeves.SLEEVES[k](end, cost=c_bps / 1e4))), rf, spy)
    desc["break_even_one_way_bps"] = {k: round(break_even_cost(full[k]), 2) for k in ROUND3}
    macro = [k for k in BOOK if k not in ROUND3]
    desc["book_without_round3"] = evaluate.stats(holdout_slice(evaluate.combine({k: net[k] for k in macro})), rf, spy)
    tsm_best = "tsmom_broad"
    others = {k: v for k, v in net.items() if k not in sleeves.TSMOM_VARIANTS or k == tsm_best}
    desc["all_candidates"] = evaluate.stats(holdout_slice(evaluate.combine(others)), rf, spy)
    desc["spy"] = evaluate.stats(holdout_slice(spy), rf, spy)
    yearly = book.groupby(book.index.year).agg(lambda x: (1 + x).prod() - 1).round(4)
    desc["book_excess_by_year"] = {str(k): float(v) for k, v in yearly.items()}

    target = {"sharpe_at_least_2": primary.get("sharpe", 0) >= 2.0,
              "cagr_at_least_10pct": primary.get("cagr_total", 0) >= 0.10}
    passes = {"excess_mean_hac_t_at_least_2": primary.get("hac_t", 0) >= 2.0,
              "alpha_vs_spy_hac_t_at_least_2": primary.get("alpha_hac_t", 0) >= 2.0}
    result = {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "window": [str(panel.HOLDOUT_START.date()), str(end.date())],
              "book_sleeves": BOOK, "primary": primary, "pass_criteria": passes,
              "passed": all(passes.values()), "user_target": target, "sleeves": sleeve_stats,
              "descriptive": desc, "code_sha256": file_hashes()}
    (OUT / "results.json").write_text(json.dumps(result, indent=2))
    pd.DataFrame({"book": book, **{k: holdout_slice(net[k]) for k in BOOK}}).to_csv(OUT / "holdout_returns.csv")
    print(json.dumps({k: result[k] for k in ("primary", "pass_criteria", "passed", "user_target")}, indent=1))
    for k, v in sleeve_stats.items():
        print(f"{k:28s} sharpe {v.get('sharpe')}  ann {v.get('ann_excess')}  dd {v.get('max_dd')}")
    print(json.dumps(desc, indent=1))
    return result


if __name__ == "__main__":
    main()
