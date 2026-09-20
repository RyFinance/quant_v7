# SEC insider purchases (Forms 3/4/5): report

Run 2026-09-18/19. Registered in `research/preregistrations.jsonl`: `PLAN.md`, `PLAN_AMENDMENT_1.md`,
`PLAN_AMENDMENT_2.md`, `VALIDATION_UNLOCK.md`.

## Verdict

**Nothing beats the PEAD benchmark of 0.70.** Two of the four candidates passed the development gate.
Both then failed validation, at net excess Sharpes of 0.49 and 0.51 against a required 0.75. More
telling than the Sharpes: with the market hedged out, every candidate is flat to negative in both
windows, and the CAPM alpha is never distinguishable from zero. What the long book earns is market
beta on small caps in a survivorship-biased universe, not an insider edge.

There is a real but small edge over the same-universe control: about +3%/yr in development and
+2.4 to +3.0%/yr in validation. It is never significant at the registered threshold, and it is
roughly the size of the trading costs (2.3%/yr).

## Data

- **Filings.** All 82 quarterly SEC DERA ZIPs, 2006q1-2026q2, 879 MB, every sha256 verified against
  the download manifest. The user supplied the contact e-mail for SEC's User-Agent; it appears in no
  file, log or report.
  - 170-235k Form 4s a year; 787k open-market purchase trades; 3.35M open-market (P and S) trades.
  - Every filing date parsed. 11 transaction dates out of millions did not, and those trades drop out.
- **Prices.** yfinance official session bars for 5,969 of the 6,600 tickers in the amendment-1
  universe (issuers still filing since 2025-01-01). The other 631 return nothing, i.e. they are gone
  from Yahoo. No rate limiting occurred.
- **Rates and market.** French daily rf and mkt_rf; the calendar matches Yahoo sessions exactly, with
  no gaps in either window.

### Coverage by year

"priced" is the share of purchase filings whose issuer maps to a ticker that has prices; "A2 pass" is
the share of those purchases whose reported price agrees with the market (amendment 1). Event counts
are after A2.

| Year | Form 4 | P trades | P issuers | mapped | priced | A2 pass | filed <=2bd | N1 ev | N2 ev | N3 ev |
|---|---|---|---|---|---|---|---|---|---|---|
| 2006 | 227,994 | 49,974 | 3,928 | 89% | 26% | 89% | 83% | 748 | 380 | 0 |
| 2007 | 234,776 | 69,767 | 4,325 | 90% | 28% | 91% | 82% | 1,418 | 631 | 0 |
| 2008 | 217,751 | 108,057 | 4,627 | 91% | 27% | 89% | 88% | 2,099 | 901 | 0 |
| 2009 | 185,988 | 48,866 | 3,642 | 92% | 30% | 94% | 84% | 1,227 | 544 | 456 |
| 2010 | 194,888 | 34,644 | 3,198 | 91% | 32% | 92% | 84% | 812 | 462 | 495 |
| 2011 | 190,117 | 41,138 | 3,480 | 93% | 38% | 94% | 85% | 1,513 | 760 | 763 |
| 2012 | 192,604 | 35,615 | 3,062 | 93% | 42% | 96% | 84% | 1,118 | 703 | 614 |
| 2013 | 193,175 | 26,303 | 2,835 | 94% | 42% | 94% | 83% | 845 | 601 | 461 |
| 2014 | 193,757 | 30,731 | 2,950 | 95% | 44% | 96% | 85% | 1,232 | 800 | 476 |
| 2015 | 191,908 | 38,019 | 3,107 | 95% | 46% | 94% | 87% | 1,791 | 1,073 | 590 |
| 2016 | 182,192 | 33,005 | 2,857 | 95% | 50% | 96% | 86% | 1,459 | 934 | 468 |
| 2017 | 180,801 | 26,634 | 2,584 | 94% | 53% | 95% | 83% | 1,345 | 878 | 525 |
| 2018 | 180,460 | 43,440 | 2,787 | 95% | 62% | 97% | 87% | 1,798 | 1,030 | 611 |
| 2019 | 175,430 | 37,480 | 2,669 | 94% | 64% | 96% | 88% | 1,826 | 1,049 | 636 |
| 2020 | 180,626 | 29,631 | 2,969 | 96% | 66% | 95% | 90% | 2,943 | 1,444 | 967 |
| 2021 | 194,453 | 24,796 | 2,670 | 96% | 68% | 96% | 86% | 1,782 | 1,003 | 846 |
| 2022 | 182,314 | 32,660 | 2,849 | 96% | 75% | 96% | 88% | 2,620 | 1,677 | 791 |
| 2023 | 181,387 | 25,035 | 2,583 | 96% | 80% | 96% | 89% | 2,563 | 1,409 | 886 |
| 2024 | 177,980 | 20,539 | 2,330 | 95% | 85% | 96% | 89% | 1,856 | 1,137 | 662 |
| 2025 | 169,537 | 21,009 | 2,411 | 94% | 90% | 97% | 87% | 2,343 | 1,484 | 772 |
| 2026 (H1) | 106,685 | 9,614 | 1,757 | 95% | 93% | 96% | 86% | 1,196 | 821 | 384 |

