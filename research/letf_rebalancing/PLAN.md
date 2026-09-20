# Leveraged-ETF close rebalancing on ES/NQ (candidate A2): pre-registration

Written 2026-09-19 before any strategy return or predictor–return statistic was computed. Checked
beforehand: ProShares file formats and AUM coverage (levels only), and the bar data conventions
already fixed in `research/intraday/PLAN.md`.

**Benchmark to beat:** PEAD 2× excess Sharpe **0.70**, measured the same way (daily, net, excess).

## Relationship to the earlier I2 test (disclosure)

`research/intraday/` tested I2, rest-of-day momentum: sign of ln P(15:30)/P_prev(16:00), traded
15:30→16:00 on ES and NQ every non-roll day. Development 2016-06 → 2020-12 gave net Sharpe 0.38
(gross 0.80) and I2 stopped at the 0.5 gate; its 2021–2026 validation was never run.

The LETF rebalancing trade always has the **same sign** as I2, because L(L−1) > 0 for every
leverage L in {3, 2, −1, −2, −3}. The new element here is **conditioning on, or sizing by, the
predicted flow relative to the liquidity that must absorb it**. So the development window's
unconditional version is already known (0.38). Both candidates below trade on subsets of I2's days,
or reweight them. Their development results are therefore not independent of I2's result. The
decisive evidence is the 2021–2026 validation window, which nobody has seen for this rule family
and in which LETF assets are largest.

## Mechanism and exact definition

