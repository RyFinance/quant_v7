# Offline strategy comparison

All returns are daily mark-to-market, net of 10 bps round-trip trading costs and 3% annual short borrow. Cash earns zero. Sharpe uses arithmetic mean daily returns with zero risk-free rate.

| Candidate | CAGR | Volatility | Sharpe | Max drawdown | 2021–23 Sharpe | 2024–25 Sharpe | 25 bps CAGR |
|---|---:|---:|---:|---:|---:|---:|---:|
| Recorded PEAD, corrected accounting | 5.16% | 7.56% | 0.70 | -12.01% | 0.79 | 0.53 | — |
| equal_weight__caps_only | 14.33% | 14.67% | 0.99 | -19.51% | 0.65 | 1.51 | 14.26% |
| trend_200d__caps_only | 13.30% | 12.86% | 1.04 | -20.13% | 0.63 | 1.61 | 12.99% |
| momentum_12_1__caps_only | 21.00% | 18.85% | 1.11 | -23.01% | 0.74 | 1.54 | 20.64% |
| momentum_trend__caps_only | 18.29% | 17.67% | 1.04 | -23.40% | 0.66 | 1.48 | 17.89% |
| low_volatility__caps_only | 7.98% | 8.35% | 0.96 | -10.18% | 0.76 | 1.34 | 7.75% |
| reversal_5d__caps_only | 13.81% | 19.79% | 0.75 | -30.36% | 0.27 | 1.47 | 9.82% |
| pead_sue_10d__caps_only | 5.62% | 6.11% | 0.93 | -7.27% | 0.58 | 1.46 | 4.72% |
| pead_sue_20d__caps_only | 6.50% | 7.20% | 0.91 | -8.33% | 0.43 | 1.70 | 5.77% |
| pead_sue_40d__caps_only | 6.03% | 8.25% | 0.75 | -9.48% | 0.24 | 1.59 | 5.47% |
| pead_long_only__caps_only | 7.24% | 8.44% | 0.87 | -9.94% | 0.33 | 1.92 | 6.52% |
| earnings_reversal__caps_only | -8.38% | 7.22% | -1.18 | -30.60% | -0.69 | -1.97 | -9.03% |
| pead_causal_ml_55__caps_only | 8.71% | 9.76% | 0.90 | -11.72% | 0.33 | 1.75 | 7.81% |
| pead_causal_ml_65__caps_only | 0.62% | 7.60% | 0.12 | -10.12% | 0.17 | -0.01 | 0.30% |
| equal_weight__vol_5pct | 5.97% | 5.51% | 1.08 | -6.75% | 0.87 | 1.38 | 5.93% |
| trend_200d__vol_5pct | 5.64% | 5.62% | 1.00 | -8.59% | 0.70 | 1.42 | 5.51% |
| momentum_12_1__vol_5pct | 6.46% | 5.54% | 1.16 | -6.93% | 0.77 | 1.71 | 6.35% |
| momentum_trend__vol_5pct | 5.97% | 5.63% | 1.06 | -9.23% | 0.62 | 1.69 | 5.83% |
| low_volatility__vol_5pct | 6.61% | 5.73% | 1.15 | -5.43% | 0.86 | 1.56 | 6.43% |
| reversal_5d__vol_5pct | 4.98% | 5.26% | 0.95 | -8.85% | 0.45 | 1.77 | 3.58% |
| pead_sue_10d__vol_5pct | 4.00% | 3.92% | 1.02 | -5.40% | 0.76 | 1.40 | 3.19% |
| pead_sue_20d__vol_5pct | 4.69% | 4.29% | 1.09 | -4.56% | 0.74 | 1.64 | 4.00% |
| pead_sue_40d__vol_5pct | 2.89% | 4.64% | 0.64 | -5.94% | 0.14 | 1.41 | 2.37% |
| pead_long_only__vol_5pct | 4.97% | 4.30% | 1.15 | -4.26% | 0.80 | 1.72 | 4.35% |
| earnings_reversal__vol_5pct | -6.11% | 4.30% | -1.44 | -22.52% | -1.11 | -1.99 | -6.73% |
| pead_causal_ml_55__vol_5pct | 4.77% | 4.62% | 1.03 | -4.82% | 0.64 | 1.62 | 4.04% |
| pead_causal_ml_65__vol_5pct | 1.38% | 3.51% | 0.41 | -5.42% | 0.44 | 0.36 | 1.12% |

