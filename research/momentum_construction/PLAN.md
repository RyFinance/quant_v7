# PLAN — momentum signal definition and portfolio construction

Registered before any result is computed. Date: 2026-09-19.

## Question

The frozen baseline (12-1 momentum, 20 slots, equal weight, monthly rebalance, no sector
constraint, `min_score=0.0`) scores 16.95% / 0.67 Sharpe over 2011–2026. Every one of those five
construction choices is arbitrary. This experiment asks two things:

1. Was any of them *badly* chosen — i.e. does a neighbouring choice move the result materially?
2. How wide is the spread of outcomes across reasonable choices? That spread, not the maximum, is
   the honest measure of how fragile the 0.67 is.

## Harness

`research/momentum_lab/core.py`, unmodified. Point-in-time S&P 500 universe (`universe='pit'`),
frozen execution engine, base 5bps/side and stress 15bps/side, windows 2011..2018, 2019..2026,
2011..2026. Everything not named below is left at the harness default.

## Variants — exactly these ten, no others

Breadth and weighting (12-1 score, monthly, `min_score=0.0`):

| id | change | call |
|---|---|---|
| C1 | 30 slots | `slots=30` |
| C2 | 50 slots | `slots=50` |
| C3 | 10 slots | `slots=10` |
| C4 | inverse-volatility weighting, 20 slots | `weight='inv_vol'` |
| C5 | GICS sector cap of 4 names, 20 slots | `sector_cap=4` |

Rebalance frequency:

| id | change | call |
|---|---|---|
| C6 | weekly rebalance, 20 slots | `rebalance='W'` |

Signal definition (20 slots, monthly, equal weight):

| id | score |
|---|---|
| C7 | 6-1 momentum: `close.shift(21) / close.shift(126) - 1` |
| C8 | blended momentum: mean of cross-sectional ranks of 3-1, 6-1 and 12-1, ranked within the eligible set at each decision date |
| C9 | 52-week-high proximity (George & Hwang 2004): `close / close.rolling(252).max()`, with `min_score=None` |
| C10 | shorter skip: `close.shift(5) / close.shift(252) - 1` |

Notes fixed in advance:

- C6: turnover will rise sharply (baseline ≈7.8x/yr). The report will state realised turnover, the
  base-vs-stress Sharpe drag, and the break-even cost per side implied by that drag.
- C8: ranks are computed on the eligible set at each decision date, averaged across the three
  horizons, then passed as the score. Because an average of percentile ranks is bounded in (0,1] and
  therefore always positive, the `min_score=0.0` screen would not bind; C8 uses
  `min_score=None` and the report states that C8, like C9, carries no positive-momentum screen.
  (Naming it here, before running, so it is not a post-hoc choice.)
- C9: `close / rolling(252).max()` is bounded near 1, so `min_score=0.0` would filter nothing;
  C9 uses `min_score=None` and the report states that this variant has no positive-momentum screen.

## Analysis, fixed in advance

1. All ten reported across all three windows at base and stress cost, with SPMO / MTUM / SPY / RSP
   comparator rows and the baseline row, plus turnover, annualised volatility, maximum drawdown and
   the FF5+UMD attribution (alpha, t, UMD loading).
2. The **distribution** of the ten full-window Sharpes (min, median, max, spread) is the headline,
   not the maximum.
3. For the single best full-window variant: `sharpe_interval` 95% block bootstrap, stated against
   the baseline's 0.67 and SPMO's 0.84.
4. Both-halves consistency is required. A variant beating SPMO in one half and not the other is
   reported as a null.
5. **No follow-up tuning.** If a variant looks good, no neighbouring parameter will be tried. Any
   additional variant requires a registered amendment and must be labelled as one in the report.
6. Multiplicity is acknowledged up front: the project ledger already holds ~110 registered trials
   with deflated-Sharpe probability below 0.5. Ten more shots at the same history are expected to
   produce an apparent winner by chance; the report will say so.

## Deliverables

`reports/momentum_construction_20260919/REPORT.md`, per-variant daily NAV CSVs, and `results.json`.
