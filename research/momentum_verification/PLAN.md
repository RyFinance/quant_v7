# Momentum verification — 2026-09-19

Keep the selected stock rule unchanged: 12–1 momentum, monthly first-session close, next-open execution, up to 20 names at 5% each, top-200 trailing 63-session dollar volume above $20m, no leverage, base 5bps/side and stress 15bps/side. Do not optimize weights, lookbacks, thresholds or universes after observing these checks.

Evidence work:
1. Reconstruct historical S&P membership with all reentry intervals, using current constituents plus the dated changes ledger, and cross-check material entries against primary index announcements. This is a documented reconstruction, not a certified constituent feed. Never label a current-survivor-only membership filter as survivorship-free.
2. Obtain prices for removed members where available. Record every absent/delisted security. A full point-in-time result is blocked if the ranked investable universe or held returns cannot be established; no silent dropping, forward-filled executions or invented delisting payouts.
3. Measure the effect of excluding stocks before historical index admission on the original universe. Treat this as a bias diagnostic, not the corrected full-index strategy. Keep liquidity ranking as specified and report coverage.
4. Compare the original candidate with actual momentum ETF histories (SPMO and MTUM), and with market and size/value/profitability/investment/momentum factor regressions using HAC errors. Use factor data only for attribution, never as model inputs or weights.
5. Independently recompute the complete trade ledger with per-asset contributions, turnover, cash, integer-share checks for a $100,000 paper account, and realistic minimum commissions. Charge all costs and report daily marked NAV. Reconcile with the frozen engine on matching fractional-share assumptions.
6. Publish a forward-paper specification and an append-only research signal record for the next permitted monthly decision, without broker orders. Historical checks cannot establish future profitability.

Windows: original selection 2019–2025-06-30, original later evaluation 2025-07-01–2026-09-17; earlier 2008–2018 diagnostic where coverage permits. All newly observed outcomes are robustness diagnostics on already viewed history, not fresh model-selection holdouts.
