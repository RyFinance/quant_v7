# Pre-registration — crash-protected / volatility-managed momentum

Date: 2026-09-19
Harness: `research/momentum_lab/core.py` (unmodified). Universe `pit`, slots 20, equal weight,
monthly rebalance, `min_score=0.0`, frozen execution engine at base (5bps) and stress (15bps) costs.
Windows: 2011..2018, 2019..2026, 2011..2026. Bar: SPMO Sharpe in **both** halves (0.70 / 0.89).

## Motivation

Barroso & Santa-Clara (2015), Daniel & Moskowitz (2016), Moreira & Muir (2017): momentum's problem
is time-varying risk, not signal quality. Our book is long-only and unlevered, so exposure can only
be scaled **down** (cap 1.0, floor 0.0) and unused weight sits in cash at the 13-week bill. The
expected improvement is therefore smaller than the long-short papers report, and any Sharpe gain has
to be checked against simple dilution.

## Signal (frozen, identical for every variant)

`score = close.shift(21) / close.shift(252) - 1` — the frozen 12-1 rule. **No variant changes the
signal.** The only thing that varies is the `exposure` series passed to `lab.run`.

## Baseline and warm-up

- **B** — the frozen 12-1 book with no exposure overlay, `start='2011-01-01'`. This is the
  comparator and the source of the strategy's own return history.
- **Warm-up run (diagnostic only, never a headline):** the *same* targets executed from
  `start='2009-01-01'`, used **only** to seed the trailing-statistic windows so that exposure is
  defined at the first 2011 decision dates. Pre-2011 point-in-time membership is thin and the
  README says such windows are biased upward; only the *volatility* of that stretch is consumed,
  never its return, and no pre-2011 number is reported as a result.

## Causality convention (applies to every variant)

Exposure applied at decision date *t* is computed **only from data observable strictly before *t***,
i.e. through session *t−1*. Concretely: the baseline daily return series is shifted one session
before any rolling statistic is taken, and SPY's close and moving average are read at *t−1*. The
harness fills the resulting target at the *next* session's open, so this is strictly conservative.
Every exposure is clipped to [0, 1]; where undefined it is 1.0.

**Registered test:** a perturbation test that multiplies all baseline daily returns (and separately
all SPY closes) after a cut date by 3, recomputes all five exposure series, and asserts that the
exposure values at every decision date on or before the cut date are bit-identical. The report will
state whether it passed.

## Variants to run — exactly these five, no others

| id | exposure at decision date *t* |
|---|---|
| **V1** | `min(1, 0.20 / sigma_t)`, `sigma_t` = annualised std (×√252) of B's daily returns over the 126 sessions ending at *t−1* |
| **V2** | as V1 with a 0.15 target |
| **V3** | `1` if SPY close at *t−1* > its 200-session simple moving average at *t−1*, else `0` |
| **V4** | `V1_t × V3_t` |
| **V5** | `min(1, raw_t / n_t)` where `raw_t = 1 / var(B's daily returns over the 21 sessions ending t−1)` and `n_t` = expanding mean of `raw_s` over all monthly decision dates `s ≤ t` starting at the warm-up date (min 24 observations). Expanding, never full-sample. |

## Reported for every variant, including failures

All three windows at base **and** stress costs; CAGR, Sharpe, vol, max drawdown, turnover; average
exposure across decision dates in 2011..2026; FF5+UMD attribution; comparator rows (SPMO, MTUM, SPY,
RSP); `sharpe_interval` (20-day circular block bootstrap 95% CI) for anything called a win.

## Dilution control

For the best variant only, with average exposure `a`: a static blend `a × B_daily_return +
(1 − a) × daily bill return`, evaluated over the same three windows. A variant whose Sharpe gain is
matched by this blend has diluted the book, not improved it.

## Outputs

`reports/vol_managed_momentum_20260919/REPORT.md`, per-variant daily NAV CSVs, `results.json`,
`exposures.csv`.

## Decision rule, stated in advance

A variant counts as a win only if it beats **SPMO's Sharpe in both halves** (0.70 and 0.89) at base
cost, survives stress cost, and beats its own dilution control. Winning one half and losing the
other is a null and will be reported as one. "Nothing beat SPMO" is an acceptable outcome.
