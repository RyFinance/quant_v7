# Crash-protected / volatility-managed momentum — nothing beat SPMO, and nothing beat the baseline

**Date:** 2026-09-19
**Pre-registration:** `research/vol_managed_momentum/PLAN.md`, sha256 `77272677a988ff3eebe800e65ca07713c84e20d48f9877dd5d6e4489d7c5bda8`, registered 2026-09-19T23:03:25-0700, **before any exposure series or result was computed**. Five variants registered, five variants run, no additions, no amendments.
**Code:** `research/vol_managed_momentum/run.py`. Harness `research/momentum_lab/core.py`, **unmodified**.
**Artifacts:** `results.json`, `exposures.csv`, `{B_baseline,V1..V5}_nav.csv`, `dilution_V*_nav.csv` (all in this directory).

---

## Answer

**No. Nothing beat SPMO's Sharpe in both halves.** Two variants edged past SPMO in the first half only (V1 at 0.717 and V3 at 0.705 against 0.70) and were beaten roughly two-to-one in the second, which the registered rule calls a null. The more damning result is the internal one: **not one of the five overlays beat the *unscaled baseline* in any window, on Sharpe or on CAGR.** All five reduced Sharpe, all five reduced CAGR, and every one of them lost to the trivial control of holding the same average amount of cash statically.

This is a 5-for-5 sweep in the wrong direction. The literature's headline result does not survive the long-only, unlevered constraint.

---

## Headline table — base cost (5bps/side)

| variant | avg exp | 2011..2018 CAGR / Sharpe / vol / maxDD | 2019..2026 CAGR / Sharpe / vol / maxDD | 2011..2026 CAGR / Sharpe / vol / maxDD |
|---|---|---|---|---|
| **B baseline** (no overlay) | 1.000 | 14.10% / **0.74** / 19.8% / −26.9% | 19.99% / **0.66** / 31.0% / −35.9% | 16.95% / **0.67** / 25.9% / −35.9% |
| **V1** const-vol 20% | 0.862 | 13.03% / 0.72 / 19.0% / −25.4% | 13.17% / 0.53 / 23.1% / −35.9% | 13.10% / 0.62 / 21.1% / −35.9% |
| **V2** const-vol 15% | 0.713 | 10.77% / 0.68 / 16.3% / −21.1% | 10.59% / 0.49 / 18.4% / −32.6% | 10.68% / 0.58 / 17.3% / −32.6% |
| **V3** SPY 200-day gate | 0.847 | 12.21% / 0.71 / 18.1% / −26.7% | 6.74% / 0.28 / 25.8% / −33.9% | 9.49% / 0.45 / 22.2% / −33.9% |
| **V4** V1 × V3 | 0.751 | 11.46% / 0.67 / 17.9% / −25.1% | 5.94% / 0.26 / 18.3% / −24.4% | 8.72% / 0.47 / 18.1% / −25.1% |
| **V5** inverse variance | 0.550 | 8.50% / 0.68 / 12.5% / −17.9% | 8.39% / 0.51 / 11.7% / −14.6% | 8.44% / 0.60 / 12.1% / −17.9% |
| | | | | |
| SPMO | — | 10.90% / **0.70** / — / −23.4% | 22.38% / **0.89** / — / −30.9% | 18.87% / **0.84** / — / −30.9% |
| MTUM | — | 14.02% / 0.92 / — / −22.1% | 16.94% / 0.67 / — / −34.1% | 15.69% / 0.73 / — / −34.1% |
| SPY | — | 11.21% / 0.78 / — / −19.3% | 17.30% / 0.78 / — / −33.7% | 14.16% / 0.77 / — / −33.7% |
| RSP | — | 10.32% / 0.69 / — / −22.9% | 13.56% / 0.60 / — / −39.0% | 11.90% / 0.64 / — / −39.0% |

