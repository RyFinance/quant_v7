# PEAD portfolio construction: hedge, vol-manage or combine? (pre-registration)

Written 2026-09-18, before any combined statistic existed. No correlation between PEAD and any sleeve, no
sleeve statistic on the PEAD window, and no statistic of any construction below has been computed.
Changing anything here after registration requires a new, separately registered amendment written
before the affected result exists.

## Question

The benchmark is the PEAD 2× book (`reports/pead_audit/REPORT.md`): excess Sharpe **0.70**
[−0.25, 1.70], 2021-08-11 → 2025-06-27, marked daily, net of costs, idle cash at T-bills; about 83%
long, beta 0.35, alpha 4.2%/yr with t = 1.15. Does hedging its market beta, managing its volatility,
or combining it with the project's existing multi-asset sleeves give a **clearly** better portfolio?
This is portfolio construction on existing return series. No new signal and no new market data.

## Status of the evidence: development only

Every window used here has been examined before:
- the PEAD 2021–2025 window picked the 2× configuration out of a sweep, and its Sharpe, beta and alpha are published;
- the 2004–2014 PEAD hold-out has been used once (Sharpe 0.52, beta 0.54, alpha t 1.12);
- the sleeves' development-era (to 2017) and 2018–2026 hold-out Sharpes are published in
  `reports/multiasset/REPORT.md`: tsmom_broad 0.47 / 0.21, fx_carry 0.45 / 0.25, bond_carry 0.31 /
  0.13 and vix_basis 0.98 / 0.29, with an 86% drawdown.

Earlier related trials: `research/higher_sharpe.py` tried an SPY-hedged SUE sleeve (`pead_sue_hedged`,
a different signal and universe; −0.20 on 2024–2025). `research/blend_sleeves.py` blended the
higher_sharpe stock sleeves. The five constructions below add five trials to the project ledger.

**All results are development evidence only.** A construction that passes does not go to capital. It
goes to a forward paper test (next section). A construction that fails is reported as failed.

## Inputs (existing files only)

