# Non-PEAD round 1: intraday rules, an ML model, and event days on ES/NQ futures

Plan: `research/intraday/PLAN.md` (registered before any predictor–return statistic). Data: LSE vault
30-minute ES/NQ bars 2016-06 → 2026-09, a new information set for the project; LSE economic calendar.
Accounting matches the PEAD benchmark: daily, net, excess (futures). Benchmark: **0.70**.

## Development, 2016-06 → 2020-12

| Candidate | Net Sharpe | Gross | 95% interval | Hit rate | Verdict |
|---|---:|---:|---|---:|---|
| I1 intraday momentum (Gao et al. 2018) | −0.12 | 0.31 | [−1.72, 0.84] | 47.1% | stop |
| I2 rest-of-day momentum (Baltussen et al. 2021) | 0.38 | 0.80 | [−0.89, 1.17] | 46.7% | stop (gate 0.5) |
| I3 LightGBM, technical features, fixed hyperparameters | −0.96 | −0.50 | [−1.85, 0.16] | 44.0% | stop |
| I4 long on Fed / CPI / payrolls days | 0.55 | 0.59 | [−0.44, 1.56] | 58.7% | to validation |

## Validation, 2021-01 → 2026-09 (run once, I4 only)

| Candidate | Net Sharpe | 95% interval | Max DD | Corr. with PEAD | Verdict |
|---|---:|---|---:|---:|---|
| I4 announcement day | −0.09 | [−0.79, 0.68] | −17% | 0.21 | **fail** |

Year by year: +4.8%, −2.5%, +5.7%, +1.3%, −7.8%, −5.2% (2021 → 2026).

## Reading

- **Intraday momentum is weak in 2016–2020 ES/NQ.** Gross it is positive (I2: 0.80), but a daily round
  trip at 0.5 bp a side takes about 2.5%/yr, and neither rule clears the gate. This fits the
  gamma-hedging explanation: the effect should be conditional on dealer positioning, not unconditional.
- **The ML model lost money even before costs** (gross −0.50, hit rate 44%). Gradient boosting on the
  terminal-style technical features found no usable pattern in the last half-hour. The simple rule (I2)
  beat it by 1.3 Sharpe gross. This is the typical out-of-sample fate of ML on price indicators, and it
  argues against using the terminal's classifier models without a genuinely informative feature.
- **The announcement-day premium did not survive 2021–2026.** CPI days in 2022 and the 2025 tariff shocks
  dominate. The interval's upper end (0.68) is below the 0.70 benchmark.

The trial ledger grows by 4 (I1–I4), and validation for this family is now consumed.

Reproduce: `PYTHONPATH=. .venv/bin/python -m research.intraday.evaluate dev` (tests: `tests/test_intraday.py`).