"avg exp" is the mean of the exposure series across the 189 monthly decision dates in 2011..2026. Mean *realised* daily gross from the NAV files matches it to within 0.004 for every variant, confirming the overlay was actually applied.

### Against the registered decision rule (beat SPMO's 0.70 / 0.89 in **both** halves)

| variant | H1 vs 0.70 | H2 vs 0.89 | verdict |
|---|---|---|---|
| B baseline | 0.744 ✓ | 0.655 ✗ | null (the known result) |
| V1 | 0.717 ✓ | 0.534 ✗ | **null** |
| V2 | 0.685 ✗ | 0.492 ✗ | fail |
| V3 | 0.705 ✓ (+0.005) | 0.276 ✗ | **null** |
| V4 | 0.674 ✗ | 0.258 ✗ | fail |
| V5 | 0.680 ✗ | 0.514 ✗ | fail |

Every overlay is *further* from the bar than the thing it was supposed to improve.

## Stress cost (15bps/side)

| variant | turnover | 2011..2018 | 2019..2026 | 2011..2026 |
|---|---|---|---|---|
| B baseline | 7.84 | 13.25% / 0.71 | 19.01% / 0.63 | 16.04% / 0.64 |
| V1 | 6.92 | 12.22% / 0.68 | 12.43% / 0.51 | 12.32% / 0.58 |
| V2 | 5.82 | 10.07% / 0.65 | 10.01% / 0.46 | 10.04% / 0.55 |
| V3 | 7.79 | 11.38% / 0.66 | 5.87% / 0.24 | 8.64% / 0.41 |
| V4 | 6.90 | 10.65% / 0.63 | 5.25% / 0.22 | 7.97% / 0.43 |
| V5 | 6.13 | 7.75% / 0.62 | 7.81% / 0.47 | 7.78% / 0.55 |

Scaling down cuts turnover (less capital to trade), so the overlays lose slightly *less* at stress cost in relative terms. It does not change any conclusion.

## Bootstrap Sharpe intervals (20-day circular block, 95%)

Nothing here is a win, so no interval is being used to claim one; they are reported because the plan required them and because they set the honest limit on what this experiment can say.

| | 2011..2018 | 2019..2026 | 2011..2026 |
|---|---|---|---|
| B baseline | [0.18, 1.38] | [0.07, 1.26] | [0.27, 1.10] |
| V1 | [0.16, 1.35] | [−0.05, 1.20] | [0.20, 1.05] |
| V2 | [0.13, 1.31] | [−0.09, 1.17] | [0.17, 1.02] |
| V3 | [0.12, 1.36] | [−0.22, 0.79] | [0.08, 0.85] |
| V4 | [0.10, 1.31] | [−0.27, 0.79] | [0.07, 0.88] |
| V5 | [0.12, 1.30] | [−0.06, 1.13] | [0.19, 1.03] |
| SPMO | [−0.19, 1.78] | [0.27, 1.59] | [0.32, 1.44] |
| MTUM | [0.25, 1.69] | [0.05, 1.35] | [0.26, 1.24] |
| SPY | [0.17, 1.43] | [0.11, 1.55] | [0.32, 1.27] |
| RSP | [0.07, 1.35] | [−0.09, 1.36] | [0.17, 1.14] |

**These intervals are very wide and they all overlap.** Taken one at a time, no single variant's loss is statistically distinguishable from the baseline. What carries the conclusion is not any one interval but the pattern: five pre-registered overlays, three windows each, two cost levels, and the sign is negative in **all thirty** cells. That is not a power problem, it is a direction problem.

## FF5+UMD attribution (base-cost daily returns, 2011-01-01 onward, HAC lags=10)

