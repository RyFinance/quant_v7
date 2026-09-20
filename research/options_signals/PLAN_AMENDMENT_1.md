# Amendment 1: implementation details, fixed before any option-derived result

Written 2026-09-18 after checking raw data layout only (OSI roots, strike grids around the AAPL
2020 split, raw vs adjusted closes). No signal, return or signal–return statistic had been computed.
Nothing here changes a candidate, threshold, window, universe or cost in PLAN.md.

1. **Split-adjusted contracts.** The vault writes adjusted contracts under the plain root (AAPL on
   2020-08-31: 49 of 108 Sept-18 calls had off-grid strikes such as 126.25), so "root equals ticker"
   cannot remove them. Rule: for every split on date D (yfinance `Stock Splits`), drop every row with
   ts ≥ D whose expiry already appears in that underlying's rows before D. This also drops standard
   series relisted in pre-split expiries, which costs at most about two months of signal per split.
2. **Other deliverable adjustments** (spin-offs, special dividends) cannot be identified from the
   symbol. For H2, a call/put pair is dropped when |C − P − (S − PV(div) − K·e^(−rT))| > 0.10·S, far
   outside normal American-option parity gaps. For H3, a leg is dropped when its IV does not solve in
   [0.01, 3.0] (as PLAN.md). H1 uses volumes only and keeps every contract.
3. **Raw spot and volume** come from yfinance `auto_adjust=False`: raw close = split-adjusted Close
   times the product of later split ratios; raw volume = split-adjusted Volume divided by the same
   factor (`data/pull_stock_raw.py` → `data/stocks_raw_2014/`). This replaces the "divide by the
   dividend adjustment" wording in PLAN.md and gives the same number.
4. **Rates.** French daily RF, compounded to an annual continuous rate for T; the file ends
   2026-07-31 and its last value is carried forward. Signals use the rate on date t.
5. **Calendar.** Trading days = dates in the AAPL official-bar file. The signal date is the last
   trading day of each ISO week. The option file's `ts` (UTC midnight) is the trading date.
6. **Missing prices.** A stock without a next-session open is not entered that week. A held stock
   whose exit open is missing exits at the last available adjusted close.
7. **Quintiles.** `pd.qcut` on the signal with ranks breaking ties (`rank(method="first")`), 5 bins.
   Long and short legs are equal-weighted inside each leg.
8. **IV inputs.** T = calendar DTE / 365. Dividend PV uses cash dividends with ex-date in (t, expiry]
   from `data/lse/dividends`, discounted at r. S − PV(div) must be positive, or the contract is dropped.
