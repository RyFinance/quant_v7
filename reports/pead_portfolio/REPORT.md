# Hedging, vol-managing or combining PEAD: no clearly better portfolio

**Result: all five pre-registered constructions FAIL.** The PEAD 2× book on its own, at an excess
Sharpe of 0.70, remains the project's best strategy. Only one construction (B3, PEAD plus trend)
beat 0.70, reaching 0.74. That edge came entirely from 2022, is far from significant (p = 0.47),
and had a deeper drawdown. The ceiling calculation shows why this route cannot give a *clearly*
better portfolio: even the best possible mix of these sleeves, chosen with hindsight, reaches only
about 0.77.

- **Plan:** `research/pead_portfolio/PLAN.md`, registered 2026-09-18T22:02:19-0700, sha256
  `291ab68d…0015`, in `research/preregistrations.jsonl`. It was written before any combined
  statistic, and the run refuses to start if the file changes.
- **Code:** `research/pead_portfolio/`. **Tests:** `tests/test_pead_portfolio.py`, 20 passing. They
  cover no look-ahead in betas, vol weights and risk weights, the two-day implementation lag, the
  warm-up, and exact cost, roll and financing accounting.
- **Numbers:** `results.json`, `daily_excess_{main,old}.csv` and `weights_{main,old}.csv`.
- **Evidence status:** every window here had been seen before, so these are development results
  only. A pass would have gone to a forward paper test, not to capital.

## Constructions (rules fixed in the PLAN)

Common rules for all five:
- Rebalanced monthly: decided on month-end data, traded the next close, earning from the day
  after that.
- Each construction is plain PEAD until 63 days of PEAD history exist. That is the first 3.6 months
  of the main window, from 2021-08-12 to 2021-12-01.
- Costs: 5 bps per side to resize the stock book, 1 bp per side on the ES hedge plus 2 bps per
  quarterly roll, 10 bps per unit change of a sleeve weight, and 1.5%/yr above T-bills on any
  stock-book leverage.

The five rules:
- **B1:** short the market (SPY as the ES proxy) at the rolling 126-day beta, clamped to [0, 1.5].
- **B2:** PEAD scaled by (expanding-mean 21-day vol) / (current 21-day vol), capped at 2×.
- **B3:** PEAD + tsmom_broad at equal risk. The mix is scaled so its ex-ante volatility equals
  PEAD's own trailing volatility.
- **B4:** PEAD + fx_carry + bond_carry + tsmom_broad, equal risk, scaled the same way. vix_basis is
  excluded: the pre-stated reason is its −86% short-vol crash.
- **B5:** B1's hedged PEAD + the B4 sleeves, equal risk.

## Results: main window 2021-08-12 → 2025-06-27 (973 days, net, excess over T-bills)

| | Sharpe [95%] | Excess CAGR | Vol | Max DD | Max DD at PEAD vol | Beta | Corr w/ PEAD | ΔSharpe vs PEAD [95%] | One-sided p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **PEAD 2×** | **0.70** [−0.24, 1.72] | 6.5% | 9.6% | −13.0% | — | 0.35 | 1 | — | — |
| B1 beta-hedged | 0.54 [−0.48, 1.62] | 3.7% | 7.2% | −10.6% | −13.9% | 0.03 | 0.74 | −0.16 [−0.87, +0.51] | 0.66 |
| B2 vol-managed | 0.51 [−0.40, 1.53] | 5.2% | 11.0% | −18.5% | −16.2% | 0.33 | 0.84 | −0.19 [−0.70, +0.33] | 0.78 |
| B3 PEAD + tsmom | **0.74** [−0.42, 1.97] | 6.4% | 9.0% | −18.1% | −19.2% | 0.17 | 0.64 | +0.04 [−1.12, +1.22] | 0.47 |
| B4 PEAD + 3 sleeves | 0.59 [−0.31, 1.54] | 5.5% | 10.1% | −14.3% | −13.7% | 0.14 | 0.40 | −0.11 [−1.02, +0.83] | 0.59 |
| B5 hedged + 3 sleeves | 0.49 [−0.44, 1.46] | 3.6% | 7.7% | −12.4% | −15.2% | 0.00 | 0.30 | −0.21 [−1.24, +0.81] | 0.66 |

How the columns are defined:
- The PEAD row reproduces the audit exactly: Sharpe 0.700, beta 0.352, alpha 4.21%/yr, t 1.15.
- Beta is against the French market factor, estimated with Newey-West (20 lags).
- The paired test is a circular block bootstrap (21-day blocks, 5,000 draws) of the difference
  between the construction's and PEAD's Sharpe ratios, which compares them at equal risk.
  Bonferroni threshold: p < 0.01.
