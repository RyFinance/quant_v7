# Residual (idiosyncratic) momentum — results

**Pre-registration:** `research/residual_momentum/PLAN.md`, sha256 `567204f4a58c...`, registered
2026-09-19T23:02:45-0700, before any score or return was computed. Four variants were registered and
exactly four were run. No amendment was filed and no variant was added after seeing a result.

**Code:** `research/residual_momentum/scores.py` (signals), `research/residual_momentum/run.py`
(runner). `research/momentum_lab/core.py` was used as-is and not modified.

**Outputs:** `R{1,2,3,4}_*_nav.csv` (daily NAV, base costs, 3,950 sessions 2011-01-03..2026-09-17),
`results.json` (all stats, attributions, bootstrap intervals, verification records, diagnostics).

---

## Headline

**Nothing beat SPMO's Sharpe in both halves.** All four variants beat SPMO in 2011–2018 and all four
lost to it in 2019–2026. Under the lab's rule that is a null, four times over, and it is reported as
one.

The secondary result is more interesting than the headline. Residualising the score did what Blitz,
Huij & Martens say it does to the *factor exposures*: market beta fell from 1.15 to 1.07, UMD loading
from 0.66 to 0.39, and the FF5+UMD intercept moved from −0.7%/yr (t = −0.27) to +3.4%/yr (t = 1.44).
It did not do what they say to the *risk*: volatility fell ~11–18%, not by half, and the maximum
drawdown got slightly **worse** in the second half. And t = 1.44 is not significance.

---

## Variants as registered

| | construction |
|---|---|
| **R1** | Daily excess returns regressed on a constant + MktRF over the trailing 756 sessions; score = sum of residuals over t−252…t−21 |
| **R2** | Same, on a constant + MktRF + SMB + HML |
| **R3** | R2's residual sum ÷ the sd of those same residuals over the same window (the Blitz–Huij–Martens construction) |
| **R4** | Control, *not* residual momentum: raw 12-1 return ÷ trailing 252-session daily return volatility |

All four run with harness defaults: point-in-time universe, 20 slots, equal weight, monthly
rebalance, `min_score=0.0`, no sector cap, no exposure overlay, frozen execution engine.

## Base costs (5bps/side)

| variant | 2011–2018 CAGR / Sharpe / vol / maxDD | 2019–2026 | 2011–2026 | turnover |
|---|---|---|---|---|
| **R1** CAPM-residual | 16.83% / **0.92** / 18.38% / −23.39% | 23.63% / 0.80 / 28.24% / −38.27% | 20.12% / 0.83 / 23.73% / −38.27% | 9.2× |
| **R2** FF3-residual | 15.90% / **0.88** / 18.27% / −23.74% | 24.57% / 0.84 / 27.17% / −37.48% | 20.08% / 0.84 / 23.07% / −37.48% | 9.6× |
| **R3** FF3-residual std | 12.47% / **0.75** / 16.96% / −23.24% | 23.18% / 0.85 / 24.93% / −39.31% | 17.60% / 0.80 / 21.24% / −39.31% | 10.3× |
| **R4** risk-adj raw (control) | 15.49% / **0.89** / 17.36% / −24.75% | 19.07% / 0.69 / 26.22% / −34.79% | 17.23% / 0.76 / 22.15% / −34.79% | 8.7× |
| baseline 12-1 | 14.10% / 0.74 / 19.81% / −26.91% | 19.99% / 0.66 / 31.04% / −35.89% | 16.95% / 0.67 / 25.93% / −35.89% | 7.8× |
| **SPMO** (the bar) | 10.90% / **0.70** / 14.88% / −23.39% | 22.38% / **0.89** / 22.32% / −30.95% | 18.87% / 0.84 / 20.41% / −30.95% | |
| MTUM | 14.02% / 0.92 / 14.83% / −22.12% | 16.94% / 0.67 / 23.35% / −34.08% | 15.69% / 0.73 / 20.17% / −34.08% | |
| SPY | 11.21% / 0.78 / 14.51% / −19.35% | 17.30% / 0.78 / 19.27% / −33.72% | 14.16% / 0.77 / 17.01% / −33.72% | |
| RSP | 10.32% / 0.69 / 15.35% / −22.88% | 13.56% / 0.60 / 19.78% / −39.04% | 11.90% / 0.64 / 17.66% / −39.04% | |

## Stress costs (15bps/side)

