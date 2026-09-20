# ETF hybrids E1–E5 on sector and country ETFs: pre-registration

Written 2026-09-19, before any strategy return, portfolio return or signal–return relation was
computed. Inspected before writing:
- the pull log (first and last bars, row counts);
- bar integrity: missing sessions, non-positive opens, stale bars (open = close and high = low),
  zero-volume bars, adjustment factors, and one-day moves over 20% as a bad-print check;
- median daily dollar volume by year.

No return was averaged across ETFs, across months or by signal.

**What this test is.** New signals on already-seen windows (disclosure below). The universe is
US-listed sector and country ETFs. Funds do not vanish the way failed stocks do, so the current-member
survivorship bias that sank `reports/fundamentals/REPORT.md` is largely absent here.

## Disclosure: overlap with earlier work

- `research/multiasset/` (registered 2026-09-18; `reports/multiasset/REPORT.md`) used 37 ETFs. Its
  equity class was SPY, QQQ, IWM, EFA, EEM, EWJ, EWG, EWU, EWC, EWA, EWZ, FXI, EWY and EWT.
  - **11 of the 31 funds here overlap:** SPY, EFA, EEM, EWJ, EWG, EWU, EWC, EWA, EWZ, EWY, EWT.
  - **Never used in any earlier study of this project** (grep of `research/`, `reports/`): the nine
    SPDR sectors, XLRE, XLC, and EWH, EWS, EWL, EWP, EWQ, EWI, EWD, EWN, EWW.
- The multiasset signals closest to these:
  - `tsmom`: sign of the 12-month excess return, volatility-scaled, long/short, all 37 ETFs.
    Development (2003–2017) Sharpe 0.44; hold-out (2018–2026) 0.05. `tsmom_broad`: hold-out 0.21.
  - `xs_momentum`: 12-1 month return, long the top third and short the bottom third within each
    class, including the 14-ETF equity class. Development −0.15; hold-out 0.13 (all classes combined).
- **E1's 12-1 ranking and E2's 12-month absolute filter are close relatives of those sleeves.** They
  run on a partly overlapping universe, over years that cover both windows below. The validation
  window is therefore not unseen data for momentum on these funds. The author also broadly knows
  how US sectors and international markets fared in 2015–2026 (US technology led; EM and Europe
  lagged). The defence is fixed literature parameters, one registered run per window, and gates set
  now.
- Other studies used SPY (many) and the 2003–2014 development years (rebalancing, fundamentals), but
  none ranked these funds.

## Universe (fixed)

31 US-listed ETFs in two cross-sections, with inception dates from the yfinance pull.
- **Sector (SPDR Select Sector), 11 funds:**
  - XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY (1998-12-22);
  - XLRE (2015-10-08);
  - XLC (2018-06-19).
- **Country, 20 funds:**
  - iShares MSCI EWA, EWC, EWG, EWH, EWJ, EWU, EWS, EWL, EWP, EWQ, EWI, EWD, EWN, EWW (1996-03-18);
  - EWY (2000-05-12), EWT (2000-06-23), EWZ (2000-07-14);
  - EFA (2001-08-27), EEM (2003-04-14);
  - SPY (1993-01-29), as the US "country".

Point-in-time eligibility:
- An ETF is eligible at signal date ME(m), the last session of month m, if it has a close at ME(m−13),
  the last session of month m−13. That is 13 complete months of history.
- First eligible signal dates:
  - the nine sectors: 2000-01-31;
  - the 1996 iShares funds: 1997-04-30;
  - EWY: 2001-06-29; EWT: 2001-07-31; EWZ: 2001-08-31;
  - EFA: 2002-09-30; EEM: 2004-05-28;
  - XLRE: 2016-11-30; XLC: 2019-07-31.
- Eligible counts:
  - Development: sector 9; country 19, then 20 from the June 2004 holding.
  - Validation: sector 9, then 10 from December 2016 and 11 from August 2019; country 20.

Delisted funds and exclusions:
- **Delisted funds.** None of the 31 has been delisted; all trade on 2026-09-18.
  - yfinance was asked for the two best-known delisted single-country ETFs, ERUS (iShares MSCI Russia)
    and RSX (VanEck Russia), both halted in 2022. It returns nothing (HTTP 404 "Quote not found").
  - They would be outside this family rule anyway: launched in 2010 and 2007, and not in the list.
- **Left out by the fixed list, still trading:** EWO, EWK, EWM (1996) and EZA (2003). They are small and
  thin. Leaving them out is a mild selection on today's liquidity, not a survivorship problem.

## Data

- Source: yfinance `Ticker.history(auto_adjust=False, actions=True)`, first bar to 2026-09-18.
  - Code: `research/etf_hybrids/pull.py`.
  - Files: `data/etf_hybrids/{T}.parquet`; `manifest.json` sha256 e5b50591…6c45a13, with
    per-file hashes inside.
  - Total-return prices: `adj_close`, and `adj_open` = open × adj_close / close.
  - Quoted prices (split-adjusted, not dividend-adjusted): `close`, used only for E3.
