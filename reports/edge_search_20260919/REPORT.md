# Strategy research results — 19 September 2026

Target: net excess Sharpe at least 2 and compound annual return above 10%. None of the 15 configurations in this batch met both targets. Counts include controls and fixed blends; they are not 15 independent discoveries.

## Completed work

- Built annual expanding-window ridge and gradient-boosting stock models using 12 price, residual-return, volume and volatility features across 503 names. Training samples increased from approximately 263,000 to 565,000 per yearly fit. Six-session label purge; next-open execution; five-session overlapping holdings and a SPY hedge. Two economic rules and a fixed blend are recorded alongside the models.
- Built same-issuer share-class relative-value trades in Alphabet, News Corp and Fox, including true share-class inception restrictions, next-open fills, short collateral, borrowing costs and explicit debit financing.
- Used the actual configured LSE Terminal MCP and authenticated vault data to obtain positioning data and build an original crowding-unwind signal across 14 markets. Extreme speculative positions, four-report unwinding and price confirmation determine direction. Position-only and price-only controls are included.
- Built downside-aware rotation across 12 ETFs covering US and international equities, real estate, commodities, gold and bonds. It ranks three-horizon momentum against downside risk, discounts correlated selections, holds at most four assets, and uses monthly decisions with next-open execution. Momentum-only and equal-weight controls use the same execution and risk infrastructure.

## Full scorecard

Returns are CAGR. Sharpe uses daily portfolio returns in excess of the daily cash rate. All open positions are marked daily. Different evaluation windows are displayed explicitly.

| Configuration | Evaluation period | Net CAGR | Excess Sharpe | Max drawdown | Stress CAGR | Stress Sharpe |
|---|---|---:|---:|---:|---:|---:|
| ridge | 2021–2025-06-27 | -3.71% | -0.60 | -34.18% | -13.55% | -1.63 |
| gradient_boost | 2021–2025-06-27 | -1.53% | -0.41 | -28.66% | -9.85% | -1.30 |
| liquidity_shock | 2021–2025-06-27 | 1.22% | -0.61 | -8.04% | -2.32% | -1.81 |
| trend_pullback | 2021–2025-06-27 | -0.74% | -0.69 | -14.81% | -7.53% | -2.02 |
| fixed_blend | 2021–2025-06-27 | -1.38% | -0.71 | -21.39% | -8.34% | -2.04 |
| alphabet | 2021–2025-06-27 | 0.94% | -1.27 | -5.26% | -1.93% | -2.72 |
| news | 2021–2025-06-27 | -1.12% | -0.85 | -10.12% | -4.60% | -1.58 |
| fox | 2021–2025-06-27 | 0.87% | -0.69 | -7.75% | -2.09% | -1.61 |
| primary_book | 2021–2025-06-27 | 0.27% | -1.41 | -5.67% | -2.81% | -2.92 |
| crowding_unwind | 2021–2025-06-27 | 3.47% | 0.09 | -8.93% | 1.02% | -0.37 |
| positioning_only | 2021–2025-06-27 | 1.76% | -0.16 | -11.55% | -2.51% | -0.77 |
| price_only | 2021–2025-06-27 | -2.99% | -0.63 | -20.21% | -12.41% | -1.76 |
| primary | 2017–2025-06-27 | 6.22% | 0.38 | -27.49% | 5.59% | 0.33 |
| momentum_only | 2017–2025-06-27 | 8.12% | 0.48 | -27.15% | 7.50% | 0.44 |
| equal_weight | 2017–2025-06-27 | 6.47% | 0.36 | -31.57% | 6.39% | 0.35 |

## Costs and interpretation

Base stock/ETF transaction costs are 10 basis points round trip, modeled as 5 basis points per side of traded notional. Stress uses 25 basis points round trip. Short strategies also use 3% annual borrow in base and 10% in stress. The share-class, positioning and rotation engine finances debit balances at the daily risk-free rate plus 1% annual spread and withholds interest on short-sale collateral. Cash earns the cached daily cash rate. These are cost scenarios, not measured venue-specific historical fills or verified historical stock-loan availability.

The best new score in this batch is the momentum-only rotation control: 8.12% CAGR, 0.48 excess Sharpe, and −27.15% maximum drawdown over 2017–mid-2025. Its recent 2021–mid-2025 result is 7.16% CAGR and 0.37 excess Sharpe. This is not a discovered high-Sharpe edge. The custom downside adjustment underperformed that control.

Both stock learning models had development Sharpe near 1 but negative evaluation excess returns after costs. Their high turnover and borrowing drag make the current five-session execution unattractive. Same-issuer convergence also failed after borrow and execution costs. The corrected crowding strategy earned 3.47% CAGR and 0.09 excess Sharpe, and its excess return became negative under cost stress.

## Reproducibility and verification

Each experiment has source code, fixed specifications or a registration file, input hashes, portfolio targets, daily NAV/returns, cost-stress results, and a JSON scorecard. The COT publication correction retains the initial outputs and documents the correction separately. Eleven focused tests passed for causal features, purged labels, position sizing, actual-unit accounting, short collateral, missing entries, and publication delays.

COT publication metadata incorrectly implies normal releases during known reporting interruptions. Conservative delays are imposed. The corrected run also waits for preceding reports used by rolling features and never moves a late vendor release earlier. Its outputs supersede the original run; no thresholds or trading parameters were retuned. See [availability amendment](../crowding_unwind_20260919/availability_corrected/AMENDMENT.md).

These are exploratory results on historical periods already exposed by this project, not a fresh untouched holdout. Current stock-universe membership creates survivorship limitations. ETF adjusted bars and modeled costs do not establish execution capacity. Failure on these tests is sufficient to reject promotion; success would still need stronger point-in-time data and paper execution.

## Files

- [Stock models](../liquidity_pressure_20260918/results.json)
- [Same-issuer trades](../share_class_20260918/results.json)
- [Corrected crowding strategy](../crowding_unwind_20260919/availability_corrected/results.json)
- [Rotation and controls](../downside_rotation_20260919/results.json)
- [Machine-readable consolidated scorecard](scorecard.json)

Re-run from the project root:

```sh
.venv/bin/python -m research.liquidity_pressure
.venv/bin/python -m research.share_class
.venv/bin/python -m research.crowding_unwind
.venv/bin/python -m research.downside_rotation
.venv/bin/python -m pytest tests/test_downside_rotation.py tests/test_share_class.py tests/test_liquidity_pressure.py -q
```

The trained-stock prediction cache belongs to the recorded inputs and code; invalidate it before rerunning against changed data. No live trading configuration was changed by these experiments.
