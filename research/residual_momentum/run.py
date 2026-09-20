"""Run the pre-registered residual momentum experiment (research/residual_momentum/PLAN.md)."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

from research.momentum_lab.core import Lab, WINDOWS, sharpe_interval
from research.residual_momentum import scores as S

OUT = Path('/Users/rytty/CCP/quant_v7/reports/residual_momentum_20260919')

VARIANTS = [
    ('R1_capm_residual', dict(factors=('MktRF',), standardise=False)),
    ('R2_ff3_residual', dict(factors=('MktRF', 'SMB', 'HML'), standardise=False)),
    ('R3_ff3_residual_std', dict(factors=('MktRF', 'SMB', 'HML'), standardise=True)),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lab = Lab()

    # --- fast-path verification against a slow per-stock loop -------------------------------
    checks = {}
    for name, kw in VARIANTS:
        c = S.verify(lab, n_checks=6, seed=7, **kw)
        checks[name] = [{'date': d, 'ticker': t, 'fast': f, 'slow': s, 'abs_diff': e}
                        for d, t, f, s, e in c]
        print(f'verify {name}: max abs diff {max(x[4] for x in c):.3e} over {len(c)} stock-months')

    # --- scores ------------------------------------------------------------------------------
    sc = {name: S.residual_scores(lab, **kw) for name, kw in VARIANTS}
    sc['R4_risk_adj_raw'] = S.risk_adjusted_raw(lab)

    dec = lab.dates[lab.decision['M'].to_numpy() & (lab.dates >= '2011-01-01')]
    elig = lab.eligible('pit')
    diag = {}
    for name, s in sc.items():
        d = s.loc[dec].where(elig.loc[dec])
        diag[name] = {'mean_eligible_scored': float(d.notna().sum(1).mean()),
                      'mean_positive': float((d > 0).sum(1).mean()),
                      'dates_under_20_positive': int(((d > 0).sum(1) < 20).sum()),
                      'n_decision_dates': int(len(dec))}
        print(name, diag[name])

    # --- runs ---------------------------------------------------------------------------------
    results, navs = {}, {}
    for name in ['R1_capm_residual', 'R2_ff3_residual', 'R3_ff3_residual_std', 'R4_risk_adj_raw']:
        print('running', name, flush=True)
        res = lab.run(name, sc[name], out=OUT)
        navs[name] = lab.nav
        r = lab.nav['return']
        res['sharpe_ci'] = {w: (lambda ci: {'lo': float(ci[0]), 'hi': float(ci[1])})(
            sharpe_interval(r.loc[a:b], lab.rf)) for w, (a, b) in WINDOWS.items()}
        results[name] = res
        for w in WINDOWS:
            s = res['base'][w]
            print(f'   {w}: cagr {s["cagr"]*100:6.2f}%  sharpe {s["sharpe"]:5.2f}  '
                  f'vol {s["vol"]*100:5.2f}%  maxdd {s["max_dd"]*100:7.2f}%  '
                  f'ci [{res["sharpe_ci"][w]["lo"]:.2f}, {res["sharpe_ci"][w]["hi"]:.2f}]')
        print(f'   alpha_t {res["attribution"]["alpha_t"]:.2f}  mkt {res["attribution"]["MktRF"]:.2f}  '
              f'umd {res["attribution"]["UMD"]:.2f}  turnover {res["base"]["turnover"]:.2f}', flush=True)

    lab.show(results)

    # --- comparator Sharpe intervals and baseline correlation ---------------------------------
    import research.momentum_verification.benchmarks as bm
    comp_ci = {}
    for sym in ['SPMO', 'MTUM', 'SPY', 'RSP']:
        r = bm.etf_returns(sym)
        comp_ci[sym] = {w: (lambda ci: {'lo': float(ci[0]), 'hi': float(ci[1])})(
            sharpe_interval(r.loc[a:b], lab.rf)) for w, (a, b) in WINDOWS.items()}

    base_nav = pd.read_csv('/Users/rytty/CCP/quant_v7/reports/momentum_lab/baseline_12_1_nav.csv',
                           index_col=0, parse_dates=True)
    corr = {n: float(navs[n]['return'].corr(base_nav['return'])) for n in navs}
    print('correlation of daily returns with the 12-1 baseline:', corr)

    payload = {'plan': 'research/residual_momentum/PLAN.md', 'windows': WINDOWS,
               'verification': checks, 'score_diagnostics': diag, 'results': results,
               'comparators': lab.comparators, 'comparator_sharpe_ci': comp_ci,
               'baseline_12_1': json.load(open('/Users/rytty/CCP/quant_v7/reports/momentum_lab/baseline.json')),
               'corr_with_baseline': corr}
    (OUT / 'results.json').write_text(json.dumps(payload, indent=2, default=str))
    print('wrote', OUT / 'results.json')


if __name__ == '__main__':
    main()
