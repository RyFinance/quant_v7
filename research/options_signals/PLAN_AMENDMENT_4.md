# Amendment 4: drop name-days where option prices imply a different underlying

Written 2026-09-19, before the registered development run. No signal–return statistic, portfolio
return, Sharpe ratio or ranking of names by later performance had been computed on any window.
Nothing here changes a candidate, threshold, window, universe, quintile rule, holding period or cost.

## Defect class

Data QA (`reports/options_signals/QA.md`) found that the option root **DD** was the old E. I. du Pont
until 2017. The yfinance "DD" price history for those years belongs to a different company
(Dow Chemical / DowDuPont). That name's option strikes do not line up with its spot for most of
2014–2019, and no registered filter protects H1 (option-to-stock volume) or H3 (skew) from pairing
one company's options with another company's stock. The same failure could come from any ticker
reuse or merger the QA has not yet reached, because 64 names arrive after the QA ran.

## Rule (general; applies to every name and every signal)

1. Each day, for each call/put pair with the same strike and expiry, both traded that day,
   7 ≤ DTE ≤ 60 and |ln(K/S)| ≤ 0.10, compute the implied spot:
   S_impl = C − P + K·e^(−rT) + PV(dividends).
   All pairs count, before H2's own parity filter.
2. If the day has at least 3 such pairs and |median(S_impl) / raw close − 1| > 0.05, the name-day is
   flagged. H1, H2 and H3's daily values for that name are set missing before the 5-day aggregation,
   so the name simply lacks a signal those days.
3. Days with fewer than 3 pairs are not checked.

QA measured clean names at 8–22 bp between parity-implied spot and the raw close on the same day, so
a 5% threshold only catches a wrong underlying, never ordinary noise. Dropping DD outright would have
changed the registered universe; this rule leaves the universe alone and removes only the contaminated
name-days.
