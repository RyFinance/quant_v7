# IV changes (candidate C2, An-Ang-Bali-Cakici 2014): status

**Status (2026-09-19 06:45 PDT): registered and built; the development run is queued and has not run.**
No strategy return has been computed for any window.

## Registration

- `research/iv_changes/PLAN.md`, sha256 `ca7c5eca…a621f593`, registered 2026-09-19T06:42:59-0700 in
  `research/preregistrations.jsonl` (`results_computed_before_registration: false`). A separate trial
  from the options-level experiment (`research/options_signals/`), counted separately in the ledger.
- Candidates: V1 +ΔIV_call, V2 −ΔIV_put, V3 ΔIV_call − ΔIV_put (the OSAP `dCPVolSpread` direction).
- 30-day ATM IV: per expiry, the traded contract with strike nearest the raw spot (|ln K/S| ≤ 0.05,
  7–90 DTE); IV from the registered options pipeline (imported: filters, split rule, dividends with
  amendment 3, wrong-underlying check of amendments 4–5); bracket the expiries around 30 DTE and
  interpolate total variance; mean over the 5 trading days ending at month-end (≥ 3 days). Monthly change
  between consecutive month-end signal dates.
- Monthly book: enter at the open after the month-end, hold to the open after the next month-end; long
  the top quintile, short the bottom, equal weight, 100% NAV per leg; ≥ 25 names. Costs 5 bps/side +
  0.5% borrow (stress 15 bps, 3%, proceeds earn nothing). Engine: `research.options_signals.evaluate.backtest`.
- Windows: development signal dates 2014-07-31 → 2019-12-31; validation 2020-01-31 → 2026-09-30,
  locked until `research/iv_changes/VALIDATION_UNLOCK.md` is registered.
- Gates: development net Sharpe ≥ 0.5 (monthly, ×√12). Validation: net ≥ 0.75, stressed mean > 0,
  block-bootstrap p < 0.05/3, and gross Sharpe ≥ 0.70.

## Code and tests

- `research/iv_changes/atm_iv.py` (daily 30-day ATM call/put IV), `research/iv_changes/evaluate.py`
  (dev/validation runs; names processed one at a time).
- `tests/test_iv_changes.py`: 10 tests pass: IV recovery on a synthetic BS market, no look-ahead (later
  prints don't change earlier values), nearest-strike and bracket rules, month-end alignment (including
  the partial final month), changes against the previous month-end, next-open entry, base/stress costs,
  √12 annualisation, validation lock, and refusal while the pull is incomplete.

## Data QA (levels only, development window, 60 names on disk)

`reports/iv_changes/qa_names_on_disk.csv`. Daily 30-day ATM IV coverage: median 100%, mean 98.3%.
Month-end change coverage: 98.5% for most names. Median ATM IV 0.22. Call-minus-put level gap: median
+0.4 vol points, largest for T (+1.2) and TSLA (−1.4). Correlation of monthly ΔIV_call with ΔIV_put
is 0.89 on average, so V3 is the small difference of two closely related series. DD keeps only 10% coverage
because the amendment 4–5 check removes its wrong-underlying days (as intended).

## Queue

A detached waiter (`research/iv_changes/wait_and_run_dev.sh`, nohup, log
`reports/iv_changes/waiter.log`) checks every 10 minutes. It starts once all 100 universe files exist
and no `data.pull_options_1d`, `run_pending_pulls.sh` or `research.options_signals.evaluate` process is
running, so it never overlaps the registered options development run. It then runs
`research.iv_changes.evaluate dev` once (skipped if `reports/iv_changes/dev/results.json` already
exists) and gives up after 72 hours. Results: `reports/iv_changes/dev/results.json`,
`selection.json`, per-candidate monthly CSVs, and `reports/iv_changes/dev_run.log`.