- "Max DD at PEAD vol" rescales the construction to PEAD's realised volatility, so a construction
  cannot pass the drawdown test just by being smaller.

## Results: 2004–2014 PEAD model window (2,769 days)

| | Sharpe [95%] | Excess CAGR | Vol | Max DD | Max DD at PEAD vol | Beta | Corr w/ PEAD | ΔSharpe [95%] | One-sided p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **PEAD model** | **0.52** [0.06, 1.08] | 6.0% | 12.7% | −27.1% | — | 0.54 | 1 | — | — |
| B1 beta-hedged | 0.30 [−0.18, 0.80] | 2.0% | 7.3% | −16.3% | −26.8% | 0.05 | 0.61 | −0.22 [−0.71, +0.20] | 0.82 |
| B2 vol-managed | 0.51 [−0.03, 1.08] | 5.7% | 12.4% | −22.6% | −23.0% | 0.44 | 0.83 | −0.02 [−0.33, +0.29] | 0.50 |
| B3 PEAD + tsmom | 0.59 [0.03, 1.16] | 6.6% | 12.2% | −20.5% | −21.3% | 0.32 | 0.68 | +0.06 [−0.47, +0.53] | 0.38 |
| B4 PEAD + 3 sleeves | 0.58 [0.02, 1.17] | 6.5% | 12.2% | −19.8% | −20.6% | 0.23 | 0.50 | +0.05 [−0.49, +0.54] | 0.42 |
| B5 hedged + 3 sleeves | 0.49 [−0.02, 1.02] | 3.2% | 6.9% | −11.3% | −20.2% | 0.01 | 0.33 | −0.03 [−0.59, +0.47] | 0.52 |

- On this window the sleeves are the development-era series that the multi-asset study selected
  on, so B3–B5 are **in-sample** here, which favours them.
- fx_carry only starts in 2009, so it enters B4 and B5 from 2009.
- Drawdowns are measured on the excess-return index, so PEAD shows −27.1% here against −24.9%
  on a total-return basis in the 2004–2014 report.

## Verdict against the registered criteria

| | C1: Sharpe > 0.70 | C2: p < 0.01 | C3: drawdown no worse | C4: beats PEAD 2004–2014 | Result |
|---|:-:|:-:|:-:|:-:|:-:|
| B1 beta-hedged | no | no | no | no | fail |
| B2 vol-managed | no | no | no | no | fail |
| B3 PEAD + tsmom | yes | no | no | yes | fail |
| B4 PEAD + 3 sleeves | no | no | no | yes | fail |
| B5 hedged + 3 sleeves | no | no | no | no | fail |

## What happened

- **B1 (hedge) did what the plan predicted.** PEAD's appraisal ratio against SPY is 0.55 on the
  main window and about 0.38 on 2004–2014, and a perfectly hedged book earns roughly that. The
  realised Sharpes were 0.54 and 0.30, against predicted values of 0.58 and 0.34.
  - Hedging removes the market premium. That premium was positive in both windows: SPY's Sharpe
    was 0.44 on the main window.
  - At its native size the drawdown is smaller (−10.6% against −13.0%). At the same volatility it
    is not (−13.9%).
  - The hedge only makes sense if you expect the market premium to be about zero from here.