- **Filing lag** for purchases: median 2 days, 86% within 2 business days, 95th percentile 21 days,
  99th 196 days. Entry at the next open after the filing date is therefore close to the trade for
  most events.
- **Ticker matching.** 89-96% of purchase filings map to a ticker, which is 98.7% of purchase value.
- **A2 price check** accepts 94.6% of priced purchases.
- **Bad prints** (amendment 2) fired on 3,807 opens and 657 close spikes out of 18.3M bars, in 516 of
  5,969 tickers.

## Registered candidates and what was run

Signal date = filing date, entry at the next session's open, 63-session hold, equal weight, daily
mark to market, idle cash at T-bills, costs 5/15/40 bps per side by ADV tier, universe filter $5 raw
price and $2M 20-day ADV known at entry, control = 20 random same-date same-filter draws.

| ID | Rule | Development | Validation |
|---|---|---|---|
| N1_cluster | >=2 officers/directors buying within 30 days, >=$50k | ran | stopped at development |
| N2_csuite | CEO/CFO/President purchases >=$25k in a day | ran | stopped at development |
| N3_opportunistic | purchase by a Cohen-Malloy-Pomorski opportunistic insider | ran | ran once |
| N4_composite | equal-weight average of N1-N3 | ran | ran once |

## Development, 2006-01 -> 2015-12 (N3 from 2009)

| Candidate | Net SR | 95% CI | Gross | Stress | Hedged | Control (med.) | vs control | Paired p | Boot p | Beta | Alpha %/yr (t) | Pos. | Gate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| N1_cluster | 0.42 | [-0.09, +0.96] | 0.50 | 0.34 | +0.23 | 0.36 | +3.30%/yr | 0.078 | 0.054 | 1.29 | +1.3 (0.40) | 69 | fail |
| N2_csuite | 0.42 | [-0.11, +0.99] | 0.51 | 0.33 | +0.17 | 0.34 | +3.05%/yr | 0.083 | 0.060 | 1.27 | +1.1 (0.37) | 55 | fail |
| N3_opportunistic | **0.77** | [+0.14, +1.40] | 0.87 | 0.66 | -0.09 | 0.71 | +3.62%/yr | 0.088 | 0.008 | 1.25 | -0.4 (-0.11) | 29 | **pass** |
| N4_composite | **0.51** | [-0.02, +1.06] | 0.60 | 0.42 | +0.13 | 0.44 | +2.96%/yr | 0.044 | 0.028 | 1.08 | +3.4 (1.18) | 48 | **pass** |

Excess CAGR 8.0-17.4%/yr, max drawdown -36% to -59%, turnover about 12x/yr, cost drag 2.2-2.5%/yr.
Events entered: N1 5,717 of 12,803, N2 3,593 of 6,855, N3 1,245 of 3,855; the rest fail the $5/$2M
filter.

## Validation, 2016-01 -> 2026-06 (run once)

| Candidate | Net SR | Needed | 95% CI | Gross | Stress | Hedged | Control (med.) | vs control | Paired p | Boot p | Beta | Alpha %/yr (t) | Pos. | Pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| N3_opportunistic | 0.49 | >=0.75 | [-0.14, +1.17] | 0.58 | 0.40 | -0.30 | 0.42 | +2.42%/yr | 0.161 | 0.052 | 1.08 | -2.8 (-0.65) | 44 | **no** |
| N4_composite | 0.51 | >=0.75 | [-0.13, +1.20] | 0.60 | 0.42 | -0.27 | 0.45 | +2.96%/yr | 0.078 | 0.049 | 1.13 | -2.7 (-0.64) | 89 | **no** |

