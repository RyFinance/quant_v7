# Edge-graveyard candidates (v2, 2026-09-19)

Written by the research agent from the Phase 1 survival study (`REPORT.md`, `tables.md`,
`predictor_decay.csv` in this folder) and the literature catalogue. **No candidate below has been
backtested on quant_v7 price data.** Each needs its own pre-registration before any return is
computed. Expected Sharpe ranges are priors from the literature/OSAP decay, not results.

## What the survival study says to look for (short version)

1. Publication kills about 60% of an anomaly's return (OSAP replication of McLean–Pontiff: −30%
   out of sample, −58% after publication). In 2015–2024 the average predictor keeps only ~30% of
   its in-sample mean (mean Sharpe 0.79 → 0.23; 14% still have t ≥ 2).
2. **Survival is NOT concentrated in small caps.** Predictors whose premium depends on microcaps
   decayed the most (2015+ Sharpe 0.13 vs 0.29 for big-cap-robust ones; small-cap share is a
   significant negative in the survival model). The "capacity niche" idea (plan D) is not supported.
3. **Survivors use newer/costlier data**: options (2015+ Sharpe 0.50) and institutional holdings
   (0.56) beat accounting (0.26), price (0.17), volume (0.12), "alt/other" (−0.20).
4. **Negative-skew (crash-exposed) spreads survive; lottery-like positive-skew spreads die**
   (2015+ Sharpe 0.36 vs 0.10; skewness is significant in every survival regression). Survival
   looks like compensation for bearing a bad tail, not free mispricing.
5. By mechanism, slow reaction to firm news (M4: earnings streaks, issuance, revisions) and new
   data (M1: options) survive best; economic links (M5: customer/supplier, industry lead-lag) are
   dead (2015+ Sharpe −0.04); cross-sectional seasonality (the M2-like set) and liquidity/volume
   (M3) are mostly dead.
6. The plain earnings-surprise predictor (SUE) has a 2015+ Sharpe of 0.06, consistent with our own
   PEAD failure. Earnings *streaks* and revisions-based signals survived.

## Ranked new candidates

Rank = expected survival × feasible with our data × usable at $100k.

### C1. Earnings-surprise streaks (M4) — Loh & Warachka (2012, *Management Science*)
- **Why ranked first:** OSAP `EarningsStreak` is the 3rd-strongest 2015–2024 survivor (Sharpe 1.12
  all stocks, 0.55 ex-microcap, 0.36 VW) while plain SUE died (0.06). It is a direct refinement of
  the project's benchmark mechanism, and the data are on disk.
- **Signal (OSAP definition):** surprise = (actual EPS − consensus)/price at each announcement
  (`data/earnings_sue.parquet`; fallback: seasonal random-walk EPS surprise from
  `data/lse/financial_reports/*.parquet`, quarterly EPS with filing dates back to 1996). Keep only
  announcements whose surprise has the **same sign as the previous quarter's surprise** (a streak
  continues). Signal = that surprise. Long the top quintile, short the bottom quintile, enter
  day +2 after the announcement, hold 21 trading days. Loh & Warachka find drift is strong when a
  surprise extends a streak and negligible when it ends one; streaks explain about half of PEAD.
- **Data:** SUE file (2,756 events, 2015+), financial_reports (≈496 names, 1996+), official OHLC.
- **Why it might still work:** investors treat each surprise as independent (gambler's-fallacy
  under-reaction to *patterns*), a pattern harder to arbitrage than single surprises.
- **Caveats:** the SUE file is small (2,756 events, 2015+), so the development sample is thin; the
  financial_reports fallback gives 1996+ but with time-series (not analyst) surprises. 2004–2014 PEAD windows are consumed; this must be a separate registered trial,
  evaluated as an increment over the PEAD benchmark (report correlation with PEAD). S&P 500 only.
- **Expected Sharpe:** 0.3–0.6 standalone in large caps; likely correlated 0.3–0.5 with PEAD.

### C2. Implied-volatility *changes* (M1) — An, Ang, Bali & Cakici (2014, *JF*)
- **Why:** OSAP `dVolCall` (2015+ Sharpe 0.85; ex-microcap 0.80) and `dCPVolSpread` (1.20; 0.71)
  are among the few options signals that survive in big stocks. The registered options experiment
  (`research/options_signals/PLAN.md`) covers *levels* (O/S, IV spread, skew) but not *changes*.
- **Signal (OSAP: 30-day, delta 0.5 IV, first monthly difference, deciles):** monthly, ΔIV_call = change over the past month in ~30-day ATM call IV; ΔIV_put the
  same for puts. Long top quintile of ΔIV_call, short bottom; and a spread version: short top
  quintile of (ΔIV_put − ΔIV_call), long bottom. Hold one month.
- **Data:** OPRA daily bars for 100 stocks (2014+), IV via the frozen options_signals pipeline.
- **Why it might still work:** informed traders move option prices first; OPRA-derived IV is
  still costly to build, and the signal is in large, liquid names.
- **Caveats:** same universe and window as the registered options trials — must be a new,
  registered trial counted in the ledger; wait for that pull to finish; only 100 names → noisy.
- **Expected Sharpe:** 0.3–0.7 gross; after costs on 100 names 0.2–0.5.