- **B2 (vol-managed) hurt.**
  - Dividing the average vol by the current vol averages above 1 (Jensen's inequality), so the book
    ran at 1.31× on average. That paid 0.32%/yr in trading and margin costs.
  - The scaling added exposure going into the 2025 drawdown: −6.6% in 2025 against +2.0% for PEAD.
  - On 2004–2014 it was a wash (−0.02), and the interval rules out a gain of +0.3 or more.
- **B3 (PEAD + trend) beat 0.70, but only because of 2022.**
  - Trend earned +43% in 2022 at raw size. B3's excess returns by year were +26.6% in 2022, then
    +0.5%, −2.0% and −2.4% in 2023–2025, against +8.7%, +4.5% and +2.0% for PEAD.
  - Trend then lost money during PEAD's own drawdown (July 2024 → April 2025). That is why B3's
    drawdown is deeper despite a correlation of −0.10.
- **B4 and B5 diluted PEAD** with near-zero sleeves. On the main window fx_carry had a Sharpe of
  0.10 and bond_carry 0.01, and equal risk weights gave them half the risk budget.

Diagnostics (not criteria) on the main window:
- After the warm-up only, PEAD scores 0.66 and the constructions 0.47, 0.47, 0.69, 0.54 and 0.42.
- With all costs ×3 and financing ×2, they score 0.54, 0.47, 0.72, 0.55 and 0.45.
- Cost is not what decides any of them.
- Every main-window paired interval is "vacuous" (a descriptive threshold of +0.3 Sharpe, chosen
  when writing this report): four years cannot tell these portfolios apart.

## Ceiling: the best any combination of these sleeves could do

These are the maximum Sharpes of weighted mixes, given each component's Sharpe and the correlation
matrix. They are ex post and biased upward.

| Main window, correlations measured in-window | Inputs | Best mix (long-only) | Unconstrained | Equal risk, static |
|---|---|---:|---:|---:|
| PEAD + tsmom + fx + bond, in-window Sharpes | 0.70, 0.23, 0.10, 0.01 | **0.77** | 0.77 | 0.52 |
| … plus the market (hedge, sign free) | market 0.44 | 0.77 | 0.77 | 0.59 |
| PEAD perfectly hedged (appraisal ratio vs SPY) | beta 0.36 | 0.55 | — | — |
| **Forward prior**: PEAD 0.60, sleeves at their 2018–26 hold-out Sharpes | 0.60, 0.21, 0.25, 0.13 | **0.72** | 0.72 | 0.60 |
| … plus the market at its 1927–2021 Sharpe | market 0.45 | 0.72 | 0.72 | 0.66 |

**The ceiling is about +0.07 Sharpe over PEAD** on this window, and about +0.12 with forward-looking
inputs. Why the ceiling is so low:
- PEAD's correlations with the sleeves (−0.10 to +0.07) are low, so diversification works.
- But the sleeves' Sharpes are only about 0.0–0.25. With zero correlation the best mix reaches
  sqrt(0.70² + Σs²), so three sleeves at 0.2 each add only about 0.08.
- The market hedge adds nothing, because PEAD already carries close to the ideal market exposure.
  SPY's in-window Sharpe (0.44) and PEAD's appraisal ratio (0.55) combine to
  sqrt(0.44² + 0.55²) = 0.70, which is exactly PEAD's own Sharpe. Removing beta can therefore only
  lower it.

Before 2018 the picture was different, because the sleeves were stronger then. Their Sharpes were
0.2–0.7, in-sample for their selection; since 2018 they have been about 0.2.
- On 2004–2014, PEAD + trend + bond carry peaks at 0.79, against PEAD's 0.55.
- On 2009–2014, where PEAD alone scores 0.91, adding FX carry lifts the peak to 1.24.

Even the ceiling could not be *confirmed*. Detecting a true +0.1 Sharpe gain at p < 0.01 with 80%
power, at a correlation of 0.9–0.95 with PEAD, needs about 100–200 years of daily data. Portfolio
construction around these sleeves cannot produce a clearly better strategy. Only new independent
return streams with Sharpe ≥ 0.3–0.4 would move the ceiling materially, and they need their own
forward test.

## Priors written in the PLAN, compared with the outcomes

| | Predicted (from published numbers) | Main | 2004–2014 |
|---|---|---:|---:|
| B1 | ≈ 0.58 main / 0.34 old, fails C1 and C4 | 0.54 | 0.30 |
| B3 | ≈ 0.64 if trend earns its 0.21 hold-out Sharpe | 0.74 (one year of trend) | 0.59 |
| B4 | ≈ 0.64 | 0.59 | 0.58 |
| B5 | ≈ 0.59 | 0.49 | 0.49 |
| Power | improvement of ≥ 0.5–1.4 needed to pass C2 | largest was +0.04 | — |

## Limits

- All windows had been seen before. The five constructions add five trials to the project ledger.
- **Account size.** At $100k, a 35% hedge is about one Micro E-mini contract (≈$30k notional), so
  the hedge moves in ~30% steps. The 58-instrument trend sleeve and the carry sleeves are not
  implementable at this size with futures. The simulation treats notional as continuous.
- SPY total return stands in for ES futures. Futures margin is not modelled. Bond carry is built
  from yields, not traded prices. The cost of resizing a sleeve assumes 5× gross notional per unit.
- PEAD's universe is today's S&P 500 in both windows (survivorship bias). The benchmark and the
  constructions share it.
- The first 3.6 months of the main window are PEAD by construction (the warm-up).

## Decision

No construction goes to paper trading. As the PLAN requires, there will be no re-weighting,
re-windowing or new constructions on these data. PEAD 2× unhedged stays the benchmark (0.70
measured; 0.5–0.7 expected forward).

Reproduce: `PYTHONPATH=. .venv/bin/python -m research.pead_portfolio.evaluate` (about 20 s). Tests:
`PYTHONPATH=. .venv/bin/python -m pytest tests/test_pead_portfolio.py`.
