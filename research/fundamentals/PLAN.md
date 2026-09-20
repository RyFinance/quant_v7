# Fundamentals signals F1/F2/F3 (edge-graveyard candidates C4 + C5): pre-registration

Written 2026-09-19, before any strategy return, portfolio return or signal-return relation was
computed. Inspected before writing: data layouts, filing coverage, acceptance-date lags, split basis
of share counts, and the signal panel's *counts and distributions only*
(`reports/fundamentals/signals.parquet`, built by `research/fundamentals/build_signals.py`; no prices
were read by it).

**Sources.** Pontiff & Woodgate (2008, JF) net share issuance; Daniel & Titman (2006). Alwathainani
(2009, BAR) earnings consistency. Chen–Zimmermann OSAP 2015–2024: `ShareIss1Y` Sharpe 0.82 (0.60
ex-microcap), `EarningsConsistency` 0.84 (0.67 ex-microcap) (`reports/edge_graveyard/`).

**What this test is.** New signals on used windows: every 2003–2026 price window below has already
been viewed by other signals in this project (PEAD 2004–2014, options, rebalancing, LETF, etc.).
Neither F1 nor F2 has been computed against returns in this project before. Universe = current S&P 500
members (496 names with both fundamentals and prices), so survivorship bias is present; a same-universe
equal-weight control is reported.

## Data

- `data/lse/financial_reports/{T}.parquet` (income statements, FY and Q1–Q4 rows): `eps` (basic),
  `weightedAverageShsOut` (fallback `weightedAverageShsOutDil` when basic <= 0), `date` (fiscal period
  end), `accepted_date`, `period`.
- `data/lse/stock_splits/{T}.parquet` (residual split guard only, see below).
- Prices: `data/multiasset/stocks/{T}.parquet` (yfinance auto-adjusted daily OHLC, 2003+). Trading
  calendar = `data/multiasset/etf/SPY.parquet` dates. Market = SPY (same file).
- RF: `research.options_signals.signals.french_daily()` `rf` (ends 2026-07-31; later days use the last
  value).

## Coverage check (done before registration) and the changes it forced

- Filings per acceptance year: 1,916 rows / 403 names (2003) rising to 2,482 / 496 (2024); no duplicate
  (symbol, period end, period) rows; about 0.1% non-positive share counts (treated as missing).
- **Placeholder acceptance timestamps.** 6% of 2003–2026 rows (3,309) have an acceptance date on or
  before the fiscal period end (times 00:00/04:00/05:00), which is impossible for a real filing (1998–
  2001: ~44% of rows are 04:00 placeholders). **Forced rule:** such rows are treated as accepted at
  period end + 45 days (Q1–Q3) or + 90 days (FY, Q4), the SEC large-filer deadlines rounded up. Rows with
  a lag of 1–10 days are real early filers (e.g. DAL) and kept.
- **Split basis.** Across 603 split events (2000+) with quarterly rows on both sides, 554 show no jump in
  share counts (the vault restates counts and EPS to the current split basis; AAPL FY1986 shares 14.4bn),
  4 show the raw split ratio (JPM 2000, CRH 2001, IRM 2014, RTX 2020), 45 are small stock dividends,
  spin-off adjustments or merger-driven share changes. **Forced rule:** the split file is NOT applied
  as a blanket adjustment (it would double-adjust); a residual guard divides a share ratio by any split
  inside the measurement interval with |log ratio| >= log 1.25 whose ratio it matches
  (|log obs / log split − 1| < 0.25). EPS growth is a ratio of restated values (no adjustment).
- Restated values: the vault serves the current restated value of old rows; a restated number can
  differ from what was known at the acceptance date. Not fixable with this data; stated as a caveat.
- **Basic, not diluted, share counts** for F1: diluted counts move mechanically with the share price
  (treasury-stock method), which would add a price-momentum component.
- Signal coverage (mean names per month-end with a valid signal): F1 368 (2003) → 446 (2014) → 493
  (2026). F2 155–253 per month (median about 215); the sign filter removes most of the rest (at
  2010-06-30: 186 valid, 210 sign-filtered, 91 with < 7 fiscal years, 5 over 600%, 4 with year gaps).
  F3 (needs both) ≈ F2. All months have far more than the 25-name minimum.
