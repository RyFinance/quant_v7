# Treasury auction cycle (edge-graveyard candidate C3): pre-registration

Written 2026-09-19, before any strategy return, event-window return or signal-return relation was
computed. Inspected so far: data layouts only (column names, date ranges of `data/multiasset/etf/IEF`,
the auction-event names and per-year counts in `data/lse/econ_calendar_us.parquet`, the Fama-French RF
end date) and the Treasury fiscaldata auction list (dates only).

## Source

Lou, Yan & Zhang (2013, RFS), "Anticipated and Repeated Shocks in Liquid Markets" (LSE-hosted PDF,
read 2026-09-19). Sample 1980-01 to 2008-06, 2/5/10-year notes, on-the-run CUSIPs, end-of-day prices.
- Treasury prices dip in the few days before an auction and recover shortly after; yields trace an
  inverted V peaking on the auction day.
- The on-the-run 2-year note's 5-day return before its auction is 8.89 bp (t about 3) below its
  5-day return after. Implied issuance costs of 9.07 / 16.81 / 18.43 bp of auction size (2/5/10-year).
- Longer maturities are hit harder; the effect spills across maturities.
- Their trading strategy (short 2-year vs a duration-matched bill/note hedge 10 days before, reverse
  10 days after) earns net Sharpe 0.84 for the 10-day window; short windows (<= 6 days) are
  unprofitable after bid-ask and repo costs.
Herb (2025, JBF) reports the auction premium persists through 2016.

## What this test is, and disclosures

- Bond ETF prices 2015+ (IEF, TLT) have already been viewed by this project's multi-asset tests (a
  different signal). This signal has not been computed on them before.
- The auction calendar in the LSE file starts 2015-01-05, so development is 2015-2019 only (about
  1,260 days, ~60 auction clusters). Power is low: a true Sharpe of 0.5 will not be distinguishable
  from 0 in development; the dev gate is a screen, not evidence.
- The paper's sample ends 2008; 2015-2026 is entirely post-publication for the original paper and
  overlaps Herb's sample only in 2015-2016.

## Data

- **Auction dates**: nominal coupon auctions of 2/3/5/7/10-year notes and 30-year bonds (original
  issues and reopenings). Primary source: `data/lse/econ_calendar_us.parquet`, `region_code == "US"`,
  events "2-Year Note Auction", "3-Year Note Auction", "5-Year Note Auction", "7-Year Note Auction",
  "10-Year Note Auction", "30-Year Bond Auction". The LSE file is missing 6 auctions (2y 2015-10, 3y
  2016-03, 5y 2015-02, 10y 2016-03, 30y 2016-03) and has no scheduled auctions after 2026-09-17. It
  is therefore unioned with the Treasury's official list (fiscaldata `auctions_query`, saved to
  `data/treasury/auctions_fiscaldata_raw.json`, filtered to security_type Note/Bond,
  inflation_index_security = No, floating_rate = No, original_security_term in the six tenors),
  de-duplicated on (date, tenor). The fiscaldata list also supplies Dec-2014 auctions (for early-Jan-2015
  post windows) and announced auctions to 2026-09-24. Excluded, fixed now: 20-year bonds (only from
  2020, so absent from development), TIPS, FRNs, bills. Auction dates are published in the Treasury's
  quarterly tentative schedule months ahead, so using them to position before the auction is not
  look-ahead. An auction date that is not a trading day in the price file maps to the next trading day
  (none expected).
- **Returns**: IEF daily auto-adjusted closes (`data/multiasset/etf/IEF.parquet`, yfinance, total
  return). Excess = R_IEF - RF, RF from `research.options_signals.signals.french_daily()` (ends
  2026-07-31; forward-filled for Aug-Sep 2026, disclosed). A short position earns -(R_IEF - RF)
  (short proceeds earn RF; borrow fee ignored, IEF is general collateral).
- Descriptive only: TLT with the same rules.

## Timing