| variant | 2011–2018 | 2019–2026 | 2011–2026 |
|---|---|---|---|
| **R1** | 15.75% / 0.87 / 18.39% / −23.84% | 22.52% / 0.76 / 28.24% / −38.33% | 19.03% / 0.79 / 23.74% / −38.33% |
| **R2** | 14.79% / 0.82 / 18.28% / −24.28% | 23.39% / 0.81 / 27.16% / −37.53% | 18.93% / 0.80 / 23.07% / −37.53% |
| **R3** | 11.30% / 0.69 / 16.96% / −23.58% | 21.92% / 0.81 / 24.93% / −39.37% | 16.39% / 0.75 / 21.25% / −39.37% |
| **R4** | 14.49% / 0.84 / 17.37% / −24.91% | 18.03% / 0.66 / 26.22% / −34.84% | 16.21% / 0.72 / 22.16% / −34.84% |
| baseline 12-1 | 13.25% / 0.71 / 19.81% / −27.05% | 19.01% / 0.63 / 31.04% / −35.93% | 16.04% / 0.64 / 25.94% / −35.93% |

Turnover rises from the baseline's 7.8× to 8.7–10.3×, so the extra 10bps/side costs these variants
more than it costs the baseline. At stress costs R3 loses its first-half win over SPMO outright
(0.69 vs 0.70) and R2's full-record Sharpe (0.80) falls below SPMO's 0.84.

## Verdict against the bar

SPMO: **0.70** first half, **0.89** second half.

| | 2011–2018 vs 0.70 | 2019–2026 vs 0.89 | both halves? |
|---|---|---|---|
| R1 | 0.92 win | 0.80 **loss** | **no** |
| R2 | 0.88 win | 0.84 **loss** | **no** |
| R3 | 0.75 win | 0.85 **loss** | **no** |
| R4 | 0.89 win | 0.69 **loss** | **no** |

Every variant wins one half and loses the other. Per the lab's rule that is a null. Nothing here is
called a win, but the bootstrap intervals were computed for all of them anyway and they settle the
question on their own.

## Bootstrap Sharpe intervals (95%, 20-day circular block, base costs)

| | 2011–2018 | 2019–2026 | 2011–2026 |
|---|---|---|---|
| R1 | [0.34, 1.55] | [0.17, 1.47] | [0.39, 1.28] |
| R2 | [0.30, 1.52] | [0.20, 1.54] | [0.41, 1.32] |
| R3 | [0.16, 1.39] | [0.21, 1.53] | [0.36, 1.27] |
| R4 | [0.31, 1.54] | [0.11, 1.28] | [0.35, 1.19] |
| SPMO | [−0.19, 1.78] | [0.27, 1.59] | [0.32, 1.44] |

Every variant's interval overlaps SPMO's in every window, and every interval is roughly a full Sharpe
point wide. Even the first-half "wins" of 0.92 against 0.70 are inside sampling noise. Fifteen years
of daily data is not enough to separate these.

## FF5+UMD attribution (2011–2026 daily, HAC lag 10) — the interesting number

| variant | alpha/yr | alpha t | MktRF | SMB | HML | RMW | CMA | UMD |
|---|---|---|---|---|---|---|---|---|
| **R1** | +3.2% | **1.31** | 1.074 | 0.041 | 0.365 | −0.442 | 0.006 | **0.506** |
| **R2** | +3.4% | **1.44** | 1.071 | 0.042 | 0.321 | −0.388 | −0.040 | **0.392** |
| **R3** | +1.3% | 0.66 | 1.033 | 0.016 | 0.326 | −0.270 | −0.036 | 0.361 |
| **R4** control | +0.1% | 0.04 | 1.012 | −0.075 | 0.187 | −0.249 | −0.066 | **0.593** |
| baseline 12-1 | −0.7% | −0.27 | **1.153** | 0.018 | 0.186 | −0.403 | −0.097 | **0.656** |

Yes: residual momentum reduces the factor betas and produces a non-zero intercept.

- Market beta drops 1.153 → 1.071 (R2). The UMD loading drops 0.656 → 0.392, i.e. the portfolio stops
  being a levered repackaging of the momentum factor. Adding SMB and HML to the regression (R2 vs R1)
  cuts UMD further, 0.506 → 0.392, which is the mechanism working as advertised.
- The intercept moves from −0.7%/yr to +3.4%/yr. **But t = 1.44.** That is not a rejection of zero
  alpha; it is the absence of a rejection, in the other direction. The honest statement is that the
  baseline demonstrably has no alpha and R2 has not demonstrated any either.
- R3, the paper's actual construction, has the *lowest* factor loadings of the three residual
  variants and the *weakest* alpha (t = 0.66). Dividing by the residual sd threw away more signal
  than noise here.
