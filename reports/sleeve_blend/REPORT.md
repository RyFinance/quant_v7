# Do the sleeves combine into something better?

Daily excess returns over French RF. Inverse-volatility weights fixed on 2021-2023 and applied
unchanged to 2024-2025. No evaluation-window information selects or weights anything.

Any claim here has to clear luck: with 37 strategies tried and only 373 evaluation days,
the best of them averages Sharpe 1.77 with no edge at all (one Sharpe standard error is 0.82).

| Portfolio | Sleeves | Effective independent bets | Later Sharpe | Later return | Later vol | Later drawdown | Beta | Alpha HAC t | Stressed Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all_sleeves | 8 | 3.88 | 0.27 | 0.55% | 2.15% | -1.85% | 0.16 | -0.12 | -0.72 |
| positive_only | 2 | 1.21 | 0.82 | 4.55% | 5.58% | -6.12% | 0.79 | 0.45 | 0.79 |
| SPY_control (benchmark) | 1 | 1.00 | 0.72 | 4.42% | 6.29% | -6.88% | 1.00 | — | — |

Mean absolute pairwise correlation across sleeves (selection window): 0.17.
Full matrix in `selection_correlations.csv`.

## Limits

- Sleeve returns are combined after each already paid its own costs; a real combined book would net
  offsetting trades, so the blends are charged slightly too much.
- The sleeves share one universe, one price source and one survivorship-biased constituent list, so
  their independence is overstated relative to genuinely different strategies.
- Inverse-volatility weighting is a fixed rule, not an optimization, but the sleeve DEFINITIONS were
  still chosen by people who had seen this data.
- No production deployment: this is sizing arithmetic over recorded research paths.

Reproduce: `PYTHONPATH=. .venv/bin/python -m research.blend_sleeves`
