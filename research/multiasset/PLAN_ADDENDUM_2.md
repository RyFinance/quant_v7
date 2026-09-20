# Addendum 2 to the multi-asset protocol: round-3 candidates (breadth)

Written 2026-09-18, after the round-2 development results and **before any round-3 sleeve was
computed**. `PLAN.md` and Addendum 1 still bind: the windows, the hold-out lock, the inclusion
rule (development Sharpe ≥ 0.30 over at least 3 years) and the equal-risk combination.

## Why this round

After 14 development trials, the book is at a Sharpe of 0.67. Its sleeves are monthly macro premia,
each making a handful of independent bets a year. A Sharpe of 2 needs **breadth**: many small,
independent bets a day. The best-documented high-breadth effect I can test with official data is
the split of stock returns into overnight (close to open) and intraday (open to close). That split
is persistent, and the two halves pull against each other (Lou, Polk and Skouras 2019, "A tug of
war"; Akbas, Boehmer, Jiang and Koch 2022).

## Data

yfinance official daily bars (auto_adjust=True: split and dividend adjusted, so a dividend lands
in the overnight return on its ex-date) for the 503 current S&P 500 constituents, 2003 to date,
downloaded once so the adjustment is consistent. **The universe is survivorship-biased**: today's
members, back-filled. For long-short portfolios the bias is smaller than for long-only ones, but it
is not zero, and it is stated with every result.

## Candidates (fixed now)

In all three, each month-end the stocks are ranked on a past-month score, the long leg is the top
decile at equal weight and the short leg is the bottom decile at equal weight (1 long plus 1 short
gross), and the positions are held over the stated half of every session in the following month.
A stock needs 252 sessions of history to be ranked.

15. **`overnight_persistence`.** Score: the cumulative overnight return over the past 21 sessions.
    Held **overnight only**: bought at the close with market-on-close orders, sold at the next
    open with market-on-open orders.
16. **`intraday_persistence`.** Score: the cumulative intraday return over the past 21 sessions.
    Held **intraday only**, open to close.
17. **`overnight_intraday_reversal`.** Score: the same overnight score as #15. Held **intraday
    only**, in the opposite direction: long the bottom decile, short the top decile.

## Costs

Every entry and every exit is an auction trade charged **2 bps one-way**. A position therefore
pays 4 bps per session per unit of gross, about 20% a year on the 2× gross book. The sleeves have
to beat that. Short positions held overnight also pay 1% a year borrow. Results at 1 bp and 3 bps
are reported alongside for context; they never decide inclusion.

## Rule carried over

Round-3 sleeves enter the book under the same inclusion rule. If more than one passes, all of them
enter as separate sleeves in the equal-risk combination.
