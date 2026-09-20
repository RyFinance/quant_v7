# Overlay control — do these overlays work on a fund you can just buy?

**Purpose.** Parallel agents are testing volatility scaling, market-state gating and
portfolio-construction changes on a 20-stock momentum book (baseline 16.95% / 0.67, 2011–2026).
This experiment is the *control*: it applies the identical overlays to buyable ETFs so that any
claimed Sharpe improvement on the stock book can be judged against the alternative of applying the
same overlay to an ETF. No stock panel is used. `research/momentum_lab/core.py` is not modified.

## Underlyings (6)

Daily adjusted closes already saved in `reports/momentum_verification_20260919/inputs/`, loaded via
`research.momentum_verification.benchmarks.etf_returns`:

`SPMO`, `MTUM`, `SPY`, `RSP`, `QQQ`, `IWM`

## Overlays (5), each applied to each underlying — 30 variants, no others

Exposure is set **only at month starts** (first session of each calendar month, the stock book's
decision cadence), held constant between decisions, long-only, capped at 1.0, remainder in cash.

- **O0 — buy and hold.** Exposure ≡ 1. The reference.
- **O1 — own 200-session trend gate.** At month start *t*: exposure = 1 if the fund's close at
  *t−1* is above the mean of its trailing 200 closes through *t−1*, else 0.
- **O2 — SPY 200-session trend gate.** Same rule but driven by SPY's close and SPY's 200-session
  moving average at *t−1*, applied to whatever the underlying is.
- **O3 — constant-volatility scaling.** At month start *t*: exposure =
  min(1, 0.20 / σ), σ = standard deviation of the fund's trailing 126 daily returns through *t−1*,
  annualised by √252.
- **O4 — O1 × O3.** The own-trend gate multiplied by the constant-vol exposure.

## Accounting (matches the frozen engine)

- Daily close-to-close marking on adjusted closes.
- Costs 5bps per side base / 15bps per side stress, charged on the traded amount |Δexposure| × NAV
  at each monthly decision, plus initial entry and a final liquidation charge, as the frozen engine
  does.
- Idle cash earns the **prior observable** 13-week bill rate (IRX) over elapsed calendar days /
  365.25 — the identical accrual `research.return_search.run.cash_rates` builds.
- Excess Sharpe over that same bill rate; statistics from `research.momentum_lab.core.stats`
  (imported, not reimplemented).
- Windows: `2011..2018`, `2019..2026`, `2011..2026`. One NAV path per (underlying, overlay), sliced
  by window, exactly as `Lab.run` does.
- **Effective start.** For each underlying, all five overlays start on the same date: the first
  session on or after 2011-01-01 at which the fund's own 200-session MA, its own 126-session vol and
  SPY's 200-session MA are all defined. This keeps O0 and O1–O4 on an identical date range so the
  deltas are clean. SPMO (inception 2015-10-12) and MTUM (2013-04-18) therefore have short
  `2011..2018` windows; the effective start is reported for every underlying.

## Reported per cell

CAGR, excess Sharpe, annualised volatility, maximum drawdown, average exposure, annual turnover —
for all three windows, at base and stress costs.

**Headline:** ΔSharpe of each overlay versus O0 on the same underlying and window.

## Additional checks (not new variants — diagnostics on the 30 above)

1. **Causality test.** Perturb every price after a cut date by a large multiplicative shock,
   recompute the exposure path, assert it is unchanged on all dates ≤ the cut. Run for all
   underlyings × O1–O4 at several cut dates. Report pass/fail.
2. **One-session implementation lag.** Re-run O1–O4 with the exposure applied one session later
   than the month start, to show the result is not an artefact of trading at the signal close.
   Reported as a robustness column, not as a separate registered variant.
3. **Dilution control.** For every (underlying, overlay, window, cost) cell, the return and Sharpe
   of a static blend of the same underlying with T-bills held at the overlay's *average exposure*
   for that window, monthly-rebalanced under the same cost model. An overlay that does not beat its
   own dilution control has done nothing.
4. **Did the monthly gate sell the bottom?** Exposure path and realised drag versus buy-and-hold
   through the 2020 and 2025 drawdowns, per underlying, for O1 and O2.

## Success criterion

There is none to "beat" — this is a control. The deliverable is the honest size of each overlay's
effect on a buyable fund, per window, and whether it survives in **both** halves. An overlay that
helps 2011–2018 and hurts 2019–2026 is reported as a null.
