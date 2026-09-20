# Treasury auction cycle (edge-graveyard C3): development result

Run 2026-09-19. Plan: `research/auction_cycle/PLAN.md` (registered 06:44:15-0700) and
`PLAN_AMENDMENT_1.md` (data mapping, registered before any return). Code: `research/auction_cycle/`,
tests `tests/test_auction_cycle.py` (8 pass). Raw output: `dev_results.json`, `dev_*_daily.csv`.

**Verdict: no candidate passes the development gate (net Sharpe >= 0.5). Validation (2020-2026-09)
was not run and stays locked; the PEAD correlation and blend were not computed (PEAD data sit only in
the validation window, per the plan).** This counts as three trials in the ledger.

## Setup

- 2/3/5/7/10/30-year nominal coupon auctions: LSE calendar, unioned with Treasury fiscaldata to fill 4
  missing dates (2015-02-25, 2016-03-08/09/10). After amendment 1 the two sources match exactly on
  every date and tenor they share. 345 auction dates in development.
- IEF daily excess over T-bills; w chosen at close i-1 earns day i; cost 2 bp per side on |dw|
  (stress 6 bp). Pre window = return days a-4..a; post = a+1..a+3.
- A1 short IEF over pre windows; A2 long IEF over post days that are not pre days; A3 = A1 + A2.
- Bond prices 2015+ were seen earlier by the multi-asset tests (a different signal). The development
  window is 5 years, so the intervals are wide.

## Development, 2015-01-02 to 2019-12-31 (1,258 days)

| | A1 pre short | A2 post long | A3 combined |
|---|---|---|---|
| Net Sharpe (base, 2 bp) | **-0.23** | **0.03** | **-0.18** |
| 95% CI (21-day block) | [-1.06, 0.57] | [-0.76, 0.83] | [-0.95, 0.57] |
| null_kind at 0.5 | vacuous | vacuous | vacuous |
| Gross Sharpe | -0.01 | 0.36 | 0.20 |
| Stress Sharpe (6 bp) | -0.68 | -0.65 | -0.93 |
| One-sided p | 0.72 | 0.47 | 0.69 |
| Deflated Sharpe (65 trials) | 0.11 | 0.25 | 0.13 |
| Annual return / vol | -0.97% / 4.2% | 0.07% / 2.8% | -0.90% / 5.0% |
| Max drawdown | -9.8% | -3.7% | -10.2% |
| Cost drag per year | 0.95% | 0.94% | 1.89% |
| Active days / entries | 832 / 118 | 325 / 118 | 1,157 / 236 |
| Net bp per entry | -4.1 | +0.3 | -1.9 |
| Passes dev gate | no | no | no |

Net return by year:

| Year | A1 | A2 | A3 |
|---|---|---|---|
| 2015 | -0.5% | -0.4% | -0.9% |
| 2016 | -1.2% | -0.1% | -1.3% |
| 2017 | +0.7% | +1.9% | +2.6% |
| 2018 | +2.5% | +1.1% | +3.6% |
| 2019 | -6.4% | -2.3% | -8.6% |

Descriptive (not gated): one-day-late entry, Sharpe -0.41 / -0.19 / -0.44. The TLT version:
0.05 / 0.31 / 0.21 net. IEF buy-and-hold excess Sharpe over the window: 0.36.

## Event study (mean IEF excess return, bp, development)

| Day | -5 | -4 | -3 | -2 | -1 | 0 | +1 | +2 | +3 | +4 | +5 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| All auctions (n=345) | +1.2 | +1.9 | +1.6 | -0.7 | -0.9 | -2.3 | +0.8 | 0.0 | +1.5 | +0.2 | +0.9 |
| 10-year (n=60) | +1.0 | +7.6 | -4.4 | -3.8 | -5.7 | -0.3 | -4.6 | -0.5 | -0.8 | -4.2 | +5.5 |

Across all auctions the shape is weakly like LYZ's: a dip on days -2..0 of about 4 bp and a small
recovery afterwards. But days -4..-3 are positive, so the registered -4..0 window nets out to about 0
gross. Each round trip costs about 4 bp, which is the size of the whole effect; this matches the
paper's own finding that short windows lose money after costs. The 10-year pattern is too noisy
(n = 60) to read.

## Interpretation

- Under these rules, 2015-2019 gives no evidence of a tradable auction cycle in IEF. Gross returns
  are near zero (A1) to weakly positive (A2/A3, 0.2-0.36), and costs remove them.
- The intervals are wide (+/-0.8). The development window cannot rule out a true Sharpe of 0.5; this
  is a failed screen, not a bounded null.
- The results for 2017-2018 (rising yields) are positive and 2019 (falling yields) is strongly
  negative. The duration trend, not auction timing, drives the yearly pattern.
- No tuning follows from this. The narrower -2..0 window in the event study is a post-hoc
  observation and is not a new candidate. Any retest must be a fresh registration on forward data.