| variant | alpha %/yr | alpha t | MktRF | SMB | HML | RMW | CMA | UMD |
|---|---|---|---|---|---|---|---|---|
| B baseline | +0.07 | 0.03 | 1.15 | 0.02 | 0.19 | −0.40 | −0.10 | 0.66 |
| V1 | −1.76 | −0.82 | 0.98 | 0.05 | 0.14 | −0.20 | −0.07 | 0.53 |
| V2 | −2.03 | −1.09 | 0.81 | 0.04 | 0.12 | −0.13 | −0.06 | 0.43 |
| V3 | −1.10 | −0.30 | 0.69 | 0.10 | 0.09 | −0.42 | −0.13 | 0.62 |
| V4 | −1.08 | −0.33 | 0.61 | 0.12 | 0.05 | −0.24 | −0.07 | 0.49 |
| V5 | +0.35 | 0.17 | 0.46 | 0.07 | 0.03 | −0.04 | −0.07 | 0.27 |

No variant has significant alpha; the overlays mostly just shrink the market and UMD betas toward zero, which is what mechanically scaling a book toward cash does. The book is a 1.15-beta, 0.66-UMD vehicle with no alpha, and scaling it produces a lower-beta, lower-UMD vehicle with no alpha.

*Harness note, no change made to `core.py`:* `Lab.run` computes `res['attribution']` from the loop variable `f` after the loop has finished, so the built-in attribution is fitted on the **stress**-cost return series, not the base one. The table above is fitted on the base series via `lab.attribution` called directly. The stress-cost alphas stored under `results[*]['attribution']` in `results.json` are, for the record: B −0.71%/yr (t −0.27), V1 −2.46 (−1.14), V2 −2.62 (−1.40), V3 −1.88 (−0.51), V4 −1.78 (−0.55), V5 −0.27 (−0.13). The baseline's published bar of "alpha t = −0.27" is the stress-series figure. Neither version changes any conclusion.

---

## Causality: the test passed

Every exposure is computed **only from data through session t−1**, strictly before decision date *t*, and the harness then fills the resulting target at the *next* session's open — so the overlay is two steps behind the trade, not one.

**Registered test:** multiply every baseline daily return **and** every SPY close after a cut date (2018-06-29) by 3 (plus 0.05 on returns), rebuild all five exposure series, and compare against the unperturbed series on every decision date at or before the cut.

**Result: passed.** Over the 114 decision dates on or before the cut, the maximum absolute difference is exactly **0.0** for all five variants — bit-identical, not merely close.

The test has power. After the cut, the same perturbation moves the exposures by up to 0.689 (V1), 0.661 (V2), 1.000 (V3), 0.664 (V4) and 0.871 (V5), so the series genuinely do respond to the data being perturbed; they simply respond only forward in time. A test that passed because the exposures ignored the input would have shown zero movement on both sides of the cut.

**Warm-up, disclosed:** V1/V2/V5 need 126 sessions of the strategy's own returns, which do not exist at the first 2011 decision date. As pre-registered, the *same unscaled targets* were executed from 2009-01-01 to seed the trailing windows. Only the volatility of 2009–2010 is consumed, never its return, and no pre-2011 number appears anywhere in this report. The README's warning that pre-2011 point-in-time membership is thin applies to return estimates; a 126-day volatility estimate is far less sensitive to which names were in the index, and the alternative (leaving early-2011 unscaled) would have been an untested exception baked into three variants.

---

## The dilution control, and why it is a stricter bar than it looks

Registered control: blend the baseline with T-bills at each variant's average exposure *a*, i.e. `a × B + (1−a) × bill`.

| variant | a | dilution control Sharpe (H1 / H2 / full) | dilution control maxDD (full) | variant Sharpe (full) | variant maxDD (full) |
|---|---|---|---|---|---|
| V1 | 0.862 | 0.744 / 0.655 / **0.674** | −31.5% | 0.616 | −35.9% |
| V2 | 0.713 | 0.744 / 0.655 / **0.674** | −26.5% | 0.583 | −32.6% |
| V3 | 0.847 | 0.744 / 0.655 / **0.674** | −31.0% | 0.450 | −33.9% |
| V4 | 0.751 | 0.744 / 0.655 / **0.674** | −27.8% | 0.467 | −25.1% |
| V5 | 0.550 | 0.744 / 0.655 / **0.674** | −20.9% | 0.601 | −17.9% |