### C3. Treasury auction cycle (M2 forced flows) — Lou, Yan & Zhang (2013, *RFS*)
- **Why:** the only forced-flow edge in the catalogue with post-publication evidence that it
  persists (Herb 2025, *JBF*, 2000–2016) and whose flow (deficits) grows faster than arbitrage capital.
- **Signal:** short 10-year Treasury exposure (IEF, or ZN/10Y micro futures) from the close 5 trading
  days before each 2/3/5/7/10/30-year coupon auction to the auction-day close; optional second rule
  long 1–3 days after. Flat otherwise.
- **Data:** auction dates in `data/lse/econ_calendar_us.parquet` (about 140 each of 2/3/5/7/10-year
  and 185 30-year auctions, 2015+); IEF daily / sovereign yields. No new data needed.
- **Why it might still work:** primary dealers must absorb supply and hedge ahead of it; slow-moving
  capital, and the trade is too small for big funds.
- **Caveats:** one instrument → low breadth and a long record needed; auctions cluster (monthly 2/5/7y
  in the same week), so count overlapping windows once.
- **Expected Sharpe:** 0.2–0.6 standalone; near-zero correlation with equity sleeves.

### C4. Net share issuance / buybacks (M4) — Pontiff & Woodgate (2008, *JF*); Daniel & Titman (2006, *JF*)
- **Why:** OSAP `ShareIss1Y` (2015+ Sharpe 0.82; ex-microcap 0.60; VW 0.49) and `ShareIss5Y` (0.88;
  0.63; VW 1.05) survive in big stocks; issuance is one of the best-surviving categories.
- **Signal:** split-adjusted share growth between t−18 and t−6 months (OSAP definition) from
  `weightedAverageShsOutDil` in `data/lse/financial_reports` (quarterly, with filing dates; adjust
  with `data/lse/stock_splits`; use only filings dated before the formation date). Long lowest
  quintile (net repurchasers), short highest; rebalance monthly, 12-month signal. 5-year variant
  as a pre-declared second rule.
- **Data:** financial_reports (≈496 names, 1996+), official OHLC for 503 names.
- **Caveats:** current S&P 500 members are survivors, and heavy repurchasers are over-represented
  among them; needs the same-universe control. Low turnover, so costs are small.
- **Expected Sharpe:** 0.2–0.5.

### C5. Earnings consistency (M4) — Alwathainani (2009, *British Accounting Review*)
- **Why:** OSAP `EarningsConsistency` 2015+ Sharpe 0.84 (ex-microcap 0.67; VW 0.42), with negative
  small-cap share (works better in big stocks).
- **Signal (OSAP):** average over the previous 48 months of annual EPS growth, where growth =
  (EPS − EPS 12 months ago) / average(|EPS| 12 and 24 months ago); drop if |growth| > 600% or if
  growth and its 12-month-ago value have different signs. Long top decile/quintile, short bottom;
  annual rebalance on filing dates.
- **Data:** `data/lse/financial_reports` quarterly EPS (sum trailing four quarters) with filing dates.
- **Caveats:** survivorship (consistent growers stay in the index); needs the same-universe control.
- **Expected Sharpe:** 0.2–0.5. Can share code and one registration with C4 (two pre-declared rules).

### C6. Momentum in high-volume stocks / seasonality-stripped momentum (M4) — Lee & Swaminathan (2000); Heston & Sadka (2008)
- OSAP ex-microcap 2015+ Sharpe 0.64 (`MomVol`) and 0.74 (`Mom12mOffSeason`). Price/volume only
  (official OHLC, 503 names). MomVol: 6-month momentum deciles within the top tercile of 6-month
  average turnover; hold 3 months. Mom12mOffSeason: average return over the past 11 months
  excluding the same calendar month a year ago.
- **Caveats:** current-member survivorship inflates momentum; negative skew (worst month −30%);
  re-testing a famous edge. Lower priority.
- **Expected Sharpe:** 0.2–0.5.

### C7 (downgraded). Earnings-announcement premium — Frazzini & Lamont (2007); Barber et al. (2013)
- Listed in v1; **downgraded**: Heitz, Narayanamoorthy & Zekhnini (SSRN 3296537) find the US
  premium disappeared after the 2004 8-K reform. Test only if a tester wants a cheap negative
  control.

## Already being tested by other agents (listed for completeness)
- **A1 Month-end balanced-fund rebalancing** (Harvey, Mazzoleni & Melone 2025) — `research/rebalancing/`.
- **A2 Leveraged-ETF close rebalancing** (Cheng & Madhavan 2009; Shum et al. 2016) — `research/letf_rebalancing/`.
- The registered options-level signals (skew, IV spread, O/S) are supported by the study:
  `SmileSlope` (Xing, Zhang & Zhao 2010) is the single strongest 2015+ survivor (Sharpe 1.47;
  ex-microcap 1.12; VW 1.38) and `CPVolSpread` holds 0.57.

## Blocked / downgraded
- EDGAR-based (Form 4 insiders, Lazy Prices, customer–supplier): **blocked on the SEC contact email**.
  Customer–supplier (M5) is also **downgraded**: OSAP `iomom_cust`/`iomom_supp` and the whole
  lead-lag family have ~zero or negative 2015+ returns.
- Small-cap "capacity niche" anomalies (plan D): **downgraded**; microcap-dependent predictors
  decayed most, and our data lack delisted names.
