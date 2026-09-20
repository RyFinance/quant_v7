# Pre-registered test: the production PEAD model on 2004–2014

Rules fixed in `research/PREREGISTRATION_pead_2004_2014.md`, registered 2026-09-17T18:44:54-0700, before any
result existed; Amendment 1 moved prices to yfinance official daily bars, also before any result.
The model was never refit. Prices and SPY: yfinance, split- and dividend-adjusted.

**Outcome: FAIL**

| Criterion | Result |
|---|---|
| alpha hac t at least 2 | fail |
| beats all events control | fail |
| positive alpha both halves | pass |

17,037 events scored, 5,604 traded by the model, 459 tickers with prices.

| Portfolio | CAGR | Vol | Excess Sharpe | Max DD | Beta | Alpha/yr | Alpha HAC t |
|---|---:|---:|---:|---:|---:|---:|---:|
| Model (live config: 5% / 100% gross) | 7.51% | 12.69% | 0.52 | -24.9% | 0.54 | 2.26% | 1.12 |
| All-events control | 4.54% | 9.79% | 0.36 | -21.7% | 0.38 | 0.41% | 0.23 |

| Half | Model alpha/yr | Model alpha t | Control alpha/yr |
|---|---:|---:|---:|
| 2004-2008 | 4.46% | 1.53 | 1.27% |
| 2009-2014 | 1.23% | 0.44 | -0.75% |

Model minus control excess Sharpe, 63-day block bootstrap 95%: [-0.18, 0.56].

## Reading it

- The universe is today's S&P 500, which biases returns **upward** (failures and delistings are
  missing). A fail is therefore robust; a pass is necessary but not sufficient.
- Execution is next-open, more conservative than the live bot's same-close fill.
- The circuit breaker is not replayed (no calibrated history before 2015).

Reproduce: `PYTHONPATH=. .venv/bin/python -m research.pead_2004_2014`