The control's Sharpe is identical for every *a*, and identical to the baseline's, **by construction**: the excess return of `a × B + (1−a) × rf` is exactly `a × (B − rf)`, so both mean and standard deviation scale by *a* and the ratio is invariant. The numbers above reproduce 0.7443 / 0.6552 / 0.6743 to four decimals for all five values of *a*, which is a useful arithmetic check on the pipeline.

The consequence is the sharpest framing of the whole experiment: **in a long-only unlevered book, holding cash cannot raise the Sharpe ratio at all.** The only way a down-scaling overlay can help is by *timing* — being small in the bad months and large in the good ones. So the honest bar is not "did the variant beat a diluted baseline", it is **"did the variant beat the baseline's own Sharpe of 0.674"**. None did: 0.616, 0.583, 0.450, 0.467, 0.601.

The plan asked for the dilution control on the best variant. By full-sample Sharpe the best is V1 (0.616); by drawdown reduction it is V5. Both are in the table, as are all five, since the control costs nothing to compute.

**Drawdown, honestly attributed.** V5 cuts max drawdown from −35.9% to −17.9%, which looks like crash protection. But the static blend at the same *a* = 0.550 already delivers −20.9% with a *higher* CAGR (10.68% vs 8.44%) and a higher Sharpe. So of V5's 18-point drawdown reduction, about 15 points are pure cash and only ~3 points are timing — bought at a cost of 2.2 percentage points of CAGR per year. V4 is the same story (−25.1% vs the control's −27.8%, at 4.9pp/yr of forgone CAGR). And V1, V2 and V3 have drawdowns that are **worse** than their own static controls (−35.9 vs −31.5, −32.6 vs −26.5, −33.9 vs −31.0). Three of the five overlays made the drawdown worse than doing nothing but holding cash.

---

## Why it failed — three diagnostics

These are explanatory diagnostics on results already in hand, not new variants.

### 1. The machinery worked. The economics did not.

V1 targeted 20% volatility and delivered 21.1% realised over 2011..2026 (19.0% / 23.1% by half), against the baseline's 25.9%. The overlay did exactly what it was built to do. Sharpe still fell from 0.67 to 0.62. This is not an implementation failure.

### 2. In this book, high trailing volatility predicts *high* forward returns

Mean baseline return in the month **following** each exposure quartile (189 monthly decision dates; the unconditional mean is +1.48%):

| variant | Q1 = lowest exposure | Q2 | Q3 | Q4 = highest exposure | Spearman(exposure, next-month return) |
|---|---|---|---|---|---|
| V1 | **+2.57%** | +1.43% | +1.42% | +0.49% | **−0.161** |
| V2 | **+2.57%** | +1.43% | +1.71% | +0.19% | **−0.178** |
| V3 | **+2.58%** | +1.65% | +1.03% | +0.65% | **−0.170** |
| V4 | **+3.16%** | +0.85% | +1.43% | +0.45% | **−0.168** |
| V5 | **+2.30%** | +2.01% | +0.50% | +1.11% | **−0.118** |

The relationship is monotonic and it points the wrong way for all five. Every overlay is smallest exactly when the next month is best. The papers' premise — that the strategy's own trailing volatility forecasts *bad* returns — is true for a long-short momentum book, where high-vol panic states are when the short leg gets run over. It is false for this long-only book, where the same high-vol states are rebounds and the long leg makes money.

### 3. Trailing volatility did not see the one crash it was built for, and sold the bottom

The baseline's −35.9% maximum drawdown is 2020-02-19 → 2020-03-23: twenty-three sessions. Exposure at the decision dates through that crash:

