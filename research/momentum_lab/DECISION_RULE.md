# Selection rule for the momentum variation program

Registered 2026-09-19, **before any variant result was seen**. Five experiments are running in
parallel (volatility management, residual momentum, portfolio construction, an overlay control on
buyable funds, and a delisted-data feasibility check). Roughly 25 variants will be tested on history
this project has already mined. Without a rule fixed in advance, the best of 25 draws from noise will
look like a discovery. This file is that rule.

## What we already know

| | 2011–2018 | 2019–2026 | 2011–2026 |
|---|---:|---:|---:|
| Baseline 12-1, point-in-time universe | 14.10% / 0.74 | 19.99% / 0.66 | 16.95% / 0.67 |
| SPMO, buyable | 10.90% / 0.70 | 22.38% / 0.89 | 18.87% / 0.84 |
| MTUM, buyable | 14.02% / 0.92 | 16.94% / 0.67 | 15.69% / 0.73 |
| SPY | 11.21% / 0.78 | 17.30% / 0.78 | 14.16% / 0.77 |

The baseline's FF5+UMD alpha is +0.07%/yr, t = +0.03 at base cost (the figure first quoted, t = −0.27,
was fitted on the stress series through a harness bug found and fixed 2026-09-19 23:09): market beta
1.15, momentum beta 0.66, nothing left over.

Over their common history (October 2015 onward) the baseline book and SPMO differ by **+0.38% a year
with a 15.7% tracking error**, correlation 0.835. They are the same product. That gap has an
information ratio of 0.02; no forward test of any achievable length could tell them apart. Any
variant that merely nudges this book around is therefore not a finding, however good its backtest
looks.

## The rule

A variant earns a forward paper record only if **all six** hold. Nothing here earns capital.

1. **Beats SPMO's excess Sharpe in both halves** — above 0.70 in 2011–2018 *and* above 0.89 in
   2019–2026. One-half winners are nulls. This is the requirement that kills variants selected by a
   single regime.
2. **Still clears (1) at stress costs** (15bps per side).
3. **The full-window Sharpe's 95% bootstrap interval excludes the baseline's 0.67.** Beating it by a
   point estimate is not beating it.
4. **The mechanism was named in the plan before the result** — one of the published effects the
   experiments were registered to test. A construction tweak that works for no stated reason is a
   parameter draw, not a mechanism.
5. **Not generic market timing.** If the variant is an overlay, the overlay control's matrix must
   show it does *less* for SPMO, MTUM and SPY than it does for the stock book. An overlay that helps
   an ETF just as much is a recommendation to buy the ETF and apply the overlay there, at a fraction
   of the turnover.
6. **Deflated Sharpe probability above 0.5** against the updated trial ledger, which stands near 110
   registered trials and rises by one for every variant these five experiments run.

## What a failure means

Failing this rule is the expected outcome and is not a wasted run. The project has now tested roughly
110 strategies; the useful output of this program is a measured answer to "can a retail-scale
momentum book beat the momentum ETF", and "no" is that answer if that is what the evidence says.

If nothing passes, the recommendation is explicit: the buyable fund is the better implementation of
this factor, and the project's effort belongs somewhere the ETF cannot go — which, per
`reports/delisted_feasibility_20260919/`, may require the survivorship-free database.

## Multiplicity accounting

Every variant run under this program is appended to the trial ledger, including the ones that fail.
The deflated Sharpe for any candidate is computed against the full count, not against the count
within its own experiment.
