"""Momentum construction sweep — the ten pre-registered variants in research/momentum_construction/PLAN.md.

Run:  PYTHONPATH=. .venv/bin/python -m research.momentum_construction.run
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.momentum_lab.core import Lab, WINDOWS, sharpe_interval

OUT = Path(__file__).resolve().parents[2] / 'reports/momentum_construction_20260919'


def main() -> None:
    t0 = time.time()
    lab = Lab()
    OUT.mkdir(parents=True, exist_ok=True)
    c = lab.close

    mom12_1 = c.shift(21) / c.shift(252) - 1      # the frozen baseline rule
    mom6_1 = c.shift(21) / c.shift(126) - 1
    mom3_1 = c.shift(21) / c.shift(63) - 1
    elig = lab.eligible('pit')
    blend = sum(x.where(elig).rank(axis=1, pct=True) for x in (mom3_1, mom6_1, mom12_1)) / 3.0
    high52 = c / c.rolling(252).max()
    skip5 = c.shift(5) / c.shift(252) - 1

    specs = [
        ('C1_slots30', mom12_1, dict(slots=30)),
        ('C2_slots50', mom12_1, dict(slots=50)),
        ('C3_slots10', mom12_1, dict(slots=10)),
        ('C4_inv_vol', mom12_1, dict(weight='inv_vol')),
        ('C5_sector_cap4', mom12_1, dict(sector_cap=4)),
        ('C6_weekly', mom12_1, dict(rebalance='W')),
        ('C7_mom6_1', mom6_1, dict()),
        ('C8_rank_blend', blend, dict(min_score=None)),
        ('C9_high52', high52, dict(min_score=None)),
        ('C10_skip5', skip5, dict()),
    ]

    results = {}
    for name, score, kw in specs:
        t = time.time()
        res = lab.run(name, score, out=OUT, **kw)
        nav = pd.read_csv(OUT / f'{name}_nav.csv', index_col=0, parse_dates=True)
        r = nav['return'].loc['2011-01-01':].dropna()
        res['sharpe_ci_full'] = list(sharpe_interval(r, lab.rf))
        for w, (a, b) in WINDOWS.items():
            if w != '2011..2026':
                res.setdefault('sharpe_ci_halves', {})[w] = list(sharpe_interval(r.loc[a:b], lab.rf))
        results[name] = res
        s = res['base']['2011..2026']
        print(f'{name:18s} full {s["cagr"]*100:6.2f}%/{s["sharpe"]:5.2f} '
              f'turn {res["base"]["turnover"]:5.2f}x  ci {res["sharpe_ci_full"][0]:.2f}..'
              f'{res["sharpe_ci_full"][1]:.2f}  [{time.time()-t:.0f}s]', flush=True)

    # reference rows: frozen baseline (already published, not a new trial) + comparators
    base_json = json.loads((Path(__file__).resolve().parents[2]
                            / 'reports/momentum_lab/baseline.json').read_text())
    bnav = pd.read_csv(Path(__file__).resolve().parents[2] / 'reports/momentum_lab/baseline_12_1_nav.csv',
                       index_col=0, parse_dates=True)
    br = bnav['return'].loc['2011-01-01':].dropna()
    base_json['sharpe_ci_full'] = list(sharpe_interval(br, lab.rf))
    base_json['sharpe_ci_halves'] = {w: list(sharpe_interval(br.loc[a:b], lab.rf))
                                     for w, (a, b) in WINDOWS.items() if w != '2011..2026'}

    # sector coverage diagnostic for C5
    elig_any = elig.any(axis=0)
    missing = [t for t in elig_any.index[elig_any] if not isinstance(lab.sector.get(t), str)]

    payload = {'variants': results, 'baseline_reference': base_json,
               'comparators': lab.comparators,
               'diagnostics': {'eligible_tickers_ever': int(elig_any.sum()),
                               'eligible_without_gics_sector': len(missing),
                               'missing_sector_examples': missing[:15]},
               'generated': pd.Timestamp.now().isoformat(), 'elapsed_s': round(time.time() - t0, 1)}
    (OUT / 'results.json').write_text(json.dumps(payload, indent=2, default=float))

    print()
    lab.show(results)
    print(f'\nwrote {OUT}/results.json in {time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