- Calendar: SPY sessions. Every fund has a bar for every session after its first bar; there are no
  missing sessions and no non-positive opens.
- Stale bars on dev rebalance days: EWP 2003-01-02, EWD 2003-03-03, EWN 2003-04-01. No zero-volume
  bar falls on any rebalance day from 2002-06 on. Trades use the recorded open even on a stale bar;
  there is no special handling.
- **Liquidity caveat.** Median daily dollar volume in 2003 was $48k (EWN), $62k (EWD), $105k (EWI),
  $111k (EWL), $142k (EWP) and $179k (EWQ). It passed $300k only in 2005. The 8 bp base cost is
  therefore optimistic for 2003–2005, and the stress case covers only part of that gap.
- Risk-free: `research.options_signals.signals.french_daily()["rf"]`, daily. It ends on 2026-07-31;
  later sessions carry the last value forward.

## Signals (literature parameters, not tuned)

All signals are computed at the close of ME(m) from closes on or before ME(m). They are ranked within
each cross-section separately.
- MOM = adj_close(ME(m−1)) / adj_close(ME(m−12)) − 1. This is the 12-1 return: months m−11 … m−1,
  skipping the latest month (Jegadeesh–Titman; Barroso–Santa-Clara).
- R12 = adj_close(ME(m)) / adj_close(ME(m−12)) − 1, the 12-month return (Antonacci).
- RF12 = compounded daily rf over the sessions in (ME(m−12), ME(m)].

Candidates:
- **E1 volatility-managed momentum** (Barroso & Santa-Clara 2015; Moreira & Muir 2017).
  - Unscaled book U: the top tercile by MOM in each cross-section.
  - σ̂ = sqrt(252 × mean of the squared daily gross excess returns of U over the 126 sessions ending at
    ME(m)). U is marked daily from the first month with both halves eligible (the 2000-02-01
    open), so σ̂ is ex ante.
  - Scale s = min(1, 0.12 / σ̂). The 12% target is from the paper. The cap of 1 means no leverage
    (long-only, unlevered account). s is applied to every weight, the rest sits in T-bills, and s
    is fixed until the next rebalance.
- **E2 dual momentum** (Antonacci 2012/2014).
  - Take the top tercile by R12 in each cross-section.
  - A selected ETF with R12 ≤ RF12 (non-positive absolute excess momentum) has its slot held in
    **T-bills**.
  - Why T-bills and not IEF: the accounting is excess over T-bills, so T-bills are the neutral
    fallback. IEF would add a duration bet from years of falling yields. That bet is outside this
    universe and the multiasset book already tested bond sleeves.
- **E3 52-week-high momentum** (George & Hwang 2004).
  - Score = close(ME(m)) / max(close over the 252 sessions ending at ME(m)). It uses the quoted,
    not dividend-adjusted, close, as in the paper's price anchor.
  - Top tercile. The paper uses the top 30% and a 6-month hold; here the holding is monthly, like
    every other candidate.
- **E4 momentum × low volatility.**
  - VOL = standard deviation of daily log total returns over the 252 sessions ending at ME(m).
  - Score = ½ pct-rank(MOM) + ½ pct-rank(−VOL) within the cross-section.
  - Top tercile.
- **E5 seasonality** (Heston & Sadka 2008; Keloharju, Linnainmaa & Nyberg 2016 for country indices).
  - Score = mean total return in the calendar month being held (m+1), over years Y−1 … Y−10, where Y
    is the year of month m+1. These are lags of 12, 24, …, 120 months.
  - Monthly returns use month-end adj_close. At least 5 of the 10 must exist; 5 is the paper's
    shortest multi-year average (years 1–5).
  - With ETF data, sectors qualify from January 2004, and EWY/EWT/EWZ from mid-2005, EFA from
    September 2006 and EEM from May 2008.
  - Before those dates the average uses 5–9 years. The ETF must also be 13-month eligible.
- **Reported reference, not a candidate:** R0 = the unscaled book U (plain 12-1 momentum, top tercile).
  Also SPY buy-and-hold.

## Portfolio and execution (fixed)

**Long-only against an equal-weight benchmark of the same ETFs.** Why:
- The account in `research_protocol_2026-09-18.md` is long-only and unlevered, and its shorting
  permission and ETF borrow costs are unknown.
- Shorting the 2003–2005 country funds (under $200k a day) was barely feasible.
- The paired test against the benchmark measures the selection value that a long-short spread
  would, while staying tradable.

Book construction:
- Each cross-section is half the book: 50% sector, 50% country. Within a half, the top
  n = round(N/3) ETFs by score are held at equal weight (0.5/n each). N is the number of ETFs with a
  valid score. Ties go to the higher score, then alphabetical ticker.
  - 9 → 3, 10 → 3, 11 → 4, 15 → 5, 19 → 6, 20 → 7.
  - If N < 3, that half holds its equal-weight benchmark. This applies only to E5's sector half in
    2003.
  - Why separate halves: momentum is documented within industries (Moskowitz–Grinblatt 1999) and
    within countries (Richards 1997), and Asness–Moskowitz–Pedersen (2013) rank within asset class.
    A pooled ranking would mostly be a US-versus-international (dollar) bet.
