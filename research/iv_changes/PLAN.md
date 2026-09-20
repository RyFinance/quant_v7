# Implied-volatility changes (An, Ang, Bali & Cakici 2014): pre-registration

Written 2026-09-19, before any code for this experiment existed and before any ATM IV, IV change,
signal-return statistic or portfolio return had been computed. The OPRA pull was at 60 of 100 names.
This is candidate C2 of `reports/edge_graveyard/CANDIDATES.md`. It is a **separate** trial from the
registered options-level experiment (`research/options_signals/PLAN.md`, amendments 1-5), which tests
IV levels weekly; this one tests monthly IV *changes* on the same data and is counted separately in
the ledger.

## Hypothesis

An, Ang, Bali & Cakici (2014, JF): stocks whose call implied volatility rose over the past month
outperform next month; stocks whose put IV rose underperform. Chen-Zimmermann (OSAP) `dVolCall` and
`dCPVolSpread` keep 2015+ Sharpe of about 0.71-0.80 excluding microcaps. Prior expectation for 100
mega caps with trade prices (no quotes), after costs: net Sharpe 0.2-0.5. A null is acceptable.

## Data, inherited unchanged from the options-signals registration

- Universe: the 100 names in `data/lse/options_1d/universe.json` (survivorship caveat as registered).
- Options `data/lse/options_1d/{T}.parquet`; raw spot, raw volume and split dates from
  `data/stocks_raw_2014`; portfolio prices `data/multiasset/stocks` (adjusted open-to-open); French
  daily RF (last value carried forward); dividends with amendment 3's raw-amount fix.
- Imported, not copied, from `research/options_signals/signals.py`: the general filters (close >= $0.10,
  volume >= 1), the split rule (amendment 1.1), Black-Scholes IV by bisection on [0.01, 3.0] on the
  dividend-adjusted spot (PV of cash dividends with ex-date in (t, expiry]), and the wrong-underlying
  check (amendments 4-5): a name-day flagged by it has no ATM IV. The dividend look-ahead horizon is
  widened from 70 to 100 days only because this signal uses expiries up to 90 DTE.
- Trading calendar and missing-price handling as amendments 1.5-1.6 (next-session open required to
  enter; missing exit open exits at the last available close).

## 30-day ATM implied volatility (fixed now)

For each name, each trading day d, and each option type (call, put) separately:

1. Candidate contracts: pass the filters above, 7 <= calendar DTE <= 90, |ln(K/S)| <= 0.05, where S is
   the raw close on d.
2. For each expiry, the ATM contract is the one with strike nearest S (ties: the lower strike). Its IV
   is solved with T = DTE/365 and r = the day's rate. If that IV does not solve, the expiry has no ATM IV
   that day (no fall-back to another strike).
3. Bracket: E1 = the longest expiry with DTE <= 30 having an ATM IV; E2 = the shortest with DTE > 30
   having an ATM IV. Both are required, otherwise the day has no value.
4. Interpolate total variance linearly in T to 30 days:
   sigma30^2 = [sigma1^2 T1 (T2 - T30) + sigma2^2 T2 (T30 - T1)] / [(T2 - T1) T30], T30 = 30/365.
5. Level on a signal date = mean of daily sigma30 over the 5 trading days ending on that date,
   needing at least 3 (as the options registration, to damp bid-ask bounce in trade prices).

## Signal dates and changes

- Signal date m = the last trading day of each calendar month, found on the whole trading calendar.
- dIV_call(m) = callIV5(m) - callIV5(m-1); dIV_put likewise. Both months' levels are required.

## Candidates (three, and only three)

- **V1_dcall**: score = +dIV_call (long rising call IV).
- **V2_dput**: score = -dIV_put (short rising put IV).
- **V3_dspread**: score = dIV_call - dIV_put (OSAP `dCPVolSpread` direction); needs both.

## Portfolio and costs

- Entry at the open of the first trading day after signal date m; held to the open after signal
  date m+1 (one month). Long the top quintile of the score, short the bottom quintile, equal weight
  inside each leg, 100% of NAV per leg (gross 2.0). Quintiles by `pd.qcut` on `rank(method="first")`.
  A month needs at least 25 names with a score, otherwise flat.
- Base costs: 5 bps per side on traded notional (turnover from drifted weights), 0.5%/yr borrow on the
  short leg, short proceeds earn RF. Stress: 15 bps per side, 3%/yr borrow, proceeds earn nothing.
- The portfolio engine is `research.options_signals.evaluate.backtest` (imported), run on monthly dates.

## Windows, lock and gates

- **Development:** signal dates 2014-07-31 -> 2019-12-31 (the first change uses the 2014-06-30 level).
  Option, spot and dividend inputs are truncated at 2019-12-31 before any signal is computed; prices
  run to 2020-02-15 only to close the last month.
- **Validation:** signal dates 2020-01-31 -> 2026-09-30. A month whose registered exit open is not yet
  in the price data when validation runs is not evaluated. The code refuses validation unless
  `research/iv_changes/VALIDATION_UNLOCK.md` is registered, with a matching hash, in
  `research/preregistrations.jsonl`, and it evaluates only candidates development selected.
- **Development gate:** net base Sharpe >= 0.5 on monthly returns (annualised by sqrt(12)). None
  passes -> null result, validation not run.
- **Validation pass (each selected candidate):** net base Sharpe >= 0.75; stressed mean net return > 0;
  one-sided circular-block bootstrap p < 0.05/3 = 0.0167 (3-month blocks, 5,000 draws); and gross
  Sharpe >= 0.70 (at least the published post-2015 ex-microcap level before costs). Newey-West t with
  3 lags is reported. A pass means a forward paper test, not capital.
- No construction choice, threshold, window, universe, quintile, holding period or cost may change
  after results are seen; any change is a new registered experiment.
