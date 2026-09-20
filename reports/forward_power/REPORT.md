# How long must a forward paper test run?

This is the probability that a forward paper test rejects "Sharpe = 0" (one-sided, 5%) when the
strategy's true annual Sharpe is as shown. It uses the iid approximation SE(Sharpe) ≈ 1/√years,
with daily data and no autocorrelation.

| True Sharpe | 0.25 yr | 0.5 yr | 1 yr | 2 yr | 3 yr | 5 yr | Years for 80% power |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0.5 | 8% | 10% | 13% | 17% | 22% | 30% | 24.7 |
| 0.75 | 10% | 13% | 19% | 28% | 36% | 51% | 11.0 |
| 1 | 13% | 17% | 26% | 41% | 53% | 72% | 6.2 |
| 1.5 | 19% | 28% | 44% | 68% | 83% | 96% | 2.7 |
| 2 | 26% | 41% | 64% | 88% | 97% | 100% | 1.5 |
| 3 | 44% | 68% | 91% | 100% | 100% | 100% | 0.7 |

Short-volatility returns are skewed and fat-tailed. For daily skew −3 and kurtosis 30 (typical of
short-dated put writing), the standard error of the Sharpe grows by the factor shown (Mertens / Lo):

| True Sharpe | SE multiplier | Years for 80% power |
|---|---:|---:|
| 0.5 | 1.05 | 27.2 |
| 0.75 | 1.08 | 12.7 |
| 1 | 1.10 | 7.5 |
| 1.5 | 1.16 | 3.7 |
| 2 | 1.22 | 2.3 |
| 3 | 1.35 | 1.3 |

## What this means

- A forward test can only confirm big edges quickly. A true Sharpe of 2 is detected with 80% power in
  about 1.5 years; a Sharpe of 3 in about 8 months.
- A true Sharpe of 0.5 needs about 25 years. No forward test will ever confirm a modest premium.
  Those decisions rest on the literature, the pre-registered history test and costs, and the
  forward test only checks that the implementation behaves as backtested (slippage, fills, turnover).
- Rule for this project: a candidate that passes validation gets a forward paper test sized small.
  Promotion to capital needs (a) forward costs and fills matching the backtest's assumptions within
  their stress band and (b) a forward Sharpe interval that does not exclude the backtest estimate.
  Nobody should expect significance from a few months of paper trading.
