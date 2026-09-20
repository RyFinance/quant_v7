# Intraday and event-day futures strategies (non-PEAD): pre-registration

Written 2026-09-18, after pulling 30-minute ES/NQ/GC/SI bars (`data/lse/futures_30m/`, 2016-06 → 2026-09)
and the LSE economic calendar (`data/lse/econ_calendar_us.parquet`). Only data conventions were
checked: bar labels, the largest gaps, and calendar event names. No predictor–return relation was
computed. Intraday price paths are a new information set for quant_v7; daily futures windows are not
new (the multi-asset book used daily futures and ETFs).

**Benchmark to beat:** PEAD 2× excess Sharpe **0.70** (`reports/pead_audit/REPORT.md`), measured the
same way here: daily-marked, net, excess returns. Futures P&L is already an excess return, with margin
cash earning RF outside the book.

## Data conventions (checked)

- Bars are left-labelled: the highest-volume labels are 09:30 and 15:30 ET, the open and close
  auctions. Times are converted from UTC to America/New_York with DST.
- P(hh:mm) = close of the bar labelled 30 minutes earlier. P(16:00) = close of the 15:30 bar;
  P(10:00) = close of the 09:30 bar; P(15:30) = close of the 15:00 bar.
- A day needs all of these bars on both that day and the previous trading day (for the prior 16:00
  close), otherwise the day is flat.
- **Roll exclusion:** days from the Thursday before the third Friday of Mar/Jun/Sep/Dec through the next
  Monday are flat. The continuous front-month series can jump overnight when it rolls.

## Candidates (four)

Every intraday candidate trades ES and NQ at 0.5 × NAV notional each, enters at P(15:30) and exits at
P(16:00) on the same day.

1. **I1_intraday_momentum** (Gao, Han, Li & Zhou 2018, JFE): position = sign(ln P(10:00)/P_prev(16:00)).
2. **I2_rest_of_day** (Baltussen, Da, Lammers & Martens 2021, JFE): position = sign(ln P(15:30)/P_prev(16:00)).
3. **I3_ml_lgbm**, the machine-learning comparison. The terminal offers gradient boosting on technical
   features; this tests whether it adds anything over I1/I2.
   - Model: LightGBM binary classifier with fixed hyperparameters, never tuned: n_estimators 300,
     learning_rate 0.03, num_leaves 15, min_child_samples 50, subsample 0.8 (bagging every
     iteration), colsample_bytree 0.8, random_state 7.
   - Features at 15:30 ET, per instrument:
     - log returns over the last 1, 2, 4, 8 and 12 bars;
     - the overnight return P_prev(16:00)→P(09:30 bar open);
     - the first-half-hour return;
     - the rest-of-day return (I2's predictor);
     - RSI(14) and Bollinger %b(20) of 30-minute closes;
     - ATR(14)/price on 30-minute bars;
     - the 20-day realised volatility of daily 16:00 closes;
     - the z-score of the 15:00 bar's volume against the same bar's trailing 20-day volumes;
     - day of week, and an instrument flag.
   - Target: the sign of the 15:30→16:00 return. ES and NQ rows are pooled.
   - Training is expanding: retrain every 1 January on all earlier rows. The first model trains on
     2016-06 → 2017-12 and first predicts 2018. Position = +1 if P(up) > 0.5, else −1.
4. **I4_announcement_day** (Savor & Wilson 2013; Lucca & Moench 2015):
   - Hold long ES and NQ (0.5 each) from P_prev(16:00) to P(16:00) on scheduled US announcement days.
   - Announcement days are rows with `region_code == "US"` and event "Fed Interest Rate Decision",
     "CPI YoY", or an event starting "Non Farm Payrolls " (not "Private").
   - The day is the release's New York date. Flat on all other days.

## Costs

Base: 0.5 bp per side of traded notional (half the ES/NQ tick, auction slippage and commission).
Stress: 1.5 bp per side. I1–I3 pay two sides per trading day; I4 pays two sides per event.

## Windows and gates

- Development: 2016-06-01 → 2020-12-31 (I3 predicts 2018-01 → 2020-12).
- Validation: 2021-01-01 → 2026-09-17, locked until `research/intraday/VALIDATION_UNLOCK.md` is
  registered, and run only for development-selected candidates.
- Development gate: net base Sharpe ≥ 0.5 (daily returns including flat days, √252).
- Validation pass: net base Sharpe ≥ 0.75; stressed mean > 0; one-sided circular-block bootstrap
  p < 0.05/4 (21-day blocks, 5,000 draws); and a Sharpe above the benchmark's 0.70.
- Also reported: the 95% interval, whether a null is bounded or vacuous at 0.5, and the correlation
  with the PEAD benchmark on common dates.

## Expectations stated in advance

- Intraday momentum was published in 2018 and its strength depends on dealer gamma positioning.
  Post-publication decay is likely.
- Announcement-day premia concentrate return in about 30 days a year, so the annualised Sharpe is
  modest even if the per-day effect is real.
- An ML model on technical indicators rarely beats a simple rule out of sample; that is the question
  I3 answers.
- Prior: net Sharpe 0 to 0.8.
