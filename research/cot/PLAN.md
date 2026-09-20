# Commodity positioning (CFTC COT) premiums: pre-registration

Written 2026-09-18, after pulling the COT table (`data/lse/cot/cot.parquet`, sha256 ffea61cb…) and
listing which markets it covers, and before any commodity price was loaded for this experiment.
COT positioning is a new information set for quant_v7. The commodity price windows are not new
(GLD/SLV were in the ETF-convergence screen, commodity trend in the multi-asset book).

## Source

Kang, Rouwenhorst & Tang (2020, *Journal of Finance*), "A Tale of Two Premiums" (read 2026-09-18,
2017 working-paper version). Commodities most heavily **bought by speculators** (non-commercials)
during a week underperform afterwards, and those they sold outperform: a short-term liquidity
premium earned by hedgers. Long-run hedging pressure (hedgers net short) earns the opposite,
insurance premium (Keynes; Basu & Miffre 2013).

## Universe (fixed by coverage, not by returns)

These are the COT markets with reports from 2015-01 to 2026-09 **and** a US-listed ETF tracking the
same futures market that trades throughout 2015–2026:

| COT | ETF | | COT | ETF |
|---|---|---|---|---|
| ZC corn | CORN | | SI silver | SLV |
| ZS soybeans | SOYB | | HG copper | CPER |
| ZW wheat | WEAT | | PL platinum | PPLT |
| SB sugar | CANE | | PA palladium | PALL |
| GC gold | GLD | | RB gasoline | UGA |
| BZ Brent (last day) | BNO | | | |

Excluded:
- WTI (the COT series is a small financial contract before 2026-04) and natural gas (COT from 2022);
- markets without a surviving ETF: coffee, cocoa, cotton, cattle, hogs, soybean oil/meal, oats, rice,
  milk, orange juice, lumber.

ETF prices are yfinance daily OHLC with splits and distributions adjusted.

## Timing

Positions are as of Tuesday (`date`) and released Friday after the close (`release_date`, 3 days
later in every row). A signal is used from the **first trading day after `release_date`**: enter at
that day's open and hold to the open of the next entry day (about one week).

## Signals (three candidates)

With noncommercial net = noncomm_long − noncomm_short, commercial hedging pressure
HP = (comm_short − comm_long) / open_interest:

1. **C1_liquidity**: Q = (net_t − net_{t−1}) / OI_{t−1}, the speculators' net purchase in the report
   week. Long the 3 markets with the lowest Q (most sold by speculators) and short the 3 with the
   highest.
2. **C2_hedging_pressure**: the mean HP over the last 52 reports (needs ≥ 40). Long the 3 highest
   (hedgers most net short) and short the 3 lowest.
3. **C3_two_premiums**: the mean of the cross-sectional percentile ranks of −Q and of the 52-week HP.
   Long the top 3, short the bottom 3.

Each leg is equal-weighted with 100% of NAV per leg (gross 2.0). A week needs at least 8 markets with
the signal, otherwise the book is flat.

## Costs

- Base: per-side cost on traded notional of 2 bps for GLD and SLV; 5 bps for PPLT, PALL and BNO;
  15 bps for CORN, SOYB, WEAT, CANE, CPER and UGA. Borrow is 1%/yr on the short leg. Short proceeds
  earn RF (so the reported spread is an excess return).
- Stress: costs ×3, borrow 5%/yr, and short proceeds earn nothing.
- A real account might use futures instead; ETF costs are the conservative, implementable baseline.

## Windows and gates

- Development: entries from 2015-01-01 to 2019-12-31. Validation: entries from 2020-01-01 to
  2026-09-17, locked until `research/cot/VALIDATION_UNLOCK.md` is registered, and run only for
  development-selected candidates.
- Development gate: net base Sharpe ≥ 0.5 (weekly returns, √52).
- Validation pass: net base Sharpe ≥ 0.75, stressed mean > 0, and a one-sided circular-block
  bootstrap p < 0.05/3 (8-week blocks, 5,000 draws). Also reported: the 95% Sharpe interval and
  whether a null is bounded or vacuous at 0.5 (see `reports/null_audit/`).

## Expectation stated in advance

Eleven markets make a narrow cross-section (legs of 3), the effects are published, and small
commodity ETFs are costly to trade weekly. Prior: net Sharpe 0 to 0.6. This is a candidate
diversifying sleeve, not a route to Sharpe 2.
