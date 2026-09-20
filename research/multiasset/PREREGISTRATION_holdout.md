# Pre-registration: the multi-asset book on its hold-out, 2018-01-01 → 2026-09-17

Written 2026-09-18, after development and **before any hold-out return was computed**. Registering
this file, with its SHA-256 in `research/preregistrations.jsonl`, is what unlocks the hold-out
dates in `research/multiasset/panel.py`. The run happens once. Every number it produces is
reported, including the ones that contradict the goal.

## What development produced

17 sleeve specifications were tried on data through 2017-12-31. All of them are logged in
`reports/multiasset/dev_trials.jsonl`, and the rules are in `PLAN.md`, `PLAN_ADDENDUM_1.md` and
`PLAN_ADDENDUM_2.md`.

The inclusion rule (Sharpe ≥ 0.30 over at least 3 years, with only the best time-series momentum
variant allowed in) selected **five sleeves**:

| Sleeve | Development Sharpe (net) | Years |
|---|---:|---:|
| `vix_basis` | 0.98 | 7.0 |
| `tsmom_broad` | 0.47 | 13.9 |
| `fx_carry` | 0.45 | 8.9 |
| `bond_carry` | 0.31 | 14.4 |
| `overnight_intraday_reversal` | 0.30 | 14.0 |

The development book (equal risk, 10% volatility target) scored an excess Sharpe of 0.57, 6.7% a
year, a −19.2% maximum drawdown and a HAC t-statistic of 2.04.

## Code, frozen

`research/multiasset/holdout.py` refuses to run if any of these files differs from the hashes below.

| File | SHA-256 |
|---|---|
| panel.py | cfdd5b19ce4983a8bb6ad507966aa761ff6b96bb017b5ef0512c37869b6a868c |
| sleeves.py | ff225443f95703fd5739d670a24666570f1a0585a88018ec1924a3dfd187d560 |
| evaluate.py | b616119f0ad7ed4ba9bb2ae5c2c7cbbd9e11af6fbb2e3cd3a66344728fd2bf57 |
| holdout.py | d989b404cdae6c78b65380c35822a91b039078e2cf21b34e75a749c2f012712c |

## Primary test

The five-sleeve book, built exactly as in development, has its daily excess returns judged on
2018-01-01 → 2026-09-17. Each sleeve runs over its full history, so the volatility scaling at the
hold-out start uses only earlier data.

**Pass criteria. Both are required:**

1. The HAC (Newey-West, 20 lags) t-statistic of the book's mean excess return is **≥ 2.0**.
2. The HAC t-statistic of the book's alpha against SPY excess returns is **≥ 2.0**.

**The user's target is reported separately, as met or not met:** an excess Sharpe **≥ 2.0** and a
total CAGR **≥ 10%**. The honest prior is that the target will **not** be met. A 0.57 development
Sharpe after 17 trials is expected to shrink out of sample.

## Descriptive analyses (reported, never decide anything)

- The hold-out statistics of every one of the 17 development sleeves.
- The book with the round-3 sleeve charged 1 bp and 3 bps per auction trade instead of 2 bps.
- Every round-3 sleeve at 1 bp and 3 bps, and the one-way auction cost at which each breaks even.
- The book without the round-3 sleeve (the four macro sleeves only).
- All candidates combined, with one time-series momentum variant.
- SPY over the same window.
- The book's excess return by calendar year.

## Known limits, stated before the result

- The stock sleeve's universe is **today's** S&P 500 members (survivorship bias).
- Bond returns are constructed from yields with a duration approximation. They are not traded
  prices.
- The vault yield series is despiked with a filter that looks one print ahead.
- The author knows, in broad terms, how trend, carry and short-volatility strategies fared after
  2018. The parameters come from the literature and the selection rule was mechanical, but that
  knowledge cannot be unknown.