- The control is the informative row. R4 gets market beta down to 1.012 by pure volatility scaling,
  with no factor model at all — but it keeps a UMD loading of 0.593 and delivers alpha t = 0.04. So
  the factor regression **is** doing work beyond volatility scaling, specifically on the momentum
  loading and on the intercept. It is just not doing enough work to clear the bar.

## Is the risk-reduction claim supported?

This is where the paper's specific claim fails on this data. BHM claim a similar return at roughly
half the volatility, with much smaller crashes.

| | vol 2011–2026 | vs baseline | maxDD 1st half | maxDD 2nd half |
|---|---|---|---|---|
| baseline | 25.93% | — | −26.91% | −35.89% |
| R1 | 23.73% | −8% | −23.39% | −38.27% |
| R2 | 23.07% | −11% | −23.74% | −37.48% |
| R3 | 21.24% | **−18%** | −23.24% | **−39.31%** |
| R4 | 22.15% | −15% | −24.75% | −34.79% |

Volatility falls by 8–18%, nowhere near half, and the control R4 gets 15% of that reduction with no
factor model at all — so most of the volatility benefit is plain volatility scaling, not
residualisation. Drawdowns improve by 2–4 points in the first half and get **worse** by 1.6–3.4
points in the second half for the three residual variants. The crash protection is not there: 2020
and 2022 hit these portfolios as hard as they hit the baseline.

Return did not stay flat either — R1 and R2 raised CAGR from 16.95% to ~20.1% while lowering
volatility. That is a better outcome than the paper predicts, and it is exactly the shape of result
that should make you suspicious rather than pleased, given how thin the statistical separation is.

## Relationship to the baseline

Daily return correlation with the frozen 12-1 baseline: R1 0.949, R2 0.940, R3 0.917, R4 0.967.
These are not different strategies. They are the same 20-name momentum portfolio with a modestly
re-ordered ranking, which is why every variant tracks the baseline's half-by-half pattern (weaker
first half, stronger second half than SPMO) rather than breaking it.

## Implementation notes and verification

- **Fast path verified.** The batched solver was checked against a slow, obviously-correct per-stock
  loop (explicit masking, `np.linalg.lstsq`, one stock and one date at a time) on 6 randomly drawn
  stock-months per variant, 18 in total. **The check passed:** max absolute difference 1.5e−15 (R1),
  1.2e−12 (R2), 9.1e−11 (R3, the larger figure being the sd division amplifying the scale). Records
  are in `results.json` under `verification`.
- **Method.** One design matrix per decision date; per-stock normal equations formed by masked matrix
  products (`XᵀX` built from the 756×p² outer-product columns times the validity mask) and solved for
  all eligible stocks at once with `np.linalg.solve`. Missing observations are excluded from the
  normal equations rather than filled. All four scores for 189 decision dates × ~500 stocks build in
  under 3 seconds.
- **Windows.** Estimation: the 756 sessions ending *at* the decision date — all data known at the
  decision, execution is the next session's open. Scoring: sessions t−251…t−21, which is exactly the
  span of daily returns whose product is the baseline's `close.shift(21)/close.shift(252) − 1`.
- **Eligibility.** A stock is scored only if it has a return on every factor-available session in
  both the estimation and scoring windows. No gap filling. This leaves 198.2 of 200 eligible names
  scored per date on average.
- **Factor tail.** `lab.factors` ends 2026-07-31 while the price panel ends 2026-09-17, so the last
  33 sessions have no factor rows. Those sessions are masked out of the regressions rather than
  filled, which affects only the last two decision dates (2026-08-03 regresses on 755 of 756
  sessions, 2026-09-01 on 734). The alternative — letting those dates go unscored — would have parked
  the portfolio in cash for the final six weeks, which is an artifact, not a result.
- **Intercept.** Every regression includes a constant, so the 12-1 residual sum measures a stock's
  excess return over that span net of its factor exposures *and* net of its own trailing 3-year mean.
  This is the BHM construction.
- **A design choice worth flagging, not tested here.** The estimation window ends at t while the
  scoring window ends at t−21, so the skipped month contributes to the betas but not to the score.
  That is standard and contains no look-ahead, but whether ending estimation at t−21 instead changes
  anything is an untested question. It was not registered and was not run. It would need an
  amendment.

## What this costs the project

Four more trials on a ledger of roughly 110, with a deflated-Sharpe probability already below 0.5.
The correct reading of R1/R2's +3%/yr intercept at t = 1.4 is that it is the sort of number this
search produces by chance at this point, and the both-halves rule exists precisely to stop it being
written up as an edge. Residual momentum is a real and well-motivated improvement to the *shape* of
the baseline's factor exposures, and it is not an edge over an ETF anyone can buy.
