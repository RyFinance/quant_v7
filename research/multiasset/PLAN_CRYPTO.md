# Crypto trend: protocol

Written 2026-09-18, after the multi-asset book failed its hold-out
(`reports/multiasset/REPORT.md`) and **before any crypto strategy return was computed**. Crypto is
the one dataset this project has never touched.

## Data and universe

- **BTC and ETH only**, from vault daily UTC bars (from 2017-08-17). BTC before that date comes
  from yfinance BTC-USD (from 2014-09-17).
- Alt coins are excluded. The vault lists only coins alive today (no LUNA, FTT and so on), and
  most start in 2019–2020, so any cross-section of them is survivorship-biased and thin.
- Crypto trades every day. Returns are daily UTC close to close, annualized with 365. The T-bill
  rate (^IRX, accrued over calendar days) is the risk-free rate.

## Windows

| Window | Dates |
|---|---|
| Development | data start → **2021-12-31** |
| Hold-out | **2022-01-01 → 2026-09-17**, locked until `PREREGISTRATION_crypto_holdout.md` is registered |

## Candidates (literature parameters, fixed now)

All three scale each coin to 40% annualized ex-ante volatility (EWMA of squared returns, 60-day
centre of mass, annualized with 365) and average across the coins alive.

- **K1 `crypto_tsmom_1w`.** Liu and Tsyvinski (2021). Each week, at the Sunday UTC close, go long
  a coin whose past 7-day return is positive and short one whose return is negative.
- **K2 `crypto_tsmom_multi`.** Hurst, Ooi and Pedersen (2017), the same rule as round 2. Each
  month-end, hold the average of the signs of the past 30-, 91- and 365-day returns.
- **K3 `crypto_trend_long_only`.** K2's signal floored at zero: long or flat, never short. This is
  implementable in spot with no shorting.

## Execution and costs

- A position decided at the close of day *t* earns returns from the close of *t+1* onward.
- **One-way cost:** 10 bps.
- **Shorts:** 3% a year borrow.

## Inclusion and hold-out test

A candidate needs a development Sharpe ≥ 0.30 over at least 3 years. Of those that pass, **the
single one with the highest development Sharpe** goes to the hold-out, because the three are
near-duplicates.

**Hold-out pass criterion:** the HAC t-statistic (20 lags) of the mean daily excess return is
**≥ 2.0** over 2022-01-01 → 2026-09-17.

**Reported beside it, never deciding anything:** Sharpe, CAGR, drawdown, beta to BTC, all three
candidates, BTC buy-and-hold, and the chosen sleeve at 10% volatility combined with the
multi-asset book.

## Stated contamination

The author knows the broad path of BTC after 2021: the 2022 crash, the 2023–2024 recovery and the
2025–2026 decline. Trend rules broadly did well in large, persistent moves like those. The rules
above are the literature's own, fixed before any number was computed, but a pass here is weaker
evidence than a pass on truly unseen data. The only clean test left after this is a forward one
(paper trading from today).
