# Amendment 1 to the 2004–2014 PEAD pre-registration

Written 2026-09-17, **before any 2004–2014 PEAD result was computed**. The original
(`PREREGISTRATION_pead_2004_2014.md`) is unchanged and still binding in every respect
except the one below. Both documents' SHA-256 digests are in `research/preregistrations.jsonl`.

## The change: stock price source

**Was:** LSE vault daily candles (split-adjusted) plus LSE dividends for total return.

**Now:** yfinance official daily bars, `auto_adjust=True` (split- and dividend-adjusted),
2003-01-01 through 2015-03-31. This is the same source and adjustment the production
model's training data was built from.

## Why, with the evidence

A data-quality check comparing the two sources over 2016–2025 (40 random names) found
daily-return correlation averaging **0.93** (minimum 0.76), where two correct sources for
the same stock agree to ~0.999. The cause: the vault's `1d` candle is a **UTC calendar-day
bar that includes pre-market and after-hours trading**, not the official 9:30–16:00 ET
session.

Direct evidence, ORCL, which reported after the close on 2025-06-11:

| | Official close | Vault `1d` close |
|---|---:|---:|
| 2025-06-11 | $176.38 | **$189.75** |

The vault's hourly bars show the jump arriving at 20:00 UTC (the 16:00 ET close) and
trading continuing to 23:00 UTC. On every after-close earnings day, the vault's "close"
already contains most of the earnings reaction. For an earnings-drift test that splits each
reaction across two days, distorts every momentum feature relative to training, and makes
the "next open" fill a thin pre-market print.

## What does not change

Hypothesis, universe, feature construction, model (never refit), sizing, execution rule,
costs, borrow, controls, metrics and all three pass criteria are exactly as originally
registered. The LSE vault remains the source for nothing in this test.