- **Benchmark B.** 50% equal weight across the eligible sector ETFs and 50% across the eligible
  country ETFs. Same eligibility, same rebalance dates, same costs.
- **Rebalancing.** The signal is taken at the close of ME(m). The book trades at the open of the next
  session (the first session of month m+1) and is held to the next rebalance open.
- **Daily marking**, NAV relative to the previous close:
  - On a rebalance day: old book close→open, trade at the open (cost), new book open→close.
  - Other days: close→close.
  - Weights drift between rebalances. Cash (1 − Σw) earns the day's rf; on a rebalance day, the cash
    held after the open earns it.
  - Each window starts from cash at its first open, so the entry is charged. The last book is marked
    to the last close with no exit charge.

## Costs (fixed)

- Per side on |Δw| at each rebalance, measured against the drifted weights at the open:
  - **3 bp** for sector ETFs and SPY/EFA/EEM;
  - **8 bp** for single-country ETFs;
  - T-bills are free.
- Stress: ×3, that is 9 bp and 24 bp.
- ETF expense ratios are already inside the fund prices and are not charged again.

## Windows (fixed)

- **Development:** signal dates 2002-12-31 … 2014-11-28. Daily returns run from 2003-01-02 to
  2014-12-31. Every price input is truncated at 2014-12-31 before any signal is computed.
- **Validation:** signal dates 2014-12-31 … 2026-08-31. Daily returns run from 2015-01-02 to
  2026-09-18.
  - Locked in code until `research/etf_hybrids/VALIDATION_UNLOCK.md` is registered with a matching
    sha256 in `research/preregistrations.jsonl` (`validation_unlocked`, copied from
    `research/options_signals/evaluate.py`).
  - Runs once, only for candidates that pass development. If none passes, validation is not run.

## Gates (five candidates: E1–E5; α = 0.05/5 = 0.01)

Returns are daily net excess over T-bills, Sharpe = mean/sd × √252, bootstrap blocks of 63 sessions,
5,000 draws, seed 20260918.
- **Development pass:** base net Sharpe ≥ 0.50 **and** above the benchmark B's base net Sharpe
  (point estimates, same days).
- **Validation pass (all required):**
  - base net Sharpe ≥ 0.75;
  - stress annualised mean excess > 0;
  - one-sided block-bootstrap p < 0.01 for mean ≤ 0 (`block_bootstrap_p`);
  - Sharpe above the PEAD benchmark's 0.70;
  - a paired test against B, one-sided p < 0.01. H0: Sharpe(candidate) ≤ Sharpe(B), by a paired
    circular block bootstrap of the daily (candidate, B) pairs; p = share of centred resampled
    differences ≥ the observed difference.
  - The paired test uses Sharpe, not mean return, because E1 and E2 hold cash. The same α applies to
    both tests, so the joint claim is controlled across the five.

## Reported, not gated

- 95% interval from `sharpe_ci` (63-session blocks), and `null_kind` at 0.5 and at 0.70.
- Deflated Sharpe with **80 trials**, using two trial-variance inputs:
  - the variance of the five candidates' daily Sharpes in the development run (project convention,
    reused in validation);
  - a fixed cross-trial annual-Sharpe dispersion of 0.5 (the `letf_rebalancing` convention).
- Gross and stress Sharpe; annualised mean and volatility.
- Beta, annualised alpha and HAC t (Newey–West, 20 lags) against SPY daily excess; beta against B.
- Maximum drawdown of the net excess NAV and of the net total NAV.
- Annual turnover (Σ|Δw| per year) and cost drag.
- Net excess return by calendar year, with B's.
- Mean number of holdings, mean risky exposure (E1, E2), and months with any T-bill slot (E2).
- Active return, tracking error and information ratio against B.
- Same statistics for B, R0 and SPY.
- **Validation only:** correlation with the PEAD benchmark, using daily excess
  `reports/pead_audit/wide_5p0_curves.csv` mtm_rf.pct_change() − rf_index.pct_change() on common
  days (2021-08 to 2025-06). The PEAD series does not overlap the development window.

## Expectations stated in advance

- These are long-only equity books, so each should correlate above 0.9 with B. Development
  (2003–2014) includes 2008.
- E1's volatility scaling and E2's cash filter should cut 2008 losses and may clear 0.5 in
  development.
- E4's low-volatility tilt lowers volatility and so raises Sharpe mechanically. In 2015–2026 it would
  lean towards the US.
- E5 is noisy: 5–10 same-month observations per fund.
- The paired test at p < 0.01 is a high bar for rotations whose tracking error against B is modest.
- Prior that any candidate passes every validation gate: about 10%.
