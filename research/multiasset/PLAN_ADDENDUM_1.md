# Addendum 1 to the multi-asset protocol: round-2 candidates

Written 2026-09-18, after the round-1 development results and **before any round-2 sleeve was
computed**. `PLAN.md` still binds in full: the same windows, the hold-out lock, the costs, the
inclusion rule (development Sharpe ≥ 0.30 with at least 3 years of history) and the equal-risk
combination.

## What round 1 showed (development window only)

| Sleeve | Development Sharpe (net) |
|---|---:|
| VIX futures basis | 0.98 |
| G10 FX carry | 0.45 |
| Time-series momentum | 0.44 |
| Global bond carry | 0.31 |
| Dollar carry | 0.17 |
| Cross-sectional momentum | −0.15 |
| Intraday momentum | −2.56 (1.6 years only) |

Pairwise correlations sit at 0.0–0.2, so diversification works. The individual sleeves are too weak
to reach a Sharpe of 2, so this round adds more independent return streams from the same
literature. Nothing from round 1 is re-tuned.

## Round-2 candidates (literature parameters, fixed now)

8. **`tsmom_broad`: time-series momentum on the Moskowitz, Ooi and Pedersen universe.** The
   round-1 rule unchanged, applied to the ETFs plus the 9 G10 currencies (spot plus carry) and the
   12 constructed 10-year government bonds. Currencies and bonds cost 1 bp one-way.
9. **`tsmom_broad_multi`.** The same universe with the Hurst, Ooi and Pedersen (2017) signal: the
   average of the signs of the 1-, 3- and 12-month excess returns.
10. **`fx_momentum`.** Menkhoff, Sarno, Schmeling and Schrimpf (2012). Monthly, rank the ten
    currencies (USD included, at zero) by their past 1-month excess return; long the top three,
    short the bottom three.
11. **`fx_value`.** Asness, Moskowitz and Pedersen (2013). Value is the negative 5-year change in
    the log real exchange rate against USD, using CPI lagged two months. Monthly, long the three
    cheapest, short the three dearest, USD included at zero. The value signal before 2014 uses
    yfinance spot, because vault FX starts in 2009; returns always come from vault FX.
12. **`bond_momentum`.** Asness, Moskowitz and Pedersen (2013). Monthly, rank the 12 constructed
    bonds by their 12-month excess return skipping the last month; long the top three, short the
    bottom three, at equal volatility.
13. **`bond_value`.** Asness, Moskowitz and Pedersen (2013). Value is the 5-year change in the
    10-year yield. Monthly, long the three largest rises, short the three largest falls, at equal
    volatility.
14. **`turn_of_month`.** McConnell and Xu (2008). Hold SPY from the close of the second-to-last
    session of each month to the close of the third session of the next, and stay flat otherwise.
    The calendar is known in advance, so no signal lag applies.

## One more rule, fixed now

Rounds 1 and 2 hold three time-series momentum variants (`tsmom`, `tsmom_broad` and
`tsmom_broad_multi`). **Only the one with the highest development Sharpe can enter the book**,
because they are near-duplicates. The other two are recorded as trials.