Both miss on three of the four conditions: the Sharpe (0.49 and 0.51 against 0.75, and below the 0.70
benchmark), the bootstrap p (0.05 against 0.0125) and the paired control test (0.16 and 0.08 against
0.0125). Stressed means stay positive, which is the only condition met.

Yearly net excess returns, N4: +29.7, +15.8, -12.1, +27.9, +14.6, +21.3, -18.7, +18.6, +5.3, +5.6,
+8.2% for 2016...2026H1. Hedged: +9.1, -8.0, -6.4, -0.0, -14.4, -2.1, +4.6, -4.8, -13.8, -7.4, +0.2%.

## What this means, plainly

- **The long book is a small-cap beta bet.** Betas are 1.08-1.29 and the market-hedged version of
  every candidate is around zero or negative (validation: -0.27 and -0.30). Take the market away and
  the strategy has nothing left. The one apparently strong development number, N3's 0.77, came from
  a window starting in 2009, i.e. after the crash, and it fell to 0.49 out of sample.
- **There is a small edge over random stocks, and costs eat it.** Insider-purchase names beat
  same-date, same-filter random draws by about 2.4-3.6%/yr after costs, but the trading itself costs
  2.3%/yr, and the difference is never significant at the registered threshold. Paired p-values of
  0.04-0.16 are the honest summary: suggestive, not established.
- **Cohen-Malloy-Pomorski's distinction did survive in a weak form.** N3 (opportunistic insiders) beat
  the broader N1 and N2 rules in development on every measure and had the best control-relative edge
  in both windows. That matches the literature's direction. It just is not worth 0.70 Sharpe after
  costs in a modern, liquid, post-publication sample.
- **The 63-day hold was not the binding problem.** Turnover at 12x/yr costs about 2.3%/yr against
  gross-to-net Sharpe gaps of roughly 0.09. A 21-day hold would have cost three times as much.

## Caveats

- **Survivorship, the big one.** Prices exist only for currently listed tickers, so the study sees
  26-46% of development-window purchases and 50-93% of validation-window ones. Firms that were
  delisted, acquired or went bankrupt are missing, and insider buying is common in distressed firms.
  This most likely flatters the results. The same-universe control carries the same bias, which is
  why the control-relative numbers are the ones to trust, and they are the weakest ones here.
- **Ticker matching.** 4-11% of purchase filings a year never map to a usable ticker. Issuers are
  linked to prices through their CIK's latest symbol, and a recycled symbol goes to whoever filed
  most recently; the A2 price check then rejects links whose reported trade price disagrees with the
  market.
- **The control is more diversified than the signal.** A repeat event extends one signal position but
  opens a fresh control position, so control books hold about twice as many names (validation: 66 vs
  44 for N3). That lowers control volatility and makes "beat the control's Sharpe" harder than it
  looks. The mean-difference paired test, which is the registered significance test, is unaffected.
- **N3 has a short development window.** The classification needs three prior years of trades, so it
  starts in 2009 and never sees 2008.
- **Costs are assumptions**, not broker quotes: 5/15/40 bps per side by liquidity tier, doubled for
  the stress case, plus 0.25%/yr borrow and 1 bp per side on the market hedge.
- **Yahoo bars are not audited.** Amendment 2 removes the visible bad prints (0.02% of bars); subtler
  errors remain.
- **The windows are not pristine.** The project has examined 2003-2026 price history many times over.
  These results are evidence about the insider signal, not about the market path.

## Files

- Registrations: `research/insider/PLAN.md`, `PLAN_AMENDMENT_1.md`, `PLAN_AMENDMENT_2.md`,
  `VALIDATION_UNLOCK.md`.
- Code: `research/insider/{sec_data,signals,prices,evaluate}.py`; tests: `tests/test_insider.py` (32,
  all passing).
- Results: `reports/insider/dev/results.json`, `reports/insider/validation/results.json`, plus daily
  return series per candidate.
- Coverage: `data/sec_insider/coverage.json`, `coverage_pre_prices.json`.
