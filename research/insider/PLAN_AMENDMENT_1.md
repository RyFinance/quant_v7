# Insider study, amendment 1: price-pull scope and purchase price check

Amends `research/insider/PLAN.md` (sha256 a8183700…). Written 2026-09-19, after the SEC ZIPs were
parsed and the no-price coverage step was run, and **before any price was pulled for this study
and before any return was computed**. The only evidence used is `data/sec_insider/coverage_pre_prices.json`
(filing counts, filing lags, ticker mapping, event counts) plus a count of implausible trade values.
No rule in PLAN.md other than the two below changes.

## What coverage showed

- **Parsing.** All 82 quarterly ZIPs (2006q1–2026q2) parsed. There are about 170–235k Form 4s a year
  and 787k open-market purchase (P) trades. Every filing date parsed; 11 transaction dates did not.
- **Filing lag** for purchases: median 2 days, 86% within 2 business days, 95th percentile 21 days.
- **Ticker mapping.** 89–96% of purchase filings a year map to a ticker (98.7% of purchase value). There
  are 17,224 mapped tickers in all. Only 6,600 belong to issuers that filed any Form 3/4/5 on or after
  2025-01-01. The rest are overwhelmingly delisted, acquired or deregistered.
- **Survivorship, quantified.** The share of mapped purchase trades whose issuer still files in
  2025–2026 is 29% (2006), 34–38% (2007–2010), 47–56% (2011–2015), 55–81% (2016–2021) and 88–100%
  (2022–2026). The development window therefore sees only a minority of the insider buying that
  actually happened.
- **Implausible values.** 0.26% of purchase trades have a value above $100M, up to $7×10¹⁵ (for
  example, a "price" of $29 million per share). They come from unit errors, totals typed as prices
  and SPAC/PIPE unit deals. By count they change 0.25% of N1 and 0.45% of N2 events. The value
  thresholds are exposed to them, and PLAN.md has no rule for them.
- **Ticker mismatches.** A symbol that changed hands can link an issuer's filings to another
  security's price history. PLAN.md's recycled-ticker rule catches this only when the new holder
  also files Form 4s.

## A1: price-pull scope

yfinance bars are pulled only for tickers whose issuer filed a Form 3/4/5 on or after 2025-01-01
(`last_filing >= 2025-01-01` in `cik_ticker.parquet`, 6,600 tickers). Three reasons:
- yfinance serves only listed symbols, so the other ~10.6k tickers would yield almost nothing.
- Requesting them would send about 20k useless requests from an IP shared with the live paper bot.
- A dead symbol that does return data most likely belongs to a different security now.

The universe was already "currently listed" under PLAN.md, so A1 adds no survivorship beyond what
PLAN.md stated. The control draws come from the same universe.

## A2: purchase price-consistency check

A purchase (P) trade counts toward N1, N2 and N3 only if two conditions hold. Counting covers the
N1 and N2 value sums, N1's distinct-insider count, and the purchase that triggers N3.
1. Its mapped ticker has a raw close (PLAN "Prices") on the last session on or before the trade
   date, and that session is at most 10 calendar days before the trade date.
2. The reported price per share is within [0.5, 2.0] × that raw close.

Everything the check uses is known before the filing date: trade date ≤ filing date ≤ signal date.
The bounds were fixed here, before any price was pulled. They are wide enough for intraday moves
and for weighted-average fills in volatile small caps. They reject:
- unit and total-value errors;
- purchases of a different share class or security, such as preferred stock or units;
- issuer-to-ticker links that point at another company's prices.

Sales (S), used only for the N3 routine/opportunistic history, are not checked. The coverage report
will add the share of purchases that pass A2, by year.

## Unchanged

Candidates, thresholds, the holding period, the universe filter ($5, $2M ADV), costs, the control,
windows, gates, and the Bonferroni divisor of 4 are all unchanged. The benchmark is still 0.70.