| Symbol | Series | Source |
|---|---|---|
| r^P (main) | PEAD 2× daily excess return | `reports/pead_audit/wide_5p0_curves.csv`: `mtm_rf.pct_change() − rf_index.pct_change()`, first (NaN) row dropped → 2021-08-12 … 2025-06-27, 973 days |
| G (main) | PEAD 2× gross exposure / previous NAV, carried into each day | recomputed from the ledger with `research.pead_audit.mtm_audit` (`positions`, `closes`, `mtm_book`, cash earns RF); the run asserts the rebuilt NAV equals `mtm_rf` to 1e-9 |
| r^P (old) | PEAD model 2004–2014 daily excess return | `reports/pead_2004_2014/model.csv`: `return` − French RF → 2004-01-02 … 2014-12-31 |
| G (old) | gross exposure | `model.csv` `gross`, lagged one day (the exposure carried into the day) |
| r^M | hedge instrument (ES-futures proxy): SPY total return − RF | main: `data/stocks_raw_2014/SPY.parquet` `Adj Close`; old: `data/yf_2003_2015/SPY.parquet` `close` (auto-adjusted) |
| RF | daily risk-free | `research.options_signals.signals.french_daily()["rf"]`, forward-filled onto the calendar |
| MKT | market for reported beta | French `mkt_rf` (the audit's convention) |
| r^k | sleeves: `tsmom_broad`, `fx_carry`, `bond_carry` (daily excess, net of their own costs) | main: `reports/multiasset/holdout/holdout_returns.csv`; old: `reports/multiasset/dev_sleeve_returns.csv` |

Calendars were checked (dates only). The sleeve, SPY and RF dates cover every PEAD day in both
windows. In the old window, tsmom_broad starts 2004-02-03 and fx_carry 2009-02-03. A missing sleeve
day is treated as missing, never as zero.

## Conventions common to all constructions (fixed)

- **Rebalance and timing.** Decisions are made at the close of the last trading day *t* of each
  calendar month, using returns through *t* only. They are traded at the close of *t+1* and the new
  weights earn returns from *t+2*. This is a full day of implementation lag, as in the multi-asset
  plan.
- **Warm-up.** An estimate needs at least **63** PEAD observations in the evaluation window. Before
  the first effective date, every construction **is** PEAD: weight 1, no hedge, no overlays. PEAD
  history before a window's start is not available and is never assumed.
- **Estimation window** W_t: the last min(252, n_t) days up to *t*, where n_t is the number of PEAD
  observations so far. Beta uses the last min(126, n_t) days.
- **Drift.** Between rebalances every position drifts with its own return:
  w_k ← w_k(1 + r_k)/(1 + r_C). Construction daily excess return: r_C = Σ w_k r_k − costs − financing.
- **Costs.**
  - Scaling the PEAD stock book: 5 bps per side on |Δw_P| × G (the bot's 10 bps round trip).
  - Market hedge: 1 bp per side on |Δh|. The quarterly ES roll costs 2 bps × |h| (close plus open),
    charged on the first trading day on or after the 10th of March, June, September and December.
  - Overlay sleeves: 10 bps per unit of |Δw_k|. This is 2 bps per side on an assumed 5× gross
    notional per unit of sleeve, a deliberately conservative assumption.
  - Initial overlay and hedge positions are charged as trades from zero. No liquidation cost at the
    window end, which is the benchmark's convention too.
- **Financing.** Leverage of the stock book costs 1.5%/yr above RF on max(0, w_P × G − 1) of NAV
  (a broker margin spread). Futures and overlay sleeves are already excess returns.
- Weights are fixed rules on past data only. Nothing is optimised on realised Sharpe.

## The five constructions (fixed)

- **B1 — beta-hedged PEAD.** β_t = OLS slope of r^P on r^M over the last min(126, n_t) days, clamped
  to [0, 1.5]. Targets: w_P = 1, hedge h = −β_t (short the ES proxy).
- **B2 — volatility-managed PEAD** (Moreira & Muir 2017, using inverse vol as specified).
  σ̂_s = standard deviation of r^P over the 21 days ending *s*, for every day *s* with at least 21
  observations. σ̄_t = the mean of all σ̂_s with s ≤ t (expanding). Target w_P = min(2, σ̄_t/σ̂_t).
  Exposure is changed by trading the stock book (5 bps per side on |Δw_P| × G, plus financing
  above 1× gross).
- **B3 — PEAD + tsmom_broad, equal risk.** Rule RP on the components {P, tsmom_broad}.
- **B4 — PEAD + fx_carry + bond_carry + tsmom_broad, equal risk.** Rule RP.
  - `vix_basis` is **excluded**. It is short volatility with an 86% drawdown, and a rule that sizes by
    trailing vol levers it up exactly before its crashes. Any cap chosen now would be chosen already
    knowing its crash.
  - `overnight_intraday_reversal` is excluded: its break-even cost is below realistic auction costs.
- **B5 — B1's hedged PEAD + the B4 sleeves, equal risk.** Rule RP on {P̃, fx_carry, bond_carry,
  tsmom_broad}. P̃'s trailing returns are r^P − β_t r^M over W_t, with B1's β_t at that date. The
  targets are w_P from RP and h = −w_P × β_t.

**Rule RP** (equal risk, scaled to the PEAD component's own risk) at each decision date *t*:
1. A component takes part if it has at least 63 non-missing returns in W_t.
2. σ_k is the standard deviation of its non-missing returns in W_t, and u_k = 1/σ_k.
3. Σ is the pairwise-complete sample covariance over W_t, with eigenvalues floored at 0.
4. λ = σ_P / sqrt(uᵀΣu), where σ_P is the PEAD component's (P, or P̃ in B5) volatility over W_t.
   Then w = λu, so the ex-ante combined volatility equals the PEAD component's own trailing vol.
5. Each weight is clipped: w_P ≤ 1.5 and each sleeve ≤ 4, with no renormalisation after clipping.

The scaling to PEAD's trailing risk is a refinement of the suggested constructions. It keeps the
comparison at like-for-like risk, so a construction cannot look better on drawdown just by being
smaller. It also keeps w_P near or below 1, so the stock book needs no margin.

## Windows

- **Main:** 2021-08-12 → 2025-06-27, the PEAD benchmark's days. All five constructions.
- **Old:** 2004-01-02 → 2014-12-31, the PEAD model's days. All five constructions can be computed.
  B3–B5 use the development-era sleeves. Those were selected on this era, so they are in-sample here,
  which **favours** B3–B5 on this window. fx_carry enters B4/B5 once it has 63 observations in W_t.

## Metrics (per construction and window, and for PEAD)

- Annualised excess Sharpe (mean/sd × √252), with a 95% interval from `sharpe_ci` (21-day circular
  blocks, 5,000 draws).
- Excess CAGR (geometric), annualised vol and max drawdown of the excess-return wealth index.
- Beta, alpha and alpha t against French MKT (OLS with Newey-West, 20 lags).
- Correlation with PEAD.
- Average weights, average hedge, turnover, and yearly cost and financing drag.
- **Paired test.** Construction minus PEAD, compared at equal risk. Statistic: ΔSR = SR_C − SR_P
  (equivalently, the mean daily difference after scaling the construction to PEAD's volatility).
  Paired circular block bootstrap: 21-day blocks, 5,000 draws, seed 20260918, the same resampled
  days for both series. One-sided p = (1 + #{ΔSR* − ΔSR ≥ ΔSR}) / 5,001. The unscaled mean-difference
  p is reported as secondary.

## Pass criteria (all four required; Bonferroni over 5 constructions)

1. **C1:** on the main window, the net excess Sharpe is higher than PEAD's on the same days
   (0.70, compared unrounded).
2. **C2:** on the main window, the paired one-sided **p < 0.01** (0.05/5).
3. **C3:** on the main window, the max drawdown is **no worse than PEAD's**. It is measured after
   scaling the construction's daily excess returns by a constant so its vol equals PEAD's vol over
   the window. The native-scale drawdown is also reported.
4. **C4:** on the old window, the net excess Sharpe is higher than PEAD's there (point estimate).

## Diagnostics (reported, not criteria)

- The main window after warm-up only, from the first effective date on.
- All costs ×3 and the financing spread ×2.
- The secondary unscaled mean-difference test, and native-scale drawdowns.

## Ceiling ("expected Sharpe") check (descriptive, fixed now)

On the main window, from the in-window Sharpes *s* and correlation matrix *R*:
- **Set A** {PEAD, tsmom_broad, fx_carry, bond_carry}: the unconstrained maximum sqrt(sᵀR⁻¹s); the
  long-only maximum by numerical optimisation; and the equal-risk value Σs / sqrt(1ᵀR1).
- **Set B** = A plus SPY excess, with the market weight free in sign (that is, hedging).
- **{PEAD, market}:** the appraisal ratio of PEAD against SPY, which is the Sharpe of a perfectly
  hedged PEAD.
- **Forward-prior ceiling:** the same maximum with the in-window correlations, but with inputs that are
  not fitted to this window: PEAD 0.60 (the audit's realistic range 0.5–0.7), the sleeves at their
  published 2018–2026 hold-out Sharpes (0.21, 0.25, 0.13), and SPY at the French market's Sharpe from
  1927 to 2021-07.
- The same in-window ceilings on the old window, for the overlap each sleeve has.

These maxima are ex post and biased upward. They are the ceiling of the approach, not an estimate
of what is achievable.

## Prior expectations, from published numbers (written before any result)

- **B1.** A perfectly hedged book's Sharpe is roughly PEAD's appraisal ratio, about the alpha t /
  √years: 1.15/√3.9 ≈ 0.58 on the main window and 1.12/√11 ≈ 0.34 on the old window. Both are
  below PEAD's 0.70 and 0.52. **B1 is expected to fail C1 and C4**, because the market premium was
  positive in both windows. Its case rests on lower risk if the forward market premium is lower.
- **B3/B4.** Equal risk weights help only when the added sleeves are strong enough. With zero
  correlation, equal-risk PEAD + one sleeve beats PEAD only if the sleeve's Sharpe exceeds
  (√2 − 1) × 0.70 ≈ 0.29. With three sleeves, their Sharpes must sum to more than 0.70. The
  published 2018–2026 sleeve Sharpes (0.21, and 0.59 summed) fall short of both, so the expected
  results are about 0.64 for both B3 and B4, **below 0.70**. A Sharpe-proportional risk budget
  would do better, but the only legitimate prior Sharpes (development era: tsmom 0.47, fx 0.45,
  bond 0.31, PEAD 0.52) are nearly equal. So equal risk is what past data supports.
- **B5:** about (0.58 + 0.59)/2 ≈ 0.59. **B2:** no strong prior; later work (Cederburg et al. 2020)
  finds out-of-sample gains from vol management unreliable.
- **Power.** The SE of a Sharpe difference over 3.9 years is about sqrt(2(1 − ρ)/3.9). To pass C2
  at α = 0.01 with 80% power, the improvement must be roughly 0.5 (ρ = 0.95), 1.0 (ρ = 0.8) or
  1.4 (ρ = 0.6) Sharpe points. **A pass is unlikely**, and a fail is mostly "not detectable", not
  "proven worse". The report classifies each result with `null_kind`.

## After the test

- **If any construction passes all four:** freeze its code and rules, and run it as a daily forward
  paper book beside PEAD for at least 12 months. Only the forward period counts toward capital.
- **If none passes:** report the null, the estimates and the ceiling. Do not re-weight, re-window or
  add constructions on these data.

## Deliverables

- Code in `research/pead_portfolio/` and tests in `tests/test_pead_portfolio.py`. The tests cover no
  look-ahead in betas and weights, and cost accounting.
- Report in `reports/pead_portfolio/REPORT.md`, with `results.json` and the daily series.
- The run refuses to start if this file's sha256 differs from its registered hash.