Trading-day index i on the IEF calendar. A position w chosen at the close of day i-1 earns the
return of day i. For each auction on day a:
- **pre window**: return days a-4 .. a (close of a-5 to close of a; the auction settles at ~13:00 ET,
  before the close, so the auction-day close is after the auction);
- **post window**: return days a+1 .. a+3 (close of a to close of a+3).
Overlapping windows (auctions cluster: 3/10/30-year in one week, 2/5/7-year in another) are unions;
a day counts once.

## Candidates (three; instrument IEF)

1. **A1_pre_short**: w = -1 on every pre-window day; 0 otherwise.
2. **A2_post_long**: w = +1 on every post-window day that is not a pre-window day of any auction; 0
   otherwise.
3. **A3_combined**: A1 + A2 (the two sets are disjoint, so w in {-1, 0, +1}).

Position size: 1 x NAV notional in IEF. No parameters are tuned; windows are the candidate list's
(-5 to 0, +1 to +3), fixed now.

## Costs

Cost = c x |w_i - w_{i-1}| charged on day i (entering, exiting and flipping all pay; a flip pays 2c).
Base c = 2 bp per side (upper end of 1-2 bp for IEF), stress c = 6 bp (3x).

## Accounting

Daily, net of costs, excess over T-bills, all trading days in the window, flat days = 0.
Sharpe = mean / sd x sqrt(252).

## Windows and gates

- Development: 2015-01-02 -> 2019-12-31. Prices are truncated at 2019-12-31 before positions are
  evaluated (auction dates from 2020 may define the last pre-windows of 2019, legitimately, since
  schedules are pre-announced).
- Validation: 2020-01-01 -> 2026-09-18. Locked in code until `research/auction_cycle/VALIDATION_UNLOCK.md`
  is registered with a matching hash in `research/preregistrations.jsonl` (`validation_unlocked`
  copied from `research/options_signals/evaluate.py`). Runs once, only for candidates passing development.
- Development gate: net base Sharpe >= 0.5.
- Validation pass: net base Sharpe >= 0.75; stress annual mean > 0; one-sided circular-block bootstrap
  p < 0.05/3 (21-day blocks, 5,000 draws, `research.options_signals.evaluate.block_bootstrap_p`);
  Sharpe above the PEAD benchmark's 0.70.
- Also reported: 95% block-bootstrap Sharpe interval (`sharpe_ci`, 21-day blocks), `null_kind` at 0.5,
  deflated Sharpe with 65 trials (trial variance = variance of the three candidates' daily Sharpes in
  the development run), annual return, vol, max drawdown, results by year, active days, hit rate,
  mean bp per window.
- Descriptive, not gated: gross Sharpe; one-day-late entry (w lagged 1 day); the TLT version; a
  development-window event study (mean IEF excess return by event day -5..+5 around 10-year auctions
  and around all auctions).

## PEAD correlation and blend (fixed now; reported, not a gate)

PEAD daily excess = `reports/pead_audit/wide_5p0_curves.csv` mtm_rf.pct_change() - rf_index.pct_change()
(2021-08 to 2025-06, inside validation). Blend = 0.5 x PEAD scaled to 10% annual vol + 0.5 x candidate
scaled to 10% annual vol (PEAD scale from its full-file vol; candidate scale from its development net
vol; constants). Computed only in the validation run, since PEAD has no development-window data;
if no candidate passes development, correlation and blend are not computed (the validation window
stays locked).

## Expectations stated in advance

- LYZ magnitudes translate to a few bp of IEF per window; with ~24 clusters a year, round-trip costs
  (~4-8 bp per cluster for A3) take a large share. Paper found short windows unprofitable after costs.
- Prior: net Sharpe 0 to 0.5 in development; the 2015-2019 sample includes the 2016 and 2018 yield
  sell-offs, which help any short-duration rule regardless of timing (A1 is short ~50% of days).
- A1 carries negative duration carry; A2 positive.