Selected among alternatives using 2021–23 Sharpe only:

```json
{
  "caps_only": {
    "name": "low_volatility__caps_only",
    "later_sharpe_difference_vs_current_pead_ci": {
      "lower_95": -0.9523466967045598,
      "median": 0.8956187188167171,
      "upper_95": 3.0131079556210842
    },
    "decision_including_current": "retain_current: baseline selection Sharpe exceeds every caps-only candidate"
  },
  "vol_5pct": {
    "name": "equal_weight__vol_5pct",
    "later_sharpe_difference_vs_current_pead_ci": {
      "lower_95": -0.9705345758442379,
      "median": 0.9248256388090825,
      "upper_95": 3.027099416296895
    }
  }
}
```

## SPY benchmark

SPY holds up to 60% in one diversified ETF; individual-name 10% cap does not apply to this benchmark.

| Benchmark | CAGR | Volatility | Sharpe | Max drawdown |
|---|---:|---:|---:|---:|
| SPY_caps_only | 6.06% | 10.90% | 0.59 | -15.15% |
| SPY_vol_5pct | 3.51% | 5.63% | 0.64 | -6.77% |

## Price-only extension: 2025-06-30 through 2026-08-10

Earlier selected candidates only. No comparable PEAD earnings history in this extension; current-universe bias still applies.

Data-quality stop: {"end": "2026-08-10", "first_missing_date": "2026-08-11", "missing_tickers": ["ABBV"], "policy": "stop before first incomplete universe day; never fabricate a held-position mark"}

```json
{
  "low_volatility__caps_only": {
    "n_days": 280,
    "annualized_return": 0.076787,
    "annualized_std": 0.058138,
    "sharpe_ratio": 1.3016,
    "sortino_ratio": 2.0557,
    "max_drawdown": -0.041026,
    "calmar_ratio": 1.8716,
    "total_return": 0.085674,
    "average_gross_exposure": 0.5975125675688574,
    "one_way_turnover_annualized": 3.2610857309101116
  },
  "equal_weight__vol_5pct": {
    "n_days": 280,
    "annualized_return": 0.145743,
    "annualized_std": 0.055886,
    "sharpe_ratio": 2.463,
    "sortino_ratio": 3.7194,
    "max_drawdown": -0.028918,
    "calmar_ratio": 5.0399,
    "total_return": 0.163195,
    "average_gross_exposure": 0.2651914941719555,
    "one_way_turnover_annualized": 0.9476711447234527
  }
}
```

## Interpretation limits

- Current 2026-selected 75-name universe has survivorship and selection bias.
- Historical Yahoo cache is not independently vendor-verified or point-in-time earnings-vintaged.
- 2024-2025 was studied by previous repository experiments; not pristine out-of-sample.
- Research candidates use sizing caps but do not reproduce production circuit breaker/daily-loss/kill-switch policy.
- No stock loan availability, market impact, taxes, cash interest, or locate fees modeled.
- Annual ML refits use only prior matured labels, including earlier evaluation-year labels for later years.
- 5% volatility target reduces exposure only, never adds leverage; not guaranteed realized volatility.
- Candidate screening is multiple testing; bootstrap intervals are descriptive, unadjusted.

Recorded PEAD keeps the original trade schedule and dollar sizes; its corrected equity is not fed back into historical risk decisions. Candidates run continuously across the selection/evaluation boundary; subperiod metrics include carried holdings. Initial entry and final liquidation costs are included. No candidate is deployed.

Reproduce: `python3 -m research.compare_strategies`. Input hashes and annual training cutoffs are in specification.json.
