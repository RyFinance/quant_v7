# Residual (idiosyncratic) momentum — 2026-09-19

Pre-registration for a momentum-lab experiment. Motivation: Blitz, Huij & Martens (2011),
"Residual momentum", argue the tradable part of momentum is the stock-specific component. Ranking on
the residual of a factor regression rather than on raw return is claimed to deliver a similar return
at roughly half the volatility, with smaller crashes, because the portfolio stops implicitly betting
on whichever factor has recently run. The frozen 12-1 baseline on this harness loads heavily on the
market (beta 1.15) and on UMD (0.66) and shows no alpha (t = -0.27); the question is whether
residualising the score cuts those loadings and produces risk-adjusted improvement.

## Fixed harness settings (unchanged from the baseline)

`research/momentum_lab/core.py` is used as-is and not modified. All variants run with the harness
defaults: `universe='pit'`, `slots=20`, `weight='equal'`, `rebalance='M'`, `min_score=0.0`
(positive scores only, matching the baseline), no sector cap, no exposure overlay. Frozen execution
engine, next-session open fills, base 5bps/side and stress 15bps/side, idle cash at the 13-week bill.
Windows: 2011..2018, 2019..2026, 2011..2026. The score is computed on monthly decision dates only
and forward-filled between them (the harness reads `score.loc[date]` at each rebalance).

Estimation window: trailing 756 sessions (3 years) of daily excess returns ending at the decision
date. Scoring window: t-252 .. t-21, i.e. 12-1 with the last month skipped, consistent with the
baseline's skip. A stock is ineligible at a date if it lacks sufficient history in the estimation
window; gaps are never filled.

## Variants — exactly these four, and no others

- **R1 CAPM-residual momentum.** At each monthly decision date, regress each stock's daily excess
  returns (stock return minus RF) on a constant and MktRF over the trailing 756 sessions.
  Score = sum of the regression residuals over the t-252 .. t-21 window.
- **R2 FF3-residual momentum.** As R1, regressing on a constant, MktRF, SMB and HML.
  Score = sum of residuals over t-252 .. t-21.
- **R3 standardised residual momentum.** R2's residual sum divided by the standard deviation of the
  same residuals over the same t-252 .. t-21 window. This is the Blitz-Huij-Martens construction,
  which is what their paper ranks on.
- **R4 risk-adjusted raw momentum (control).** The baseline's raw 12-1 return
  (`close.shift(21)/close.shift(252) - 1`) divided by the stock's trailing 252-session daily return
  volatility at the decision date. This is not residual momentum; it is the cheap approximation.
  It is included to test whether the factor regression does any work beyond simple volatility
  scaling.

## Implementation commitment

The rolling regressions are solved with batched linear algebra (one design matrix per decision date,
all eligible stocks solved together via least squares, missing data masked out rather than filled).
The fast path will be verified against a slow, obviously-correct per-stock loop on a handful of
stock-months; the check and its result will be reported.

## Reporting commitment

All four variants, across all three windows, at base and stress costs, with the comparator rows
(SPMO, MTUM, SPY, RSP) and the baseline. Volatility and maximum drawdown are reported alongside
Sharpe for every variant, because the paper's claim is specifically about risk reduction: matching
the baseline's return at materially lower volatility counts as a success even at a lower CAGR. The
FF5+UMD attribution is reported for every variant. A bootstrap Sharpe interval (`sharpe_interval`,
20-day circular block) is reported for anything called a win.

## The bar

SPMO's Sharpe: 0.70 in 2011..2018, 0.89 in 2019..2026, 0.84 over 2011..2026. A variant counts only
if it beats SPMO's Sharpe in **both** halves. Winning one half and losing the other is a null and
will be reported as one. No grid search, no lookback tuning, no variant added after seeing a result;
a new idea requires a registered amendment and the report must say it was an amendment.

Deliverable: `reports/residual_momentum_20260919/REPORT.md`, daily NAV CSVs and a results JSON.
