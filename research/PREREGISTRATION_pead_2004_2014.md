# Pre-registration: the production PEAD model on 2004–2014

Written 2026-09-17, **before** any 2004–2014 PEAD result was computed by this project.
Its SHA-256 is recorded in `research/preregistrations.jsonl` at the moment of writing.
Nothing below may change after results are seen; any change is a new, separately
dated pre-registration, and this one still gets reported.

## Why this test

Every PEAD result so far comes from 2015–2025, a window this project has examined so
many times that the luckiest of the 37 strategies tried would average a Sharpe of 1.77
with no edge at all (`reports/sleeve_blend/`). The production model was fit only on
2015-onward events. **2004–2014 has never been used for anything**, because the price
cache began in 2015. The LSE vault now supplies daily candles from 2003, and the
analyst-estimate earnings history on disk already reaches ~2000. Scoring that decade
with the model *exactly as it is* is the cleanest out-of-sample test available.

## Hypothesis (one primary test)

> **H1.** Events the unchanged production model chooses to trade in 2004-01-01 →
> 2014-12-31 earn positive returns beyond their market exposure, and beat trading every
> event without the model.

## Data

| Input | Source |
|---|---|
| Stock prices | LSE vault daily candles (split-adjusted) plus LSE dividends for total return |
| Market | SPY from yfinance (split- and dividend-adjusted) |
| Earnings dates, estimates, actuals | `data/earnings_raw/` (yfinance), the same source the model was trained on |
| Risk-free | French daily RF, the snapshot already in `reports/higher_sharpe/inputs/` |
| Universe | the 503 current S&P 500 constituents (**survivorship-biased**, see below) |

## Rules (fixed now)

- **Features:** built exactly as in training (`earnings/features.py`): SUE via
  `earnings/sue.py`; 5- and 20-day pre-event returns from market-model residuals
  (60-day rolling beta vs SPY, `clustering/residual_returns.py`); liquidity rank from
  `reports/universe_ranking.csv`.
- **Event timing:** effective trading date as in `earnings/signal.py` (after-close
  reports count from the next session).
- **Model:** `bot/state/model/pead_model_expanded.joblib`, loaded, never refit.
- **Sizing:** quarter-Kelly with the model's own payoff ratio; direction = sign(SUE).
  Primary configuration is the **live one**: 5% per position, 100% gross.
- **Execution:** decision at the effective-date close, fill at the **next session's
  open** (more conservative than the live bot's same-close fill), hold 20 sessions,
  daily mark-to-market.
- **Costs:** 10 bps round trip, 3% annual short borrow; free cash earns RF.
- **Not replayed:** the circuit breaker (its calibration history starts in 2015).

## Controls

1. **All-events control:** every event traded in the SUE direction at equal size, same
   caps, costs and execution. Tests whether the *model* adds anything.
2. **SPY:** the market over the same period, for beta and alpha.

## Metrics

Daily mark-to-market excess return over RF: Sharpe, CAGR, volatility, max drawdown;
beta and Newey-West (HAC, 20 lags) alpha t-statistic versus SPY excess returns;
number of trades.

## Pass criteria (all three required)

1. Alpha HAC t-statistic **≥ 2.0** over 2004–2014.
2. The model portfolio beats the all-events control: the 63-day paired block-bootstrap
   95% interval for the excess-Sharpe difference **excludes zero**.
3. Alpha is **positive in both halves**, 2004–2008 and 2009–2014.

## How to read the outcome

- The universe is today's constituents, which biases returns **upward**. A **fail** is
  therefore robust; a **pass** is necessary but not sufficient evidence of an edge.
- Only the primary configuration decides pass or fail. Any other configuration
  reported alongside it is descriptive.
- Whatever the outcome, it is reported, including if it contradicts the live setup.
