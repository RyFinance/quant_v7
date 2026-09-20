# COT positioning premiums: development result (stopped at the gate)

Plan: `research/cot/PLAN.md` (registered 2026-09-18 13:24 PDT, before any commodity price was loaded).
Development window: weekly entries 2015-01 → 2019-12, 11 commodity ETFs, legs of 3, gross 2.0.
**No candidate reached the development gate (net Sharpe ≥ 0.5). The validation window 2020–2026 was
not run and stays untouched for these signals.**

| Candidate | Gross Sharpe | Net Sharpe | 95% interval | Stress Sharpe | Turnover/yr | Cost drag/yr | Max DD |
|---|---:|---:|---|---:|---:|---:|---:|
| C1 liquidity (fade speculators' weekly net buying) | 0.94 | 0.25 | [−0.60, 0.99] | −1.29 | 126× | 13.2% | −36% |
| C2 hedging pressure (52-week) | 0.40 | 0.33 | [−0.45, 1.14] | 0.04 | 5× | 1.3% | −32% |
| C3 both premiums | 0.56 | 0.05 | [−0.65, 0.72] | −1.13 | 84× | 9.2% | −31% |

## Reading

- The Kang–Rouwenhorst–Tang liquidity premium **is visible gross** (0.94) in 2015–2019. The signal
  flips most of the book every week, and with ETF spreads the costs take about three quarters of it.
  Its yearly net path also decays: +24% (2015), +4%, +6%, −10%, −6% (2019).
- All three are vacuous nulls: the intervals neither establish nor exclude a Sharpe of 0.5.

## Not done, and why

A futures-cost version of C1 (about 2–3 bps a side) would look better in development. Registering it
now would be a choice made after seeing these results, so it would have to be declared as a new,
data-informed experiment tested only on 2020–2026. A 6-position weekly long/short futures book is also
lumpy for a $100k account (gold, copper, RBOB and Brent contracts are $70k–$300k notional). That
decision is left to the user and was not made here.

Reproduce: `PYTHONPATH=. .venv/bin/python -m research.cot.evaluate dev`; tests: `tests/test_cot.py`.
