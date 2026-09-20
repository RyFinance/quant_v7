# Rebalancing-pressure front-running (edge-graveyard candidate A1): pre-registration

Written 2026-09-19, before any strategy return, signal-return relation or backtest was computed.
Only data layouts were inspected (column names, first/last dates of `data/multiasset/etf/SPY,IEF`,
the PEAD curve file's date range).

**Source.** Harvey, Mazzoleni & Melone, "The Unintended Consequences of Rebalancing", NBER w33554
(March 2025, revised January 2026). Read from the NBER PDF. Their setup:

- Simulate a 60/40 portfolio of S&P 500 futures and 10-year Treasury note futures (daily, 1997-09-10
  to 2023-03-17). Weight drift: w' = w(1+R_eq) / (w(1+R_eq) + (1-w)(1+R_bd)).
- **Threshold signal** (B.1): the drifted equity weight minus 60%, measured at the close of day t;
  the simulated portfolio resets to 60% when |w - 60%| >= delta. The paper's signal is the average of
  the delta-signals for delta = 0.0%, 0.1%, ..., 2.5% (26 values), eq. (2).
- **Calendar signal** (B.2): the same drift, reset to 60% on the last business day of each month.
  Its predictability sits in the last week of the month ("week4" = last 5 trading days).
- Headline: a one-standard-deviation rise in the Threshold (Calendar) signal predicts a 16 (17) bp
  lower S&P 500 return next day, and 4 (2) bp higher Treasury return. Pressure reverts within about
  two weeks. Predictability became significant in the early 2000s.
- **Front-running strategy** (Section 4): R_{t+1} = (R_SP,t+1 - R_10y,t+1) x w_t, with w_t the average
  of (i) -Threshold_t / 1.5% and (ii) the modified Calendar signal: sign(-Calendar_t) if t is in the
  last 5 trading days of the month; sign(Calendar_{t-4}) on the first business day of the new month
  (reversal); 0 otherwise. Reported (Table 6, 1997-2023): 10.2% p.a., vol 9.17%, Sharpe 1.11 gross,
  skew 5.23, "close to 1" net of costs; 0.90 excluding Sep 2008-Mar 2009 and Mar 2020.

**What this test is.** Every price window 2003-2026 has been viewed by this project, and the paper's
own sample (1997-2023) overlaps almost all of it. This is an implementability-after-costs test with
instruments we can trade (ETFs), not an independent discovery.

## Instruments and data

- Equity leg SPY, bond leg IEF (7-10y Treasury ETF, the closest traded proxy to the 10-year note; we
  have no ZN/TY series). Daily auto-adjusted closes from `data/multiasset/etf/{SPY,IEF}.parquet`
  (2003-01-02 to 2026-09-18). Returns are close-to-close total returns.
- The simulated 60/40 portfolio uses the same SPY and IEF returns (the paper uses futures excess
  returns; the difference in drift is second order).
- Long-short P&L: a dollar-neutral position (long SPY / short IEF, or the reverse) has excess return
  R_SPY - R_IEF (financing and short proceeds at the T-bill rate cancel). No RF series is needed for the
  gated candidates.

## Candidates (three)

All trade the SPY-minus-IEF spread with notional w_t per leg (fraction of NAV), set at the close of
day t and earning (R_SPY - R_IEF) over t -> t+1.

1. **R1_calendar**: w_t = modified Calendar signal alone (values -1, 0, +1): sign(-Cal_t) on each of
   the last 5 trading days of a month; sign(Cal_{t-4}) on the first trading day of a month, where
   Cal_{t-4} is the Calendar signal 4 trading days earlier; 0 otherwise.
2. **R2_threshold**: w_t = -Threshold_t / 1.5% (the paper's rescaling; averaged over 26 deltas).
3. **R3_combined**: w_t = 0.5 x R1 + 0.5 x R2 (the paper's Section 4 strategy).

Timing: the signal uses returns through the close of t. The paper assumes the position is set at that
close. We keep that timing (implementable as a market-on-close order sized from prices a few minutes
before 16:00; the Calendar sign rarely flips in the last minutes). The month-end window uses the
exchange trading calendar, which is known in advance. Warm-up: the simulated portfolios start at 60%
on 2003-01-02; evaluation starts 2003-02-03.

Descriptive, not gated (reported for context only): (a) each candidate with a one-day execution lag
(w_{t-1} applied to R_{t+1}); (b) gross returns; (c) the equity-only leg (w_t x (R_SPY - RF)) for
R3; (d) mean spread return per active day for R1 in bp.

## Costs

Cost = c x |w_t - w_{t-1}| x 2 legs, charged on day t+1. Base c = 2 bp per side (upper end of
1-2 bp for SPY/IEF). Stress c = 6 bp per side (3x).

## Accounting

Daily returns over all trading days in the window, net of costs, days with w = 0 count as zero.
Sharpe = mean/sd x sqrt(252).

## Windows and gates

- Development: 2003-02-03 -> 2014-12-31 (about the earliest half of the 2003-2026 history).
- Validation: 2015-01-01 -> 2026-09-18. Locked in code until `research/rebalancing/VALIDATION_UNLOCK.md`
  is registered with a matching hash in `research/preregistrations.jsonl`. Run once, only for
  candidates that pass development.
- Development gate: net base Sharpe >= 0.5.
- Validation pass: net base Sharpe >= 0.75; stress mean > 0; one-sided circular-block bootstrap
  p < 0.05/3 (21-day blocks, 5,000 draws, `research.options_signals.evaluate.block_bootstrap_p`);
  and Sharpe above the PEAD benchmark's 0.70.
- Also reported: 95% block-bootstrap Sharpe interval (`sharpe_ci`, 21-day blocks), `null_kind` at 0.5,
  deflated Sharpe with 60 project trials (trial variance = variance of the three candidates' daily
  Sharpes in the same run), annual return, vol, max drawdown, hit rate (of active days), number of
  position changes, max |w|, results by year.

## PEAD overlay (fixed in advance)

PEAD benchmark daily excess = `reports/pead_audit/wide_5p0_curves.csv` mtm_rf.pct_change() -
rf_index.pct_change() (2021-08 to 2025-06, inside validation). Overlay = 0.5 x PEAD scaled to 10%
annual vol + 0.5 x candidate scaled to 10% annual vol, where the PEAD scale uses its full-file vol and
the candidate scale uses its development-window net vol (both constants, no rebalancing of weights).
Reported with the candidate's correlation to PEAD on common dates, in the validation run only (the
benchmark has no development-window data).

## Expectations stated in advance

- The paper's Sharpe is driven by crises (skew 5.23; GFC and COVID). Development (2003-2014) contains
  the GFC, so the development Sharpe is likely flattered; validation contains COVID.
- Threshold turnover is high (w moves daily); costs at 2 bp x 2 legs could take a large share.
- Publicity in 2025 may have eroded the last ~1.5 years.
- Prior: net Sharpe 0.2 to 0.9 in development, lower in validation.
