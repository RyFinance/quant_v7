# Pre-registration: crypto trend on its hold-out, 2022-01-01 → 2026-09-17

Written 2026-09-18, after crypto development and **before any hold-out return was computed**.
Registering this file unlocks the hold-out dates in `research/multiasset/crypto.py`. The run
happens once.

## Development result (through 2021-12-31; `reports/multiasset/crypto/dev_results.json`)

| Candidate | Sharpe | Years | Passes |
|---|---:|---:|---|
| crypto_tsmom_1w | 0.49 | 7.1 | yes |
| crypto_tsmom_multi | 1.11 | 6.3 | yes |
| **crypto_trend_long_only** | **1.24** | 6.2 | yes, **chosen** (highest) |
| BTC buy-and-hold (reference) | 1.24 | 7.0 | — |

## Frozen code

`research/multiasset/crypto.py` sha256 **f617c19e4c19981f991bb1f3ee45959dc138ff9578ef0d6f190c9c3745b2ec26**. The hold-out function refuses to run if the
file differs.

## Primary test and pass criterion

`crypto_trend_long_only` on 2022-01-01 → 2026-09-17. **Pass:** the HAC t-statistic (20 lags) of the
mean daily excess return is **≥ 2.0**. With 4.7 years of data this needs a Sharpe of roughly 0.9 or
more.

## Reported, never deciding anything

All three candidates, BTC buy-and-hold, and a 50/50 blend (both at 10% volatility) of the chosen
sleeve with the multi-asset book's recorded hold-out returns. The multi-asset book failed its own
test, so that blend is illustration only.

## Contamination, restated

The author knows BTC's broad path after 2021. A pass is therefore weaker evidence than a pass on
unseen data. The only clean test after this is forward paper trading.
