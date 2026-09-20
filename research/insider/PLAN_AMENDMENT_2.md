# Insider study, amendment 2: cleaning bad yfinance prints

Amends `research/insider/PLAN.md` ("Missing bars"). Written 2026-09-19, while the yfinance pull was
running and **before any portfolio, event or control return was computed**. The only evidence is a
bar-quality scan of the first 344 pulled tickers (1.02M bars), not conditioned on any signal:
- 189 opens more than 2× away from both the prior close and the same day's close;
- 11 opens more than 1% outside the day's high–low range;
- 36 one-day close spikes, more than 3× away from both neighbouring closes in the same direction;
- 32 of the 344 tickers (9%) have at least one of these.

## Why it matters

The long book rebalances to 1/N at the open whenever the active set changes, which is almost daily.
A bogus open on a rebalance day forces the book to trade at a price that never existed. Whether the
print is too high or too low, the rebalance turns it into a gain. With about 100 positions, one
10× bad open adds roughly 8% of NAV. A one-day close spike does not bias returns, because the next
open undoes it. It does add huge artificial daily returns that distort volatility. PLAN.md only
handles a *missing* open.

## Rules (fixed now, applied to every ticker, identical for candidates and control)

**B2, close spikes (return accounting only).** Evaluated first, on the split-adjusted close. A close is
a bad print if it is more than 3× above both the prior and the next close, or more than 3× below
both. It is then treated as missing for portfolio returns, i.e. carried forward from the prior close.
In development mode the next close is looked up only within the window, so the check at 2015-12-31
cannot see 2016.

**B1, bad opens.** An open is treated as missing if any of these holds:
- (a) it is more than 1% above the high or 1% below the low, when both are positive;
- (b) it is more than 2× away from the prior close **and** more than 2× away from the same day's
  close (after B2);
- (c) it is not positive.

A missing open is handled as PLAN.md already says. A held position's gap is taken at the prior close.
An event whose entry-day open is missing is skipped. It is never entered at the prior close, because
filings usually land after the close and the overnight gap carries the market's reaction.

**Unchanged.** The universe filter ($5 raw close, $2M ADV) and the cost tiers use the bars as
reported, because that is what was known on the day. No other rule changes.

The bounds (2× for opens, 3× for close spikes) were chosen now, from the nature of the errors.
They were not fitted to any result. The full-universe frequencies will be in the report.
