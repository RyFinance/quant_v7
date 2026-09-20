# Rebalancing (A1): validation unlock

Development run (2003-02-03 -> 2014-12-31, `reports/rebalancing/dev_results.json`) completed under
`research/rebalancing/PLAN.md` with no change to rules, costs or gates.

Development net Sharpe (base 2 bp/side/leg): R1_calendar 0.47 (fails the 0.5 gate), R2_threshold 0.74
(passes), R3_combined 0.82 (passes). Selected for validation: R2_threshold, R3_combined.

Validation (2015-01-01 -> 2026-09-18) runs once, for these two only, with the PLAN's gates:
net Sharpe >= 0.75, stress mean > 0, one-sided block-bootstrap p < 0.05/3, Sharpe > 0.70; PEAD overlay
and correlation reported as fixed in the PLAN. Noted before unlocking: development returns are
dominated by 2008, and the descriptive one-day-lag variants are near zero (R3 0.02), so the result
depends on setting the position at the same close the signal is measured.
