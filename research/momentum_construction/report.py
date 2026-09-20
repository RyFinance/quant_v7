"""Build reports/momentum_construction_20260919/REPORT.md from results.json. Numbers are never typed by hand."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'reports/momentum_construction_20260919'
W = ['2011..2018', '2019..2026', '2011..2026']
LABEL = {
    'C1_slots30': 'C1  30 slots',
    'C2_slots50': 'C2  50 slots',
    'C3_slots10': 'C3  10 slots',
    'C4_inv_vol': 'C4  inverse-vol weight',
    'C5_sector_cap4': 'C5  sector cap 4',
    'C6_weekly': 'C6  weekly rebalance',
    'C7_mom6_1': 'C7  6-1 momentum',
    'C8_rank_blend': 'C8  rank blend 3/6/12',
    'C9_high52': 'C9  52-week-high prox.',
    'C10_skip5': 'C10 5-day skip',
}


def main() -> None:
    d = json.loads((OUT / 'results.json').read_text())
    V, B, C = d['variants'], d['baseline_reference'], d['comparators']
    rows = [(LABEL[k], V[k]) for k in LABEL]

    def perf(key: str) -> str:
        L = [f'| variant | {" | ".join(W)} |', '|---|---|---|---|']
        for n, r in rows:
            L.append(f'| {n} | ' + ' | '.join(
                f'{r[key][w]["cagr"]*100:.2f}% / **{r[key][w]["sharpe"]:.2f}**' for w in W) + ' |')
        L.append('| | | | |')
        L.append('| *baseline 12-1, 20 slots* | ' + ' | '.join(
            f'{B[key][w]["cagr"]*100:.2f}% / {B[key][w]["sharpe"]:.2f}' for w in W) + ' |')
        for s in ['SPMO', 'MTUM', 'SPY', 'RSP']:
            L.append(f'| *{s}* | ' + ' | '.join(
                f'{C[s][w]["cagr"]*100:.2f}% / {C[s][w]["sharpe"]:.2f}' for w in W) + ' |')
        return '\n'.join(L)

    # risk / cost table
    navs = {k: pd.read_csv(OUT / f'{k}_nav.csv', index_col=0, parse_dates=True)['return'].loc['2011':]
            for k in LABEL}
    bnav = pd.read_csv(ROOT / 'reports/momentum_lab/baseline_12_1_nav.csv',
                       index_col=0, parse_dates=True)['return'].loc['2011':]
    corr = {k: pd.concat([bnav.rename('b'), v.rename('v')], axis=1).dropna().corr().iloc[0, 1]
            for k, v in navs.items()}
    risk = ['| variant | turnover /yr | vol | max DD | 5→15bps CAGR drag | 5→15bps Sharpe drag | corr to baseline |',
            '|---|---|---|---|---|---|---|']
    for n, r in rows:
        k = [x for x in LABEL if LABEL[x] == n][0]
        s, ss = r['base']['2011..2026'], r['stress']['2011..2026']
        risk.append(f'| {n} | {r["base"]["turnover"]:.2f}x | {s["vol"]*100:.1f}% | {s["max_dd"]*100:.1f}% | '
                    f'{(s["cagr"]-ss["cagr"])*100:.2f} pp | {s["sharpe"]-ss["sharpe"]:.3f} | {corr[k]:.3f} |')
    sb, sbs = B['base']['2011..2026'], B['stress']['2011..2026']
    risk.append(f'| *baseline* | {B["base"]["turnover"]:.2f}x | {sb["vol"]*100:.1f}% | {sb["max_dd"]*100:.1f}% | '
                f'{(sb["cagr"]-sbs["cagr"])*100:.2f} pp | {sb["sharpe"]-sbs["sharpe"]:.3f} | 1.000 |')
    for s in ['SPMO', 'SPY']:
        risk.append(f'| *{s}* | — | {C[s]["2011..2026"]["vol"]*100:.1f}% | '
                    f'{C[s]["2011..2026"]["max_dd"]*100:.1f}% | — | — | — |')

    # attribution
    att = ['| variant | alpha (ann.) | alpha t | MktRF | UMD | HML | RMW |', '|---|---|---|---|---|---|---|']
    for n, r in rows + [('*baseline*', B)]:
        a = r['attribution']
        att.append(f'| {n} | {a["alpha_annual"]*100:+.2f}% | {a["alpha_t"]:+.2f} | {a["MktRF"]:.2f} | '
                   f'{a["UMD"]:.2f} | {a["HML"]:+.2f} | {a["RMW"]:+.2f} |')

    # bootstrap intervals
    ci = ['| variant | full 2011–2026 | 2011–2018 | 2019–2026 |', '|---|---|---|---|']
    for n, r in rows + [('*baseline*', B)]:
        f, h = r['sharpe_ci_full'], r['sharpe_ci_halves']
        ci.append(f'| {n} | {r["base"]["2011..2026"]["sharpe"]:.2f}  [{f[0]:.2f}, {f[1]:.2f}] | '
                  f'{r["base"]["2011..2018"]["sharpe"]:.2f}  [{h["2011..2018"][0]:.2f}, {h["2011..2018"][1]:.2f}] | '
                  f'{r["base"]["2019..2026"]["sharpe"]:.2f}  [{h["2019..2026"][0]:.2f}, {h["2019..2026"][1]:.2f}] |')

    # both-halves verdict
    s1, s2 = C['SPMO']['2011..2018']['sharpe'], C['SPMO']['2019..2026']['sharpe']
    ver = [f'| variant | H1 vs SPMO {s1:.2f} | H2 vs SPMO {s2:.2f} | verdict |', '|---|---|---|---|']
    npass = 0
    for n, r in rows:
        a, b = r['base']['2011..2018']['sharpe'], r['base']['2019..2026']['sharpe']
        p1, p2 = a > s1, b > s2
        npass += p1 and p2
        v = 'PASS' if (p1 and p2) else ('null (wins H1 only)' if p1 else
                                        ('null (wins H2 only)' if p2 else 'fails both'))
        ver.append(f'| {n} | {a:.2f} {"✓" if p1 else "✗"} | {b:.2f} {"✓" if p2 else "✗"} | {v} |')
    a, b = B['base']['2011..2018']['sharpe'], B['base']['2019..2026']['sharpe']
    p1, p2 = a > s1, b > s2
    v = 'PASS' if (p1 and p2) else ('null (wins H1 only)' if p1 else
                                    ('null (wins H2 only)' if p2 else 'fails both'))
    ver.append(f'| *baseline* | {a:.2f} {"✓" if p1 else "✗"} | {b:.2f} {"✓" if p2 else "✗"} | {v} |')

    sh = np.array([r['base']['2011..2026']['sharpe'] for _, r in rows])
    shs = np.array([r['stress']['2011..2026']['sharpe'] for _, r in rows])
    h1 = np.array([r['base']['2011..2018']['sharpe'] for _, r in rows])
    h2 = np.array([r['base']['2019..2026']['sharpe'] for _, r in rows])
    cg = np.array([r['base']['2011..2026']['cagr'] for _, r in rows]) * 100
    best = rows[int(sh.argmax())]
    dist = dict(lo=sh.min(), med=float(np.median(sh)), hi=sh.max(), mean=sh.mean(),
                sd=sh.std(ddof=1), spread=float(np.ptp(sh)), slo=shs.min(), smed=float(np.median(shs)),
                shi=shs.max(), h1lo=h1.min(), h1hi=h1.max(), h2lo=h2.min(), h2hi=h2.max(),
                cglo=cg.min(), cghi=cg.max(), nabove=int((sh > B['base']['2011..2026']['sharpe']).sum()),
                bestname=best[0], bestsh=best[1]['base']['2011..2026']['sharpe'],
                bestci=best[1]['sharpe_ci_full'], npass=npass)

    tpl = (Path(__file__).parent / 'REPORT_TEMPLATE.md').read_text()
    txt = tpl.format(perf_base=perf('base'), perf_stress=perf('stress'), risk='\n'.join(risk),
                     att='\n'.join(att), ci='\n'.join(ci), ver='\n'.join(ver), **dist)
    (OUT / 'REPORT.md').write_text(txt)
    print(f'wrote {OUT}/REPORT.md ({len(txt)} chars)')


if __name__ == '__main__':
    main()