Cheng & Madhavan (2009, *Journal of Investment Management*, "The Dynamics of Leveraged and Inverse
ETFs") show that a fund with leverage L and assets A_{t−1} at the prior close must, to restore
exposure L·A_t, trade at the close

    Δ_t = A_{t−1} · (L² − L) · r_t

in the underlying, where r_t is the index close-to-close return. The trade is positive (a buy) after up
days for both leveraged (L = 2, 3) and inverse (L = −1, −2, −3) funds.

- **Shum, Hejazi, Haryanto & Rodier (2016, *Review of Finance* 20(6), 2379–2409)** find that
  end-of-day volatility rises with the ratio of potential rebalancing trades to total trading volume,
  2006–2011. The effect is largest on volatile days. This motivates normalising by volume.
- **Ivanov & Lenkey (2018, *Journal of Financial Markets* 41, 36–56)** find that same-day capital flows
  (creations/redemptions, which tend to be contrarian) substantially offset rebalancing demand. After
  controls, the late-day effect is economically insignificant, 2006–2014. We cannot observe
  same-day flows at 15:30, so the predicted flow here is gross of that offset. This is the main
  reason to expect failure.
- Recent work on LETF "loop gains" (Zhao 2026, arXiv 2608.03703, "Preying on Leveraged ETFs"; arXiv
  2608.22768, "The Loop-Gain Matrix") defines a loop gain as rebalancing capital (assets ×
  leverage constant) times the price impact of the venue that must clear it. The ratio φ below is
  that quantity's flow-over-liquidity analogue.

## Data

- **Bars:** `data/lse/futures_30m/ES_F.parquet`, `NQ_F.parquet`. These are the same bars and
  conventions as the intraday plan, loaded with `research.intraday.evaluate.load_bars`/`daily_table`.
  - P(15:30) is the close of the 15:00 bar. P(16:00) is the close of the 15:30 bar.
  - r_t = P(15:30)/P_prev(16:00) − 1, the index return known at 15:30.
- **LETF assets:** ProShares daily fund files, `https://accounts.profunds.com/etfdata/ByFund/<T>-historical_nav.csv`,
  saved to `data/letf_proshares/` on 2026-09-19. They give daily NAV, shares outstanding and "Assets
  Under Management". AUM = NAV × shares was checked to within 0.2%. There are no missing days since 2016.
  - Nasdaq-100 → NQ: TQQQ (+3), SQQQ (−3), QLD (+2), QID (−2), PSQ (−1).
  - S&P 500 → ES: UPRO (+3), SPXU (−3), SSO (+2), SDS (−2), SH (−1).
  - **Coverage gap:** Direxion funds (SPXL/SPXS, and sector funds such as SOXL) are not covered. The
    site is behind a bot wall, yfinance `get_shares_full` returns nothing for them, and SEC N-PORT is
    out of scope (no approved contact email). TQQQ/SQQQ dominate Nasdaq-100 LETF assets. For the
    S&P 500, SPXL is roughly UPRO-sized, so ES rebalancing gamma is understated, perhaps by about a
    third to a half. A missing fund that scales proportionally cancels in the rank-based rules below.
    The sector funds (e.g. SOXL) map to neither contract and are excluded by design.
- **No look-ahead in AUM:** for trading day t, the rules use the latest ProShares row dated strictly
  before t, the prior close.
- **Liquidity:** V̄_t = median over the previous 20 trading days (excluding t) of the 15:30-bar
  volume × P(16:00) × multiplier (ES 50, NQ 20), in dollars. Day t's own 15:30 bar is never used in
  any signal.

## Signal

For instrument k ∈ {ES, NQ} on day t:

    G_{k,t−1} = Σ_{funds i on k's index} AUM_{i,t−1} · L_i(L_i − 1)     (rebalancing gamma, $)
    F_{k,t}   = G_{k,t−1} · r_{k,t}                                      (predicted close flow, $)
    φ_{k,t}   = |F_{k,t}| / V̄_{k,t}                                       (flow / typical last-30-min volume)

The expanding reference distribution for (k, t) is φ_k over all earlier valid days, from the first
bar day. At least 60 earlier observations are required; before that the instrument is flat.

## Candidates (two)

Both enter at P(15:30), exit at P(16:00), and trade ES and NQ at 0.5 × NAV notional per unit of
position.

1. **L1_flow_top_quintile:** position = sign(F_{k,t}) if φ_{k,t} ≥ the 80th percentile of the expanding
   reference distribution, else 0.
2. **L2_flow_scaled:** position = sign(F_{k,t}) · min(φ_{k,t} / median(reference), 3). The average
   position is roughly 1, larger on high-flow days and capped at 3.

## Costs, calendar, accounting

- Cost per side is 0.5 bp (base) or 1.5 bp (stress) of traded notional, so 2 × cost × |position| × 0.5
  per instrument-day.
- **Roll exclusion:** as in the intraday plan (`roll_days`), days from the Thursday before the third
  Friday of Mar/Jun/Sep/Dec through the next Monday are flat. They still count in the reference
  distributions: φ does not depend on the roll, and the volume median is robust.
- A day needs P_prev(16:00), P(15:30) and P(16:00) on both instruments (common ES/NQ calendar, as in
  I1–I4).
- Returns are daily, net, with days out of the market counted as 0. Futures P&L is already an excess
  return. The French daily RF is used only to report a cash-plus-futures total-return figure.

## Windows and gates

- Development: 2016-06-01 → 2020-12-31. The intraday prices in this window were already seen through
  I1–I4, including the unconditional I2.
- Validation: 2021-01-01 → 2026-09-17. It stays locked until
  `research/letf_rebalancing/VALIDATION_UNLOCK.md` is registered, and runs once, only for
  development-selected candidates.
- Development gate: net base Sharpe ≥ 0.5.
- Validation pass requires all of:
  - net base Sharpe ≥ 0.75;
  - stressed mean > 0;
  - one-sided circular-block bootstrap p < 0.05/2 = 0.025 (`block_bootstrap_p`, 21-day blocks, 5,000
    draws);
  - net Sharpe > 0.70.

## Reported (not gates)

- The 95% Sharpe interval (`sharpe_ci`, 21-day blocks), with `null_kind` at 0.5.
- Deflated Sharpe with 60 trials and a fixed cross-trial annual-Sharpe dispersion of 0.5, so the
  per-day variance is 0.25/252.
- Hit rate on active days, active days, by-year returns, and max drawdown.
- Correlation with the PEAD benchmark daily excess return, `mtm_rf.pct_change() −
  rf_index.pct_change()` from `reports/pead_audit/wide_5p0_curves.csv`.
- **Dose-response (diagnostic):** instrument-days (non-roll, in-window) are bucketed by the
  expanding-quintile rank of φ (1–5, set by the 20/40/60/80th percentiles of the reference
  distribution). For each bucket we report the mean gross signed return sign(F)·r_last in bp, the
  t-statistic, the hit rate and n. "Grows with flow" means Q5 − Q1 > 0 and Spearman(bucket, mean)
  > 0. It is reported in both windows.
- Mean G by year, showing the growth in LETF assets.

## Expectations stated in advance

Ivanov & Lenkey's capital-flow offset, and the thin gross margin I2 already showed (0.80 gross,
0.38 net), make a validation pass unlikely. The top-quintile rule halves cost drag per day in the
market but also cuts active days by about 80%. The prior is a net Sharpe of −0.3 to 0.8.