- F1 distribution: median −0.1%, 5–95% range −7.3% to +14.0% (log); extremes (|F1| > 0.7, 71 names)
  are mergers, IPOs, recapitalisations (AIG 2011, C 2010) and are kept (quintile ranks only).

## Signals (fixed)

Computed at each signal date t (last trading day of each month) from filings with availability date
<= t, where availability = first trading day strictly after the acceptance date (or the placeholder
fallback date). Code: `research/fundamentals/signals.py`.

- **F1 net share issuance.** Latest quarterly row (Q1–Q4) available at t with period end <= t − 6 months:
  shares S1. Row available at t with period end nearest to (that period end − 12 months), within ±45
  days: S0. F1 = log(S1/S0) after the split guard. Score = −F1 (long net repurchasers, short issuers).
- **F2 earnings consistency.** Last 7 FY rows available at t, consecutive (period-end gaps 300–430 days),
  basic EPS e. Growth g_k = (e_k − e_{k−1}) / (0.5(|e_{k−1}| + |e_{k−2}|)) for the last 5 years; missing if a
  denominator is 0, |g_last| > 6, or g_last and g_prev have opposite signs. F2 = mean of the 5 growths.
  Score = F2.
- **F3 combined.** Mean of the cross-sectional percentile ranks of −F1 and F2 on date t, among names with
  both (and an entry-day open).

## Portfolio (fixed)

- Monthly: signal at the close of the last trading day of month m; trade at the next open; hold to the
  next open after the following signal date. Names without an entry-day open are excluded.
- Long top quintile, short bottom quintile of the score, equal weight, 100% NAV per leg
  (`research.options_signals.evaluate.target_weights`, >= 25 names needed or flat). Exit at the last
  available close if a name has no exit open. Backtest = `research.options_signals.evaluate.backtest`
  (turnover from drifted weights).
- Costs: base 5 bp per side on turnover + 0.5%/yr borrow on the short leg, short proceeds earn RF (no
  drag). Stress: 15 bp per side, 3%/yr borrow, proceeds earn 0 (charge = short notional × RF).
- Returns are per holding period (monthly) long-short excess returns net of costs; Sharpe = mean/sd × √12.

## Windows

- Development: signal dates 2003-01-31 → 2014-11-28 (holdings 2003-02 to 2015-01-02 open; 143 months).
- Validation: signal dates 2014-12-31 → 2026-07-31 (holdings to the 2026-09-01 open). Locked in code
  until `research/fundamentals/VALIDATION_UNLOCK.md` is registered with a matching sha256 in
  `research/preregistrations.jsonl` (guard copied from `research/options_signals/evaluate.py`
  `validation_unlocked`). Runs once, only for candidates that pass the development gate.

## Gates (three trials: F1, F2, F3)

- Development: base net Sharpe >= 0.5 → selected for validation.
- Validation pass: base net Sharpe >= 0.75; stress mean > 0; one-sided circular-block bootstrap
  p < 0.05/3 (`evaluate.block_bootstrap_p`, 6-month blocks, 5,000 draws); and Sharpe above the PEAD
  benchmark's 0.70.

## Reported (not gated)

95% block-bootstrap Sharpe interval (`sharpe_ci`, 6-month blocks) and `null_kind` at 0.5; deflated
Sharpe with 65 project trials (trial variance = variance of the three candidates' monthly Sharpes in the
same run); gross and stress Sharpe; beta and annualised alpha against SPY excess (OLS on holding-period
returns); max drawdown; annual turnover and cost drag; results by year; names per leg; same-universe
controls: EW long-only of all scored names minus RF (Sharpe), and long-leg minus EW, EW minus short-leg
(gross). Validation only: correlation with the PEAD benchmark (daily excess = `reports/pead_audit/
wide_5p0_curves.csv` mtm_rf.pct_change() − rf_index.pct_change(), compounded over each holding period,
2021-08 to 2025-06).

## Expectations stated in advance

- Survivorship: current members that issued heavily and failed are missing, which biases F1's short leg
  towards survivors (hurts F1) while consistent growers staying in the index helps F2's long leg.
- OSAP post-2015 Sharpes are equal-weight all-stock and gross; in S&P 500 names, net, expect 0.1–0.5.
  Development includes the GFC. Prior: neither clears 0.75 in validation.
