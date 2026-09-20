# Validation unlock: SEC insider purchases

Registered after the development run (`reports/insider/dev/results.json`) and before any number from
2016 onward was computed.

## What development selected

Gate: net excess Sharpe ≥ 0.5 **and** beats the same-universe control (positive mean difference and a
Sharpe above the control's median).

| Candidate | Net Sharpe | Control (median) | Excess vs control | Passes |
|---|---|---|---|---|
| N1_cluster | 0.42 | 0.36 | +3.30%/yr | no (Sharpe < 0.5) |
| N2_csuite | 0.42 | 0.34 | +3.05%/yr | no (Sharpe < 0.5) |
| N3_opportunistic | 0.77 | 0.71 | +3.62%/yr | **yes** |
| N4_composite | 0.51 | 0.44 | +2.96%/yr | **yes** |

**N3_opportunistic** and **N4_composite** go to validation. N1 and N2 stop here and are never run on
2016–2026. N4 is the average of the N1–N3 sleeves, so those sleeves are computed in validation only
as N4's inputs; N1 and N2 get no validation result of their own.

## Frozen code

No rule, thresholds, cost, filter, control or gate changes. sha256 of the four modules as recorded in
the development results:

- research/insider/sec_data.py `756f475cb77e14075f054e70d369e1c2848c1dedcbba9dcf34eef04a2523e0aa`
- research/insider/signals.py `8db3336b9272207170cd0baa443b8166611b6c2a515c5311c218badc2244164f`
- research/insider/prices.py `2f87622f11083bc5a87528b1bf50c0a277628a1474be3178da05e301764a7d21`
- research/insider/evaluate.py `4b6b841a9b2e3b2f2c7340ed90dec35637d1f6683088b6e66323f77472827761`

Filing data: `data/sec_insider/manifest.json` sha256
`c9f197a7326555667ded4455c78f72043a3c3335ea357ee18833e9a1b2b082c4` (82 quarterly ZIPs, 2006q1–2026q2).

## Window and pass conditions

Window: signal dates 2016-01-01 → 2026-06-30, run **once**, book starting flat.

A candidate passes only if all of these hold, as registered in PLAN.md:
- net excess Sharpe ≥ 0.75, and above the PEAD benchmark of 0.70;
- stressed (×2 costs) mean net excess return > 0;
- one-sided block-bootstrap p < 0.05/4 = 0.0125;
- the paired test against the same-universe control, p < 0.0125.

A pass means a forward paper test from its registration date, not capital.

## Stated before the run

Development gave no market-adjusted alpha: the CAPM alpha t-statistics were 0.40 (N1), 0.37 (N2),
−0.11 (N3) and 1.18 (N4), with betas of 1.08–1.29, and N3's hedged Sharpe was −0.09. The long-only
Sharpes therefore rest on market exposure in a currently-listed universe, and the controls were
already at 0.34–0.71. The honest expectation is that neither candidate clears 0.75 net with a
paired p below 0.0125. The run happens because the registered gate says it does.
