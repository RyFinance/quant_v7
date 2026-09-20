# What the failed tests actually ruled out

Method from Tan, *Two Kinds of Nothing* (arXiv 2608.30490, found through the LSE research feed). A
failed test is only evidence of absence if its confidence interval **excludes** the smallest effect
worth having. Here that is an excess Sharpe of 0.5 (a sleeve worth holding). The project target is 2.0.

These are re-computations of already-recorded out-of-sample returns. No new data, trial or window was
used. Intervals are 95% circular-block bootstrap intervals with 21-day blocks. Crypto uses the iid
approximation because its daily series were not saved. Sharpes match the original reports (book −0.02,
PEAD 0.52). Full table: `null_audit.csv`; code: `research/null_audit.py`,
`research/common/inference.py`.

## Findings

1. **The Sharpe ≥ 2 target is ruled out for every tested family with at least 4 years of
   out-of-sample data:** multi-asset carry, trend, VIX basis, overnight reversal, PEAD, ETF
   convergence, FX session rules and crypto trend. No 95% interval reaches 2.0. Only the 1.5-year
   `higher_sharpe` evaluations are too short to rule out anything.
2. **Genuinely ruled out (bounded nulls, interval below 0.5):**
   - overnight/intraday reversal after 2018 (−0.59, interval −1.23 to 0.05);
   - both FX session rules;
   - LQD/IEF, SPY/QQQ and the fixed ETF-convergence blend.
   These should not be revisited.
3. **Not ruled out (vacuous at 0.5):**
   - FX carry 0.25 [−0.20, 0.73];
   - bond carry 0.13 [−0.47, 0.74];
   - VIX basis 0.29 [−0.35, 0.96];
   - broad trend 0.21 [−0.59, 1.06];
   - crypto trend 0.40 [−0.51, 1.30];
   - the multi-asset book −0.02 [−0.70, 0.70].

   "Failed" here means "not shown", not "shown absent". A modest premium of about 0.3–0.5 in these
   families is still consistent with the data. That matches their long-run literature values, and
   it is too small for the target either way.
4. **PEAD 2004–2014:** the Sharpe interval [0.06, 1.08] excludes zero, but the registered test was
   alpha against the market (t 1.12), which failed. The positive Sharpe is mostly market exposure,
   and the all-events control earns 0.36 [−0.10, 0.88].

## What this means for the search

- Standard premia can plausibly supply about 0.3–0.5 each and are nearly uncorrelated (development
  correlations near 0). Five such sleeves would combine to roughly 0.7–1.1, not 2. A higher Sharpe
  needs either a genuinely new information set (the registered options experiments) or a
  higher-frequency premium (short-dated put writing), which is why those are next.
- Future reports should state their interval and whether a null is bounded or vacuous, alongside the
  deflated Sharpe against the project-wide trial ledger (Gençay, arXiv 2608.27734).
