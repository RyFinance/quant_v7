# Momentum lab — shared harness

Every momentum variation runs through this harness so results are comparable across experiments.
**Do not modify `core.py`.** Copy a helper into your own module if you need to change behaviour, and
say so in your report.

## Use

```python
from pathlib import Path
from research.momentum_lab.core import Lab, stats, sharpe_interval
lab = Lab()
score = lab.close.shift(21) / lab.close.shift(252) - 1        # the frozen 12-1 rule
res = lab.run('my_variant', score, out=Path('reports/my_experiment_20260919'))
lab.show({'my_variant': res})                                  # prints comparators too
```

Run with `PYTHONPATH=. .venv/bin/python -m research.<your_module>` from `/Users/rytty/CCP/quant_v7`.
First `Lab()` builds a panel cache; later ones load in seconds.

## What the harness gives you

| | |
|---|---|
| `lab.open/close/volume` | 503 × 4958 daily frames, split-adjusted |
| `lab.member` | **point-in-time S&P 500 membership**, reconstructed from the dated changes ledger |
| `lab.eligible('pit')` | frozen filter: 252 sessions of history, ADV > $20m, top 200 by ADV, member on the date |
| `lab.eligible('cache')` | the biased universe, for contrast only — never a headline |
| `lab.sector`, `lab.factors` (FF5+UMD daily), `lab.spy`, `lab.rf` | |
| `lab.run(name, score, **kw)` | builds targets, runs the frozen execution engine at base and stress costs, returns stats for all three windows plus an FF5+UMD attribution |
| `lab.comparators` | SPMO, MTUM, SPY, RSP over identical windows |
| `sharpe_interval(r, lab.rf)` | 20-day circular block bootstrap 95% CI |

`lab.run` / `lab.targets` keywords: `slots` (default 20), `weight` `'equal'|'inv_vol'`,
`exposure` (Series in [0,1], scales gross at each decision date), `rebalance` `'M'|'W'`,
`sector_cap` (max names per GICS sector), `universe` `'pit'|'cache'`, `min_score` (default 0.0 —
positive momentum only; `None` disables).

Execution is the frozen engine: next-session open fills, daily marking, 5bps/side base and 15bps
stress, idle cash at the 13-week bill, long-only, no leverage, final liquidation charged.

## Windows

| | |
|---|---|
| `2011..2018` | first half |
| `2019..2026` | second half |
| `2011..2026` | full record |

Membership starts at 2011 because the public changes ledger thins before then (2 changes recorded in
2005, 1 in 2006, against 12–26 a year from 2011). Earlier windows are biased upward and are not
headline material.

## The bar

The baseline — frozen 12-1 rule on the point-in-time universe — is **16.95% / 0.67 Sharpe**
(2011–2026), 14.10% / 0.74 in the first half, 19.99% / 0.66 in the second, FF5+UMD alpha t = +0.03 (base cost).

The thing to beat is **SPMO at 0.84** (2011–2026), because anyone can buy it: 0.70 in the first half,
0.89 in the second. A variant only counts if it beats SPMO's Sharpe **in both halves**. Winning in
one half and losing the other is a null, and should be reported as one.

## Rules

1. Write `research/<your_experiment>/PLAN.md` listing the **exact** variants you will run, then
   register it before computing anything:
   `PYTHONPATH=. .venv/bin/python -m research.momentum_lab.register research/<x>/PLAN.md "<note>"`
2. Run exactly that list. No grid search, no adding a variant after seeing a result. A new idea needs
   an amendment file registered first, and the report must say it was an amendment.
3. **Do not install or upgrade any Python package.** The bot shares this environment.
4. Report every variant you ran, including the failures, with all three windows and the comparator
   rows. Report the stress-cost column for anything you call a win.
5. Write `reports/<your_experiment>_20260919/REPORT.md` and state plainly whether anything beat the
   bar. "Nothing beat SPMO" is a complete and valuable answer — the project has ~110 recorded trials
   and a deflated-Sharpe probability already below 0.5, so a manufactured winner costs more than it
   is worth.
