# Options-implied stock signals: pre-registration

Written 2026-09-18, before any option-derived statistic was computed. The option data were being
pulled while this was written; no signal, return or summary of them had been calculated.

## Why this is a legitimate new test

Every stock/ETF/FX/crypto price window from 2003 to 2026 has already been inspected by this project
(see `research/preregistrations.jsonl`). What is new is the **information set**: OPRA option trade
prints from the London Strategic Edge vault (`/export`, `dataset=options`, `timeframe=1d`: one row per
contract per day, open/high/low/close/volume of trades, 2014-06 onward). No quant_v7 experiment has
used option data before. The stock return windows are not pristine, so these results are evidence
about the option signals, not about the market paths. Any candidate that passes still needs a forward
paper test from its own registration date before capital.

## Data

- Options: `data/lse/options_1d/{T}.parquet` from `data/pull_options_1d.py`. The universe rule is in
  that file and in `universe.json`: 100 current S&P 500 names with options history from 2014-06-30 or
  earlier, ranked by mean dollar volume over 2014-01..2014-06. It still carries survivorship bias from
  current membership; the ranking uses no post-2014 information.
- Contracts kept: the OSI root equals the ticker (standard 100-share deliverable; adjusted contracts
  are dropped), close price ≥ $0.10, daily volume ≥ 1, calendar DTE within each signal's window.
- Stocks: `data/multiasset/stocks/{T}.parquet` (yfinance official session, split- and dividend-adjusted
  OHLCV). Portfolio returns use open-to-open adjusted prices.
- Raw spot for moneyness and IV = yfinance close ÷ (dividend adjustment) × (product of later split
  ratios), using `data/lse/stock_splits`. Raw share volume = adjusted volume ÷ later split ratios.
- Rates: French daily RF (as in earlier experiments), continuously compounded for IV.
- Dividends: `data/lse/dividends` (amounts are raw, not split-adjusted, which matches raw strikes).
  Present value of cash dividends with ex-date in (t, expiry] is subtracted from spot for IV. Using
  realised ex-dates is a mild look-ahead that is standard in vendor IV surfaces; it is recorded here.
- IV: Black–Scholes European on the dividend-adjusted spot, solved by bisection in [0.01, 3.0]; a
  contract whose price is outside the no-arbitrage bounds is dropped. Only OTM or near-ATM contracts
  are used, where the early-exercise premium is small.
- No bid/ask quotes exist: prices are last trades, so daily IVs carry bid-ask bounce. Every signal is
  therefore a mean over the 5 trading days ending on the signal date (fixed now, not tuned).

## Candidates (four, and only four)

All are cross-sectional within the universe; a stock needs the signal on at least 3 of the 5 days.

1. **H1_os — option-to-stock volume** (Johnson & So, 2012, JFE). O/S = Σ option contract volume × 100 ÷
   Σ raw stock share volume over the 5 days. High O/S → lower returns. Long lowest quintile, short
   highest.
2. **H2_ivspread — call-minus-put implied volatility** (Cremers & Weinbaum, 2010, JFQA). Each day, over
   call/put pairs with the same strike and expiry, both traded that day, 7 ≤ DTE ≤ 60 and
   |ln(K/S)| ≤ 0.10: the volume-weighted mean of IV_call − IV_put, with weight = mean volume of the pair.
   Open interest is not available, so volume replaces it. High spread → higher returns. Long highest
   quintile, short lowest.
3. **H3_skew — put smirk** (Xing, Zhang & Zhao, 2010, JFQA). Each day, in the nearest expiry with
   10 ≤ DTE ≤ 60 that has both legs: IV of the put with K/S in [0.80, 0.95] closest to 0.95, minus IV of
   the call with K/S in [0.95, 1.05] closest to 1.00. High skew → lower returns. Long lowest quintile,
   short highest.
4. **H4_composite — fixed blend.** Mean of the cross-sectional percentile ranks of −O/S, +IV spread and
   −skew, needing at least 2 of the 3. Equal weights are fixed now and never fitted.

## Portfolio and costs

- The signal date t is the last trading day of each calendar week. Entry is at the next session's
  open; the position is held to the open after the next signal date (about one week).
- Equal weight: the long quintile gets 100% of NAV and the short quintile 100% (gross 2.0, within Reg-T).
  A week needs at least 25 stocks with the signal, otherwise the book is flat.
- Base costs: 5 bps per side on traded notional (from weight changes, so turnover is charged exactly),
  plus short borrow at 0.5%/yr on the short leg. These are large-cap names where general-collateral
  borrow is typical; this is an assumption, not a broker quote.
- Stress costs: 15 bps per side plus 3%/yr borrow, and short proceeds earn nothing (RF deducted from
  the spread).
- Reported return = long leg − short leg − costs − borrow, i.e. an excess return that assumes short
  proceeds earn RF (base) or nothing (stress). Break-even cost per side is reported for each candidate.

## Windows, selection and gates

- **Development:** signal dates 2014-07-01 → 2019-12-31. The loader refuses signal dates from 2020 on
  until `VALIDATION_UNLOCK.md` is registered in `research/preregistrations.jsonl`.
- **Development gate (selects for validation):** net base excess Sharpe ≥ 0.5 on weekly returns,
  annualised by √52. If no candidate passes, the experiment stops with a null result and validation is
  not run.
- **Validation:** signal dates 2020-01-01 → 2026-09-17, run once, only for candidates that passed
  development.
- **Validation pass (each candidate):** net base Sharpe ≥ 0.75, stressed mean > 0, and a one-sided
  circular-block bootstrap p-value (8-week blocks, 5,000 draws) below 0.05/4 = 0.0125 (Bonferroni over
  the four registered candidates). Newey–West t-statistics with 4 lags are also reported.
- A validation pass means "start a forward paper test" on the LSE sim account; it does not mean
  capital. No threshold, window, universe, quintile, holding period or cost figure may change after
  results are seen. Any change is a new, separately registered experiment.

## Expectations stated in advance

The published effects were strongest in small, illiquid stocks and before about 2010. In 100 mega
caps after 2014, with trade prices instead of quotes, the prior expectation is a net Sharpe of 0 to
0.8. The project target (Sharpe ≥ 2, >10%/yr) is very unlikely to come from any one of these. An
honest null result is an acceptable outcome.
