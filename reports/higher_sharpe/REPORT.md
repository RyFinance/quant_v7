# Higher-Sharpe, fee-aware research

Frozen cache; next-open fills; daily mark-to-market; 5% ex-ante volatility target; 60% gross exposure cap. Sharpe uses excess returns over French daily RF; free cash earns RF, short collateral earns nothing.

Base: 10 bps round trip + 3% annual short borrow. Stress: 25 bps + 10% borrow. All numbers below are on 2024-01-02 through 2025-06-27, after selection on 2021–2023.

| Strategy | Selection Sharpe | Later CAGR | Later volatility | Later Sharpe | Later drawdown | Beta | Alpha HAC t | Stress CAGR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Wide PEAD recorded schedule | — | 9.84% | 8.94% | 0.53 | -10.72% | 0.36 | -0.13 | — |
| residual_momentum | -0.48 | 6.36% | 5.25% | 0.24 | -3.53% | -0.02 | 0.40 | 3.85% |
| residual_reversal | -1.09 | 4.99% | 4.38% | -0.02 | -2.78% | 0.03 | -0.15 | -0.74% |
| low_beta_spread | -0.22 | 7.47% | 5.56% | 0.42 | -4.27% | 0.06 | 0.33 | 6.93% |
| low_vol_long | 0.44 | 10.89% | 6.19% | 0.89 | -5.48% | 0.23 | 0.50 | 10.53% |
| liquid_equal_weight | 0.66 | 9.01% | 6.10% | 0.62 | -6.34% | 0.32 | -0.73 | 8.93% |
| low_vol_hedged | -0.34 | 5.26% | 3.90% | 0.04 | -3.14% | 0.03 | -0.10 | 3.75% |
| momentum_reversal_blend | -0.99 | 5.48% | 3.27% | 0.11 | -2.94% | 0.01 | 0.08 | 1.55% |
| pead_sue_hedged | -0.20 | 1.35% | 3.22% | -1.13 | -2.70% | -0.00 | -1.52 | -1.80% |
| pead_reaction_confirmed | -0.05 | 4.55% | 2.74% | -0.20 | -1.83% | -0.02 | -0.12 | 2.03% |
| defensive_momentum_blend | 0.14 | 8.34% | 4.36% | 0.70 | -3.57% | 0.13 | 0.37 | 6.72% |
| SPY_control | 0.66 | 9.81% | 6.29% | 0.72 | -6.11% | 0.34 | -0.63 | 9.77% |

Selection result (63-day paired block bootstrap; unadjusted for multiple tests):

```json
{
  "name": "liquid_equal_weight",
  "evaluation_delta_sharpe_ci_95": {
    "lower_95": -1.1049554549766751,
    "median": 0.13526222302496993,
    "upper_95": 1.917679036373239
  },
  "passes_research_gate": false
}
```

## Limits

- 11 additional candidate/control definitions after earlier 26 configurations; exploratory multiple testing, no pristine holdout.
- Current constituent survivorship persists despite causal liquidity ranking.
- Hedges reduce estimated beta but neither guarantee zero beta nor neutralize sector/style factors.
- Historical data and revised earnings estimates are not independently vendor verified.
- All positions paper/research. No borrow availability, locate fees, tax or market impact model.
- Cash assumes a Treasury-bill-like return on free cash. Actual broker interest may be lower; short collateral earns no rebate.
- Adjusted Yahoo OHLC are total-return proxies, not literal historical trade prices. Adjusted-price ADV is not point-in-time unadjusted dollar volume.
- Sizing constraints only: production risk gates/circuit breaker are not replayed for these candidates.

Wide PEAD accounting preserves recorded share quantities and decision schedule, charging reconstructed trading costs and borrow once and crediting free cash interest. It is an accounting audit, not a rerun of gates using marked equity. Recorded fills are same-day closes; candidate fills are next opens, so relative results are not a controlled signal-only experiment.

Cash-rate source: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html (daily three-factor file RF column; downloaded snapshot hash in specification).

Reproduce: `python3 -m research.higher_sharpe`. Frozen inputs, source hashes, complete earlier-window results, stressed paths and CSVs are saved beside this report.
