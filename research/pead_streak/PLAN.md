# Pre-registration: earnings-surprise streaks (edge-graveyard candidate C1)

Written before any strategy return was computed. Only data coverage was examined (event counts per
year, the announcement-time distribution, the 60% event-date quantile).

## Hypothesis
Loh & Warachka (2012, *Management Science*): post-earnings drift is concentrated in announcements
whose surprise has the same sign as the previous quarter's surprise (a streak continues). Question:
does conditioning PEAD on a streak give a strategy that beats the PEAD 2x benchmark (excess Sharpe
0.70, `reports/pead_audit/REPORT.md`)?

## Data and coverage
- Events: `data/earnings_sue_expanded.parquet` (18,844 announcements, 489 tickers,
  2015-04-01 -> 2025-06-26). Effective trade dates: `data/pead_signal_expanded.parquet` (`date` =
  first session that can react; after-close announcements already moved to the next session).
- Prices: `data/multiasset/stocks/{T}.parquet` adjusted daily closes. Universe = today's S&P 500
  (survivorship bias upward; shared by the control).
- Rates and market: `research.options_signals.signals.french_daily()` (`rf`, `mkt_rf`).
- **This is development evidence only.** The whole 2015-2025 SUE history has been used by earlier
  PEAD work (the production model was trained on it; the benchmark itself covers 2021-08 -> 2025-06),
  so the "validation" half below is only a first look at a locked, not an unseen, window.

## Signal (fixed)
- Surprise sign = sign(`surprise_pct`); zero or missing surprise = no sign (never in a streak).
- Previous surprise = the same ticker's immediately preceding announcement in the file, used only if
  its raw announcement time is at least 30 and at most 200 calendar days before the current one AND
  its effective date is strictly before the current effective date (known before entry).
- Streak event: current sign == previous sign (both nonzero).

## Timing and holding (fixed)
- Day 0 = effective date (first calendar session >= `date`). Enter at the close of day +1 (skips the
  announcement reaction), hold 20 sessions, exit at the close of day +21: the position earns the
  close-to-close returns of days +2..+21. 20 sessions ~ the one-month holding period of the Loh &
  Warachka / OSAP `EarningsStreak` calendar-time portfolios and the benchmark's 20-session hold.
- A ticker already held ignores a new event until it exits.

## Candidates (2; the Bonferroni divisor is 2)
- **S1 streak long-short**: long positive-after-positive events, short negative-after-negative
  events. Equal weight within each leg, rebalanced daily: long leg +0.5, short leg -0.5 of NAV
  (a leg with no names is 0).
- **S2 streak long-only**: long positive-after-positive events, equal weight, gross 1.0.
- ~~S3 (benchmark `wide_5p0` book filtered to streak entries)~~ dropped: that ledger covers only
  2021-08 -> 2025-06, entirely inside the validation window, so it has no development sample.

## Controls (no model, same universe, same timing, same sizing and costs)
- **C1 all-events long-short** (control for S1): long every positive-surprise event, short every
  negative one (streak or not).
- **C2 all-positive long-only** (control for S2): long every positive-surprise event.

## Accounting (fixed)
- Daily mark-to-market. Daily excess return = sum_i w_i (r_i - rf) - costs - borrow
  (short proceeds earn rf; long-only has no idle cash).
- Costs: 5 bps per side (10 bps round trip) on daily turnover, where turnover = sum |w_t - w_pre|
  and w_pre are yesterday's weights drifted by today's returns (entries, exits and rebalancing).
  Borrow 0.5%/yr on short gross. Stress: 3x both (15 bps per side, 1.5%/yr borrow).
- A missing price for a held name is a zero return (count reported).

## Windows
- Development: events with effective date 2015-04-01 .. 2021-06-30 (~first 60% of events); returns
  2015-04-01 .. 2021-06-30 (positions still open at the end are cut there).
- Validation: events with effective date 2021-07-01 .. 2025-06-30; returns 2021-07-01 .. last exit.
  Locked: the code refuses to run it unless `research/pead_streak/VALIDATION_UNLOCK.md` is registered
  in `research/preregistrations.jsonl` with a matching sha256 (same guard as
  `research/options_signals/evaluate.py`). Validation runs once, only for candidates passing dev.

## Statistics
- Annualised excess Sharpe (sqrt 252), 95% circular-block bootstrap CI (`sharpe_ci`, block 21),
  `null_kind` at 0.5, deflated Sharpe with 65 trials (trial variance = variance of the daily Sharpe
  across S1, S2, C1, C2 in the development run).
- One-sided p: `block_bootstrap_p` on daily excess returns, block 21.
- Beta and alpha on `mkt_rf` (OLS, Newey-West 20 lags); excess return and Sharpe by year.
- Candidate minus control: Sharpe and bootstrap p of the daily difference (information only).
- Correlation with the benchmark daily excess (`wide_5p0_curves.csv`: mtm_rf.pct_change() -
  rf_index.pct_change()) over overlapping dates. The benchmark window lies inside validation, so it
  is reported only if validation runs.

## Gates
- Development (per candidate): base net excess Sharpe >= 0.5 AND greater than its control's base net
  excess Sharpe.
- Validation (per surviving candidate): base net Sharpe >= 0.75, stress Sharpe > 0, one-sided
  p < 0.05/2 = 0.025, and Sharpe above the 0.70 benchmark.
- No parameter in this document changes after any result is seen.
