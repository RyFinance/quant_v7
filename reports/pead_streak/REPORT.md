# Earnings-surprise streaks (candidate C1): development FAIL, validation not run

Plan: `research/pead_streak/PLAN.md`, registered 2026-09-19T06:43:51-0700 (sha256 57f1b696…) in
`research/preregistrations.jsonl` before any return was computed. Code: `research/pead_streak/streak.py`;
tests: `tests/test_pead_streak.py` (7 pass); numbers: `reports/pead_streak/dev/results.json`.

**Verdict: neither candidate passes the development gate, so validation stays locked and nothing
challenges the PEAD 2x benchmark (excess Sharpe 0.70).**

## Design (as registered)
- Events: `earnings_sue_expanded` / `pead_signal_expanded`, 18,844 announcements, 489 tickers,
  2015-04 -> 2025-06 (all previously used by PEAD work: development evidence only).
- Streak: surprise sign equals the previous quarter's sign; the previous announcement must be 30-200
  days earlier and tradable before the current effective date.
- Enter at the close of day +1 after the effective date, hold 20 sessions (returns days +2..+21).
  Equal weight, rebalanced daily. S1 long-short 0.5/0.5; S2 long-only 1.0.
- 5 bps per side on turnover and 0.5% borrow (stress: 3x). Marked daily, excess over T-bills.
- Controls: same engine on all events (C1 long positive / short negative; C2 long all positive).
- Development: events 2015-04-01 -> 2021-06-30 (~60%). Validation: 2021-07 -> 2025-06, locked.
- S3 (benchmark book filtered to streaks) was dropped before any result: its ledger lies wholly in
  the validation window.

## Development (2015-04 -> 2021-06, 467 tickers with prices)
11,262 nonzero-surprise events; 10,785 with a known previous surprise; 7,751 streaks
(6,927 positive, only 824 negative, so the short leg is thin).

| Book | Net excess Sharpe [95% CI] | Gross | Stress | p (1-sided) | Beta | Alpha/yr (t) | Gate |
|---|---|---:|---:|---:|---:|---|---|
| S1 streak long-short | 0.13 [-0.45, 0.73] | 0.46 | -0.54 | 0.32 | 0.03 | +0.7% (0.27) | **fail** (< 0.5) |
| S2 streak long-only | 0.79 [-0.02, 1.70] | 0.93 | 0.52 | 0.012 | 0.99 | +0.2% (0.10) | **fail** (below control) |
| C1 all-events long-short | -0.56 [-1.27, 0.13] | 0.01 | -1.71 | 0.94 | -0.02 | -2.8% (-1.45) | control |
| C2 all-positive long-only | 0.83 [0.04, 1.75] | 0.98 | 0.55 | 0.010 | 0.98 | +1.4% (0.56) | control |

- Deflated Sharpe probability (65 trials): S1 0.00, S2 0.03.
- Candidate minus control (daily difference): S1 - C1 Sharpe 0.67 (p 0.036), so the streak filter
  does improve the plain-PEAD spread, as Loh & Warachka find. But that spread starts from -0.56,
  and S1 ends at 0.13. S2 - C2 is -0.51 (p 0.89): among long positions, the streak filter adds nothing.
- S2 is the market: beta 0.99 and alpha 0.2%/yr. Its Sharpe is the 2015-2021 S&P 500 on
  surviving names, which the control also earns.
- Costs: daily equal-weight rebalancing gives about 54x annual turnover and about 2.8%/yr of drag.
  Even gross, S1 (0.46) is below the 0.5 gate and S2 (0.93) is below its control (0.98).
- Null kind at 0.5: S1 and S2 are both vacuous (their intervals cannot rule out 0.5).
- Correlation with the PEAD benchmark: not computed. The benchmark window (2021-08 -> 2025-06) lies
  entirely inside the locked validation window.

By year (net excess return; Sharpe):

| Year | S1 | S2 | C2 |
|---|---|---|---|
| 2015 (Apr-) | -0.2% (-0.04) | -5.0% (-0.50) | -2.1% (-0.10) |
| 2016 | -1.9% (-0.27) | 4.1% (0.35) | 5.1% (0.42) |
| 2017 | 9.1% (2.09) | 19.2% (2.10) | 20.4% (2.30) |
| 2018 | -5.9% (-1.03) | -3.4% (-0.12) | -3.2% (-0.12) |
| 2019 | -3.2% (-0.54) | 34.1% (2.32) | 34.7% (2.37) |
| 2020 | 6.0% (0.43) | 24.9% (0.79) | 25.6% (0.81) |
| 2021 (-Jun) | 1.3% (0.29) | 18.7% (2.36) | 19.1% (2.44) |

## Notes
- After the first dev run, one bug was fixed: in long-only books, a negative event (never held)
  wrongly blocked the ticker. The fix follows the plan's rule ("a ticker already held") and changed
  no reported figure at two decimals. No parameter was changed.
- The universe is today's S&P 500, which biases the long books upward. That bias affects the
  controls equally.

Reproduce: `PYTHONPATH=. .venv/bin/python -m research.pead_streak.streak dev`