| decision date | V1 | V2 | V3 | V4 | V5 |
|---|---|---|---|---|---|
| 2020-01-02 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| 2020-02-03 | 1.00 | 0.98 | 1.00 | 1.00 | 0.72 |
| 2020-03-02 | **1.00** | 0.88 | 0.00 | 0.00 | 0.19 |
| 2020-04-01 (after the trough) | **0.43** | 0.32 | 0.00 | 0.00 | 0.02 |
| 2020-05-01 | 0.40 | 0.30 | 0.00 | 0.00 | 0.08 |

Trailing 126-session volatility through January and February 2020 was low, so V1 entered the crash at **full exposure** and its drawdown is *identical to the baseline's*, −35.9%, to the basis point. It then cut to 0.43 on April 1 — after the March 23 bottom — and sat out a +13.0% month. A 126-session window cannot turn around inside a 23-session crash. It can only arrive late and sell the low.

### 4. The market-state gate is a long-short instrument used on a long-only book

V3 sat out 29 of 189 months (15.3%), flipping 26 times. The baseline's mean return in the months it sat out was **+3.87%**, against **+1.05%** in the months it stayed in; compounded, the skipped months were worth **+168.8%**. It sat out October 2011 (+12.7%), October 2015 (+6.9%), March 2016 (+7.0%), January 2019 (+12.1%), April 2020 (+13.0%), October 2022 (+17.5%), November 2023 (+12.8%) and April 2026 (+27.7%).

This is Daniel & Moskowitz's own mechanism, read correctly. They find momentum crashes in post-bear rebounds — and the crash is in the **short** leg, where beaten-down losers rocket. A gate that steps aside for the rebound protects a long-short book from exactly that. Our book has no short leg, so the rebound is not a crash, it is the best month of the cycle, and the gate deletes it. V3 and V4 are the two worst variants in the study for precisely this reason.

---

## Relation to the parallel ETF test

A parallel agent is testing whether these same overlays improve buyable funds (SPMO, MTUM, SPY) by as much. The framing that question was meant to settle — "is this generic market timing rather than something about this stock book?" — does not arise here, because **there is no gain to attribute.** Every overlay lost on this book. Two readings remain open, and the ETF result decides between them:

- If the overlays also fail on SPMO/MTUM/SPY, then trailing-volatility and 200-day-MA timing simply did not work on US equity beta over 2011–2026, and this is a fact about the period, not about the book.
- If the overlays *help* the ETFs but hurt this book, the difference is concentrated risk: a 20-name equal-weight book at 26% volatility has idiosyncratic swings that trailing volatility cannot time, while a broad fund's volatility is nearly all market beta, which is the thing a 200-day MA actually tracks.

Either way, the conclusion for **this** book stands unchanged and does not depend on their answer.

---

## What this rules out and what it does not

**Ruled out for this book:** constant-volatility targeting at 20% and 15%, a 200-day market-state gate, their product, and Moreira–Muir inverse-variance scaling — as *down-only, unlevered* overlays on the frozen 12-1 point-in-time book, monthly, over 2011–2026. All five are worse than doing nothing, at both cost levels, in all three windows.

**Not ruled out:** the same overlays applied with leverage. The literature's result depends on scaling exposure *up* in calm periods as much as down in turbulent ones, and a cap at 1.0 removes half the mechanism — V1 sits at the cap 49% of the time, so half its decisions are no-ops in one direction only. Whether a levered version works is a different experiment against a different (and considerably less buyable) bar, and it was not registered here. Also not ruled out: overlays on the short leg of a book that has one — but this book does not have one, and that is the whole finding.

**The standing null is unchanged.** The baseline remains 0.67 against SPMO's 0.84, and after five more registered trials it is still 0.67. This adds five entries to a ledger of roughly 110 trials whose deflated-Sharpe probability was already below 0.5; the correct effect of this report on that ledger is to push it slightly further down, not up.
