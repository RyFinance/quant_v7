"""Crash-protected / volatility-managed momentum overlays on the frozen 12-1 book.

Pre-registered in research/vol_managed_momentum/PLAN.md (sha256 7727267...), registered
2026-09-19T23:03:25-0700. Runs exactly the five variants listed there and nothing else.

    PYTHONPATH=. .venv/bin/python -m research.vol_managed_momentum.run
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from research.momentum_lab.core import Lab, WINDOWS, stats, sharpe_interval

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'reports/vol_managed_momentum_20260919'
WARM_START = '2009-01-01'
LIVE_START = '2011-01-01'
END = '2026-09-17'
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:7.1f}s]', *a, flush=True)


# ---------------------------------------------------------------- exposures
def build_exposures(strategy_returns: pd.Series, spy: pd.Series,
                    decision_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """All five exposure series, each using ONLY data through session t-1.

    strategy_returns: daily returns of the UNSCALED baseline book (warm-up run).
    spy:              SPY close, daily.
    decision_dates:   monthly decision dates the harness will look up.
    """
    r = strategy_returns.dropna().sort_index()
    past = r.shift(1)                      # value at t is the return of t-1

    # V1 / V2 -- Barroso & Santa-Clara constant-volatility scaling
    sigma = past.rolling(126).std() * np.sqrt(252)
    v1 = (0.20 / sigma).clip(upper=1.0)
    v2 = (0.15 / sigma).clip(upper=1.0)

    # V3 -- Daniel & Moskowitz market-state gate
    sp = spy.dropna().sort_index()
    above = (sp > sp.rolling(200).mean()).astype(float)
    v3 = above.shift(1)                    # state as of t-1

    # V5 -- Moreira & Muir inverse variance, expanding-window normaliser
    raw = 1.0 / past.rolling(21).var()
    raw_dec = raw.reindex(decision_dates)
    norm = raw_dec.expanding(min_periods=24).mean()
    v5 = (raw_dec / norm).clip(upper=1.0)

    e = pd.DataFrame(index=decision_dates)
    e['V1'] = v1.reindex(decision_dates)
    e['V2'] = v2.reindex(decision_dates)
    e['V3'] = v3.reindex(decision_dates)
    e['V5'] = v5
    e['V4'] = e['V1'] * e['V3']
    e = e[['V1', 'V2', 'V3', 'V4', 'V5']].clip(lower=0.0, upper=1.0).fillna(1.0)
    return e


# ---------------------------------------------------------------- causality
def causality_test(lab, base_returns, decision_dates, cut='2018-06-29') -> dict:
    """Perturb everything strictly after `cut`; exposures on or before `cut` must not move."""
    cut = pd.Timestamp(cut)
    ref = build_exposures(base_returns, lab.spy, decision_dates)

    r2 = base_returns.copy()
    fut = r2.index > cut
    r2[fut] = r2[fut] * 3.0 + 0.05                      # blow up all future strategy returns
    sp2 = lab.spy.copy()
    sfut = sp2.index > cut
    sp2[sfut] = sp2[sfut] * 3.0                          # and all future SPY prices
    alt = build_exposures(r2, sp2, decision_dates)

    keep = decision_dates[decision_dates <= cut]
    a, b = ref.loc[keep], alt.loc[keep]
    identical = bool((a.to_numpy() == b.to_numpy()).all())
    moved_after = {c: float(np.nanmax(np.abs(
        ref.loc[decision_dates > cut, c].to_numpy() - alt.loc[decision_dates > cut, c].to_numpy())))
        for c in ref.columns}
    worst = {c: float(np.nanmax(np.abs(a[c].to_numpy() - b[c].to_numpy()))) for c in ref.columns}
    return {'cut': str(cut.date()), 'decision_dates_checked': int(len(keep)),
            'identical_before_cut': identical, 'max_abs_diff_before_cut': worst,
            'max_abs_diff_after_cut': moved_after}


# ---------------------------------------------------------------- main
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lab = Lab()
    log('lab loaded')

    score = lab.close.shift(21) / lab.close.shift(252) - 1     # frozen 12-1 rule
    results, meta = {}, {}

    # --- unscaled baseline, headline window
    base = lab.run('B_baseline', score, out=OUT)
    base_nav = lab.nav.copy()
    log('baseline done', base['base']['2011..2026']['sharpe'])

    # --- warm-up execution of the SAME targets, diagnostic only: seeds the trailing windows
    t_unscaled = lab.targets(score)
    warm = lab.execute(t_unscaled, stress=False, start=WARM_START)
    warm_ret = warm['return']
    log('warm-up done', warm_ret.index[0].date(), '->', warm_ret.index[-1].date(), len(warm_ret))

    dec = pd.DatetimeIndex(lab.dates[lab.decision['M']])
    dec = dec[(dec >= warm_ret.index[0]) & (dec <= pd.Timestamp(END))]

    # --- causality test BEFORE anything is executed with an exposure
    caus = causality_test(lab, warm_ret, dec)
    log('causality test:', caus['identical_before_cut'], caus['max_abs_diff_before_cut'])
    if not caus['identical_before_cut']:
        raise SystemExit('CAUSALITY TEST FAILED -- exposures depend on future data')

    exposures = build_exposures(warm_ret, lab.spy, dec)
    exposures.to_csv(OUT / 'exposures.csv')
    live = exposures.loc[LIVE_START:]
    log('avg exposure 2011+:', {c: round(float(live[c].mean()), 4) for c in live.columns})

    results['B_baseline'] = base
    meta['B_baseline'] = {'avg_exposure': 1.0, 'n_decisions': int(len(live))}

    for v in ['V1', 'V2', 'V3', 'V4', 'V5']:
        e = exposures[v]
        res = lab.run(v, score, out=OUT, exposure=e)
        nav = lab.nav.copy()
        res['attribution_base'] = lab.attribution(nav['return'].loc[LIVE_START:])
        results[v] = res
        meta[v] = {'avg_exposure': float(live[v].mean()),
                   'median_exposure': float(live[v].median()),
                   'min_exposure': float(live[v].min()),
                   'frac_at_cap': float((live[v] >= 0.999).mean()),
                   'frac_at_zero': float((live[v] <= 1e-9).mean()),
                   'mean_daily_gross': float(nav['gross'].mean()),
                   'n_decisions': int(len(live))}
        log(v, 'base sharpe', {w: round(res['base'][w]['sharpe'], 3) for w in WINDOWS},
            'avg_exp', round(meta[v]['avg_exposure'], 3))

    results['B_baseline']['attribution_base'] = lab.attribution(base_nav['return'].loc[LIVE_START:])

    # --- bootstrap Sharpe intervals on every variant (cheap, and needed for any claimed win)
    navs = {'B_baseline': base_nav['return']}
    for v in ['V1', 'V2', 'V3', 'V4', 'V5']:
        navs[v] = pd.read_csv(OUT / f'{v}_nav.csv', parse_dates=['date']).set_index('date')['return']
    ci = {}
    for n, r in navs.items():
        ci[n] = {w: list(sharpe_interval(r.loc[a:b], lab.rf)) for w, (a, b) in WINDOWS.items()}
        log('ci', n, {w: [round(x, 3) for x in ci[n][w]] for w in WINDOWS})

    # --- dilution control: baseline blended with T-bills at each variant's average exposure
    rfd = lab.rf_daily.reindex(base_nav.index).fillna(0.0)
    dilution = {}
    for v in ['V1', 'V2', 'V3', 'V4', 'V5']:
        a = meta[v]['avg_exposure']
        blend = a * base_nav['return'] + (1 - a) * rfd
        dilution[v] = {'exposure': a,
                       **{w: stats(blend.loc[s:e2], lab.rf) for w, (s, e2) in WINDOWS.items()},
                       'ci': {w: list(sharpe_interval(blend.loc[s:e2], lab.rf))
                              for w, (s, e2) in WINDOWS.items()}}
        blend.rename('return').to_frame().to_csv(OUT / f'dilution_{v}_nav.csv')
        log('dilution', v, 'a=', round(a, 3),
            {w: round(dilution[v][w]['sharpe'], 3) for w in WINDOWS})

    comp = lab.comparators
    comp_ci = {}
    import research.momentum_verification.benchmarks as bm
    for sym in ['SPMO', 'MTUM', 'SPY', 'RSP']:
        r = bm.etf_returns(sym)
        comp_ci[sym] = {w: list(sharpe_interval(r.loc[a:b], lab.rf)) for w, (a, b) in WINDOWS.items()}

    payload = {'plan': 'research/vol_managed_momentum/PLAN.md',
               'plan_sha256': '77272677a988ff3eebe800e65ca07713c84e20d48f9877dd5d6e4489d7c5bda8',
               'registered_at': '2026-09-19T23:03:25-0700',
               'windows': {k: list(v) for k, v in WINDOWS.items()},
               'causality_test': caus, 'results': results, 'exposure_meta': meta,
               'sharpe_ci': ci, 'dilution_control': dilution,
               'comparators': comp, 'comparator_ci': comp_ci}
    (OUT / 'results.json').write_text(json.dumps(payload, indent=2, default=float))
    log('wrote', OUT / 'results.json')

    print()
    lab.show(results)
    print()
    lab.show(results, key='stress')


if __name__ == '__main__':
    main()
