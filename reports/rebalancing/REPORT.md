# A1: front-running balanced-fund rebalancing (Harvey, Mazzoleni & Melone 2025)

**Verdict: fails validation. Nothing beats the 0.70 benchmark on its own.** The effect is real in the
sense that gross returns are positive in both halves. But after 2 bp/side/leg costs the validation
Sharpe is 0.63 (R2) and 0.45 (R3). Almost all of it is from two crisis years (2008, 2020), and it
disappears with a one-day execution lag.

Plan: `research/rebalancing/PLAN.md` (registered 2026-09-19T03:17:37-0700). Unlock:
`research/rebalancing/VALIDATION_UNLOCK.md`. Code: `research/rebalancing/{signals,evaluate}.py`.
Tests: `tests/test_rebalancing.py` (7 pass). Raw output: `reports/rebalancing/{dev,validation}_results.json`
and daily CSVs.

**Scope caveat.** Every window from 2003 to 2026 was viewed before, and the paper's sample (1997-2023)
covers most of it. This measures whether the paper's rule could be harvested with ETFs after costs. It
is not independent evidence.

## Rule as implemented (from the NBER PDF, Section 1.2, Section 4 and Appendix B)

- A simulated 60/40 SPY/IEF portfolio. The paper uses ES and 10y-note futures; we have no ZN series.
- **Threshold signal:** the drifted equity weight minus 60% at the close of t. The portfolio resets when
  |dev| >= delta. The signal is averaged over delta = 0.0%, 0.1%, ..., 2.5%.
- **Calendar signal:** the same drift, reset on the last trading day of each month.
- **Candidates:**
  - **R1_calendar:** position = sign(-Cal_t) on the last 5 trading days of the month, and sign(Cal_{t-4})
    on the first trading day of the month (the reversal). Zero on other days.
  - **R2_threshold:** position = -Thr_t / 1.5%.
  - **R3_combined:** the average of R1 and R2. This is the paper's strategy, which reports gross Sharpe
    1.11 over 1997-2023.
- **Trading:**
  - Positions are held in SPY-minus-IEF, set at the close of t and earning over t to t+1.
  - Cost is 2 bp per side on each leg, applied to |Δw|. The stress case is 6 bp.
- **Ambiguity:** the paper writes the reversal term as sign(Calendar_{-4}). We read that as the signal
  4 trading days earlier.

## Development, 2003-02-03 to 2014-12-31 (all three candidates)

| | R1_calendar | R2_threshold | R3_combined |
|---|---|---|---|
| Net Sharpe (base) | **0.47** (fails) | **0.74** (passes) | **0.82** (passes) |
| 95% CI | [-0.08, 1.02] | [0.39, 1.12] | [0.35, 1.27] |
| Gross Sharpe / stress Sharpe | 0.64 / 0.12 | 0.90 / 0.42 | 1.03 / 0.41 |
| p (one-sided) | 0.052 | 0.004 | 0.004 |
| Deflated Sharpe (60 trials) | 0.55 | 0.87 | 0.93 |
| Annual return / vol | 5.8% / 12.4% | 8.5% / 11.5% | 7.3% / 8.9% |
| Max drawdown | -21.8% | -14.3% | -8.8% |
| Hit rate (active days) | 53% | 47% | 49% |
| Active days / position changes | 858 / 465 | 3000 / 2999 | 3000 / 2999 |
| Annual cost drag | 2.2% | 1.8% | 1.9% |
| One-day-lag Sharpe (descriptive) | -0.37 | 0.31 | 0.02 |
| Sharpe excluding 2008 (descriptive) | – | 0.55 | 0.57 |
| 2008 return | +31% | +74% | +54% |

R1 earns 8.7 bp per active day net, but it is active only about 3.4 days a month.

## Validation, 2015-01-01 to 2026-09-18 (R2 and R3 only, run once)

| | R2_threshold | R3_combined |
|---|---|---|
| Net Sharpe (base) | **0.63** | **0.45** |
| 95% CI / null kind at 0.5 | [-0.10, 1.11], vacuous | [-0.26, 1.01], vacuous |
| Gross Sharpe / stress Sharpe | 0.76 / 0.36 | 0.67 / 0.02 |
| Stress annual mean | +4.1% | +0.2% |
| p (one-sided), needs < 0.0167 | 0.108 | 0.126 |
| Deflated Sharpe (60 trials) | 0.80 | 0.53 |
| Annual return / vol / max drawdown | 7.1% / 11.3% / -11.8% | 3.6% / 7.8% / -13.8% |
| Hit rate | 47% | 46% |
| One-day-lag Sharpe (descriptive) | -0.31 | -0.38 |
| Sharpe excluding 2020 (descriptive) | 0.25 | 0.17 |
| Sharpe since 2025-03, after the paper (descriptive) | -0.01 | -0.40 |
| **Passes validation** | **no** (Sharpe, p) | **no** (Sharpe, p) |

Returns by year:
- **R2:** 2015 +3.5%, 2016 -1.0%, 2017 -1.9%, 2018 +0.8%, 2019 +1.6%, **2020 +86.6%**, 2021 -1.3%,
  2022 +16.2%, 2023 +2.5%, 2024 -5.0%, 2025 +2.4%, 2026 YTD -2.7%.
- **R3:** 2015 -2.2%, 2016 +2.9%, 2017 -1.1%, 2018 +1.9%, 2019 -2.9%, **2020 +33.7%**, 2021 +3.5%,
  2022 +5.8%, 2023 +3.4%, 2024 +2.1%, 2025 0.0%, 2026 YTD -3.9%.

## PEAD overlay (pre-registered 50/50 risk weights, 973 common days 2021-08 to 2025-06)

| | Correlation with PEAD | Candidate Sharpe (common) | PEAD Sharpe | Overlay Sharpe [95% CI] |
|---|---|---|---|---|
| R2_threshold | -0.00 | 0.62 | 0.70 | **0.92** [0.09, 1.88] |
| R3_combined | 0.06 | 0.47 | 0.70 | 0.82 [-0.09, 1.82] |

The overlay beats 0.70 because the sleeve is uncorrelated with PEAD. But the overlay window is only
3.9 years, and the sleeve's return in that window is mostly 2022 (a year when stocks and bonds fell
together). The interval is too wide to call this an improvement. The overlay was not a gated test.

## Reading

1. **Mechanism.** Gross profits in both halves agree with the paper: dev R3 gross is 1.03 against the
   paper's 1.11. The profits are almost entirely crisis convexity: 2008 in development, 2020 (and 2022)
   in validation. Outside those years, net Sharpe is 0.2-0.6.
2. **Implementation.** The profits need a position set at the same close that the signal is measured.
   A one-day lag makes every candidate zero or negative. So any live version must compute the signal
   from prices a few minutes before 16:00 and trade MOC. Only that timing was tested (as the paper
   assumes). Whether a 15:45 signal keeps the edge is untested, and would be a new registered
   experiment. The 30-minute ES bars could answer it for the equity leg.
3. **Costs.** The threshold legs trade every day, and 2 bp per side per leg costs about 1.5-1.9% a year.
   At 6 bp, R3's validation mean is gone.
4. **After publication.** Since 2025-03 the sleeves are flat to negative, which fits front-running
   decay but covers too few days to be evidence.

**Conclusion:** as a stand-alone strategy, this is a graveyard entry. A crisis-convex, low-correlation
sleeve next to PEAD is plausible on economic grounds. A new, separately registered test would need to
use near-close execution and a forward paper period.
