# Amendment 3: two input/calendar defects found in data QA

Written 2026-09-19, while the option pull was still running (36 of 100 names on disk) and before the
registered development run. No signal–return statistic, portfolio return, Sharpe ratio or ranking of
names by later performance had been computed on any window. The only numbers seen were data-quality
figures: row counts, strike-versus-spot alignment, dividend amounts, and development-window signal
levels, coverage and IV-solver diagnostics (`reports/options_signals/QA.md`). Nothing here changes a
candidate, threshold, window, universe, filter, quintile rule, holding period or cost.

## Defect 1: some vault dividend amounts are back-adjusted, not raw

PLAN.md takes cash dividends from `data/lse/dividends` on the premise that "amounts are raw, not
split-adjusted, which matches raw strikes". The premise fails for two universe names:

- **GE**, ex-dates 2015-12-17 → 2021-06-25: the vault amount is 4.7924 × the cash actually paid (e.g.
  2017-06-15: 1.15019 against $0.24 paid). 4.7924 = 1 / 0.2087, the product of GE's later yfinance
  split and spin-off factors (1.04, 0.125, 1.281, 1.253).
- **T**, ex-dates 2014-07-08 → 2022-01-07: the vault amount is 0.7553 × the cash paid (1 / 1.324, the
  2022 WarnerMedia factor).

With these amounts, PV(dividends) for GE in 2016–2018 was overstated by about 3% of spot, which
lowers the dividend-adjusted spot, raises call IVs and lowers put IVs. GE's rolling H2 value had a
95th percentile of 0.234 (0.02–0.04 for the other 21 names first checked), |H2| > 5% on 24.5% of
development days, and a negative H3 skew on 27% of days. Recomputed with the cash actually paid,
these become 0.039, 1.7% and 2.7%, in line with the other names. H1 does not use dividends.
Post-2020 the same comparison also finds COP's two variable-return dividends doubled (2021-12-31,
2022-03-30), QCOM's 2021 increase dated one quarter early, and MGM's $0.0025 dividends shown by
yfinance as $0.003 (3-decimal rounding).

**Fix.** `signals.load_dividends` keeps the vault's rows (which dividends exist, and their ex-dates),
but where the raw yfinance file already registered in amendment 1.3 (`data/stocks_raw_2014/{T}.parquet`,
the source of raw spot and of split dates) has a cash dividend on the same ex-date, the amount is that
file's raw amount, `Dividends × split_factor_after`: the same back-out that turns its `Close` into
`raw_close`. Vault rows without a same-day yfinance dividend are left unchanged. On every other matched
development-window ex-date (89 dividend-paying names) the two sources agree to within 0.31%, i.e.
rounding, so for those names the change is immaterial.

Known and deliberately left as registered (each is at most about 1% of spot for at most one quarter):
vault rows with no yfinance counterpart, namely MSFT 2019-01-24 $0.123, QCOM 2018-02-15 $0.57 (a
second copy of the 2018-02-27 dividend), HON 2016-09-15 $0.66 and 2018-09-17 $1.85 (around its
spin-offs), MDT 2018-09-27 $0.50 (probably genuine; yfinance lacks it), the pre-2017 DD rows (see
QA.md), and ex-date differences of 6–7 days for ACN 2015 and HPQ 2016.

## Defect 2: a mid-week signal date at the end of the development window

Amendment 1.5 fixes the signal date as the last trading day of each ISO week. `evaluate.run` found
ISO-week maxima on the trading calendar already cut at DEV_END, so Tuesday 2019-12-31 became a signal
date, although ISO week 2020-W01 runs to Friday 2020-01-03. That added a 288th development week and
split the last holding period into 3 and 2 trading days.

**Fix.** Signal dates are found on the whole trading calendar loaded for the run (exchange days are
known in advance, and no price value is used), and then restricted to [start, end]. The first signal
date after `end` is still appended only to define the last exit. Development: 287 signal dates, the
last 2019-12-27, held from the 2019-12-30 open to the 2020-01-06 open. Validation: the price files
end on 2026-09-18, so its last registered signal date is 2026-09-11. Its registered exit, the open
after 2026-09-18, is not in the data, so that week is not evaluated. The old code had instead used
Thursday 2026-09-17 as a signal date and closed the 2026-09-11 book at the 2026-09-18 open.

## Tests

`tests/test_options_signals.py` gains one test for each fix: raw amounts replace back-adjusted vault
amounts on matching ex-dates and unmatched rows are kept, and no signal date falls inside an ISO week
that continues past the window end.
