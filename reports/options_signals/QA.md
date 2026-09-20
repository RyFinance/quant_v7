# Options-signal data and signal QA

Written 2026-09-19 while the option pull was running: 36 of the 100 names were on disk (AAPL … GS,
universe ranks 1–36). The development run (`research/run_pending_pulls.sh` → `evaluate dev`) had not
started. Its only earlier attempt, on 2026-09-18 at 19:54, refused to run because 78 names were
missing, so no result exists.

> **No returns were computed.** No stock return, portfolio return, Sharpe ratio, signal–return
> statistic or ranking of names by later performance was computed on any window. The QA used option
> prints, raw spot levels and volumes, dividends, and the *levels* of the three signals in the
> development window (up to 2019-12-31). The adjusted stock price files that `evaluate` uses for
> returns were read only for their trading-calendar dates, and around three spin-off dates to confirm
> that the adjusted series has no artificial gap. The backtest loop was timed on synthetic random
> prices. The vault was not called, and the running pull was not touched.

## Summary

| Question | Finding |
|---|---|
| Strikes line up with spot? | Yes, for all 36 names. Put–call-parity spot matches the raw close to 8–22 bp on the same day, against 47–156 bp a day off. No missed split or deliverable change. |
| Defects found | **Two, both fixed under [amendment 3](../../research/options_signals/PLAN_AMENDMENT_3.md), registered 2026-09-19T01:47:26-0700 before any result.** (1) The vault's dividend amounts are back-adjusted for GE (×4.79, 2015-12 → 2021-06) and T (×0.755, 2014 → 2022). This distorted GE's H2 and H3 badly. (2) `evaluate` made Tuesday 2019-12-31 a signal date, which breaks the ISO-week rule. |
| Signal coverage | O/S on ≥ 99.9% of development days, IV spread on ≥ 98.7%, skew on ≥ 91.1% (PFE; ≥ 93% of signal dates). No name is below 70%. |
| Plausibility | Median ATM IV runs from 14.5% (KO) to 43% (TSLA, MU); AAPL is 22.9%. 3.6% of IV solves fail, almost all prices below the σ = 1% value. 28 of 6.8 million solved IVs sit near a bound. After the fix, no spread or skew stays far from its normal range. |
| Runtime | About 1 minute for the full 100-name development run: ~35 s of signals on 6 workers, ~3 s of backtests. The peak is about 6.9 GB for the first ~15 s. That fits in 16 GB, but this Mac is already using swap (§6). |
| Open before the run | **DD** (not on disk yet, rank 47): yfinance's "DD" before 2019-06 is Dow Chemical, then DowDuPont, while OPRA's "DD" root was E. I. du Pont. Its strikes will not match spot for most of 2014–2019. A decision is needed (§7). |

## 1. Raw data

The 36 names hold 55.4 M daily contract rows, 15.8 M of them in 2014–2019 after the price
and volume filters. Every OSI root equals the ticker, and no (date, expiry, type, strike) is repeated.
Rows per year, in thousands (2014 starts on 2 June; 2026 ends on 16 September, the vault's last day):

| name | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AAPL | 140 | 197 | 168 | 161 | 184 | 207 | 377 | 319 | 293 | 266 | 268 | 314 | 269 |
| GOOGL | 68 | 133 | 143 | 164 | 234 | 216 | 253 | 290 | 360 | 251 | 206 | 292 | 331 |
| TSLA | 89 | 135 | 139 | 201 | 291 | 317 | 763 | 773 | 704 | 581 | 551 | 761 | 544 |
| AMZN | 78 | 174 | 240 | 304 | 582 | 519 | 652 | 633 | 588 | 315 | 262 | 330 | 273 |
| NFLX | 97 | 205 | 150 | 126 | 246 | 225 | 275 | 257 | 294 | 284 | 289 | 417 | 254 |
| BAC | 31 | 62 | 65 | 82 | 89 | 86 | 125 | 129 | 142 | 127 | 114 | 129 | 84 |
| MSFT | 42 | 82 | 84 | 103 | 139 | 142 | 222 | 263 | 275 | 303 | 326 | 364 | 370 |
| C | 35 | 65 | 73 | 82 | 89 | 82 | 117 | 115 | 111 | 96 | 99 | 127 | 96 |
| MU | 43 | 61 | 45 | 90 | 145 | 131 | 127 | 167 | 152 | 125 | 212 | 259 | 653 |
| GILD | 55 | 92 | 101 | 94 | 86 | 70 | 114 | 71 | 60 | 48 | 58 | 65 | 46 |
| VZ | 29 | 49 | 56 | 60 | 58 | 55 | 60 | 63 | 76 | 81 | 75 | 82 | 69 |
| JPM | 31 | 67 | 78 | 102 | 90 | 84 | 144 | 112 | 138 | 128 | 117 | 164 | 117 |
| GE | 25 | 48 | 48 | 58 | 68 | 56 | 77 | 79 | 75 | 75 | 82 | 92 | 81 |
| XOM | 29 | 76 | 75 | 68 | 86 | 80 | 124 | 113 | 149 | 122 | 115 | 110 | 98 |
| V | 28 | 62 | 64 | 64 | 85 | 83 | 130 | 121 | 113 | 88 | 98 | 135 | 103 |
| INTC | 37 | 66 | 60 | 71 | 98 | 91 | 132 | 132 | 127 | 133 | 180 | 200 | 257 |
| EBAY | 30 | 35 | 31 | 37 | 43 | 40 | 68 | 68 | 56 | 43 | 43 | 53 | 37 |
| CSCO | 24 | 47 | 48 | 54 | 75 | 81 | 98 | 79 | 78 | 69 | 70 | 82 | 90 |
| GM | 28 | 45 | 47 | 59 | 66 | 59 | 86 | 115 | 113 | 104 | 93 | 81 | 53 |
| CMCSA | 15 | 30 | 34 | 37 | 43 | 39 | 51 | 55 | 51 | 40 | 44 | 51 | 41 |
| WFC | 24 | 46 | 66 | 63 | 69 | 63 | 99 | 99 | 97 | 86 | 85 | 106 | 75 |
| IBM | 32 | 62 | 65 | 64 | 83 | 79 | 102 | 97 | 99 | 85 | 86 | 124 | 132 |
| ORCL | 25 | 44 | 38 | 46 | 52 | 47 | 62 | 85 | 81 | 102 | 113 | 220 | 230 |
| JNJ | 23 | 48 | 48 | 53 | 71 | 68 | 101 | 77 | 62 | 69 | 65 | 74 | 60 |
| QCOM | 28 | 63 | 61 | 63 | 65 | 96 | 111 | 130 | 145 | 126 | 125 | 116 | 128 |
| PFE | 22 | 43 | 45 | 38 | 46 | 55 | 99 | 118 | 107 | 92 | 104 | 95 | 62 |
| BA | 37 | 66 | 69 | 85 | 166 | 198 | 315 | 224 | 191 | 161 | 195 | 181 | 123 |
| DIS | 31 | 80 | 87 | 74 | 83 | 119 | 179 | 151 | 170 | 151 | 140 | 128 | 77 |
| PG | 20 | 50 | 51 | 47 | 64 | 62 | 67 | 67 | 69 | 57 | 50 | 62 | 59 |
| BIIB | 34 | 77 | 62 | 53 | 58 | 68 | 76 | 70 | 48 | 35 | 32 | 38 | 18 |
| MA | 32 | 53 | 47 | 47 | 64 | 83 | 129 | 127 | 124 | 97 | 87 | 109 | 94 |
| CVX | 30 | 71 | 72 | 52 | 63 | 57 | 114 | 98 | 117 | 86 | 87 | 91 | 74 |
| MRK | 20 | 39 | 37 | 43 | 51 | 67 | 77 | 84 | 77 | 70 | 71 | 100 | 66 |
| SLB | 32 | 65 | 59 | 54 | 66 | 58 | 54 | 54 | 73 | 62 | 65 | 63 | 50 |
| KO | 24 | 44 | 42 | 41 | 50 | 52 | 86 | 76 | 80 | 65 | 67 | 82 | 68 |
| GS | 24 | 50 | 67 | 83 | 96 | 78 | 105 | 139 | 139 | 127 | 132 | 222 | 236 |

Distinct expiries per day (median in the year), the share of option volume within ±20% of spot, and
alignment checks. "Odd days" are days whose volume-weighted median K/S is below 0.8 or above 1.25, or
with under 40% of volume within ±20% of spot. "Off-grid days" have more than 20% of volume on strikes
that are not multiples of $0.50, the mark of split-adjusted series. "Parity spot err" is the median
|ln(C − P + K·e^(−rT) + PV(div)) − ln(raw close)| over near-ATM pairs (2014–2019), on the same day and
on the nearer of ±1 day.

| name | expiries/day 2014 | 2019 | 2025 | vol ±20% of spot, 2014-19 | lowest year | odd days | off-grid days | days w/o options | parity spot err, same day / ±1 day (bp) | splits / spin-offs (yfinance) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AAPL | 13 | 16 | 21 | 0.93 | 0.92 | 5 | 80 | 1 | 8 / 76 | 2014-06-09 ×7, 2020-08-31 ×4 |
| GOOGL | 13 | 14 | 21 | 0.98 | 0.84 | 5 | 1 | 1 | 13 / 69 | 2022-07-18 ×20 |
| TSLA | 11 | 16 | 21 | 0.89 | 0.78 | 0 | 27 | 1 | 16 / 141 | 2020-08-31 ×5, 2022-08-25 ×3 |
| AMZN | 12 | 15 | 21 | 0.96 | 0.81 | 6 | 0 | 1 | 11 / 82 | 2022-06-06 ×20 |
| NFLX | 13 | 14 | 19 | 0.94 | 0.80 | 1 | 25 | 1 | 11 / 117 | 2015-07-15 ×7, 2025-11-17 ×10 |
| BAC | 13 | 15 | 20 | 0.92 | 0.87 | 5 | 0 | 1 | 12 / 82 | – |
| MSFT | 13 | 16 | 21 | 0.95 | 0.88 | 1 | 0 | 1 | 11 / 65 | – |
| C | 13 | 13 | 18 | 0.94 | 0.83 | 14 | 0 | 1 | 15 / 76 | – |
| MU | 11 | 13 | 20 | 0.89 | 0.76 | 10 | 0 | 1 | 15 / 154 | – |
| GILD | 12 | 13 | 17 | 0.94 | 0.86 | 5 | 0 | 1 | 16 / 86 | – |
| VZ | 13 | 14 | 16 | 0.96 | 0.93 | 5 | 0 | 1 | 14 / 55 | – |
| JPM | 13 | 13 | 20 | 0.95 | 0.90 | 5 | 0 | 1 | 13 / 64 | – |
| GE | 13 | 14 | 16 | 0.85 | 0.65 | 18 | 0 | 5 | 15 / 71 | 2019-02-26 ×1.04, 2021-08-02 ×0.125, 2023-01-04 ×1.281, 2024-04-02 ×1.253 |
| XOM | 12 | 15 | 19 | 0.96 | 0.84 | 6 | 0 | 1 | 14 / 64 | – |
| V | 11 | 14 | 19 | 0.96 | 0.89 | 3 | 20 | 1 | 13 / 64 | 2015-03-19 ×4 |
| INTC | 13 | 14 | 19 | 0.94 | 0.76 | 19 | 0 | 1 | 13 / 79 | – |
| EBAY | 12 | 13 | 15 | 0.97 | 0.92 | 7 | 0 | 2 | 16 / 70 | 2015-07-20 ×2.376 |
| CSCO | 13 | 14 | 17 | 0.95 | 0.86 | 4 | 0 | 1 | 13 / 66 | – |
| GM | 11 | 12 | 15 | 0.94 | 0.79 | 16 | 0 | 1 | 16 / 83 | – |
| CMCSA | 11 | 13 | 17 | 0.95 | 0.82 | 15 | 71 | 2 | 19 / 68 | 2017-02-21 ×2, 2026-01-05 ×1.067 |
| WFC | 12 | 14 | 19 | 0.95 | 0.81 | 12 | 0 | 1 | 16 / 65 | – |
| IBM | 12 | 14 | 17 | 0.94 | 0.83 | 5 | 0 | 2 | 12 / 60 | 2021-11-04 ×1.046 |
| ORCL | 12 | 13 | 20 | 0.97 | 0.72 | 5 | 0 | 1 | 15 / 60 | – |
| JNJ | 11 | 15 | 17 | 0.94 | 0.58 | 27 | 0 | 1 | 13 / 47 | – |
| QCOM | 12 | 13 | 18 | 0.92 | 0.76 | 15 | 0 | 1 | 16 / 75 | – |
| PFE | 13 | 12 | 18 | 0.96 | 0.84 | 1 | 0 | 2 | 16 / 56 | 2020-11-17 ×1.054 |
| BA | 12 | 15 | 18 | 0.93 | 0.83 | 3 | 0 | 1 | 13 / 80 | – |
| DIS | 12 | 16 | 18 | 0.94 | 0.84 | 1 | 0 | 1 | 12 / 61 | – |
| PG | 11 | 14 | 15 | 0.84 | 0.29 | 36 | 0 | 1 | 14 / 48 | – |
| BIIB | 12 | 13 | 14 | 0.92 | 0.76 | 46 | 0 | 4 | 22 / 94 | – |
| MA | 11 | 13 | 18 | 0.95 | 0.90 | 4 | 0 | 1 | 14 / 64 | – |
| CVX | 12 | 13 | 17 | 0.95 | 0.86 | 5 | 0 | 1 | 17 / 67 | – |
| MRK | 12 | 15 | 19 | 0.95 | 0.87 | 3 | 0 | 2 | 17 / 61 | 2021-06-03 ×1.048 |
| SLB | 11 | 13 | 16 | 0.93 | 0.79 | 25 | 0 | 1 | 20 / 88 | – |
| KO | 12 | 15 | 17 | 0.96 | 0.92 | 5 | 0 | 1 | 13 / 47 | – |
| GS | 11 | 13 | 20 | 0.97 | 0.77 | 7 | 0 | 1 | 13 / 77 | – |

Findings:

- **Strikes line up with spot everywhere.** The parity check puts the option dates on the same day as
  the raw close for every name, and the raw close on the right (unadjusted) scale.
- **Off-grid strikes appear only after recorded splits**: AAPL 2014 and 2020, NFLX 2015, V 2015,
  CMCSA 2017 (until the last pre-split LEAP expired in January 2019), and TSLA 2022. So the vault
  writes split-adjusted series under the plain root. The split rule drops them from H2 and H3; H1 counts
  them (amendment 2).
- **Odd days are isolated, genuine trading.** Most fall on the day before an ex-dividend date
  (deep-ITM call dividend capture: AAPL 2014-08-06, 2014-11-05, 2015-11-04, 2016-11-02; BAC 2014-09-02;
  JPM 2015-06-30; XOM 2014-08-08; INTC 2014-08-04). Others are conversion or box trades (GE,
  2015-11-06: 591k calls and 591k puts at the 38 strike with spot at 29.92), or strikes stranded by a
  large move (BIIB after March 2019, March 2020, late 2022). No name has a run of misaligned days that
  would suggest a missing split. The dividend-capture days do raise O/S in ex-dividend weeks. That is
  real volume, and H1 as registered counts it.
- **Yfinance records spin-offs as fractional "splits"** (EBAY 2015-07-20 ×2.376, GE 2019-02-26 ×1.04,
  IBM 2021 ×1.046, …). Raw spot is therefore the true traded price, and the split rule also drops
  pre-listed expiries after those spin-offs.
- **The vault has no option rows on a spin-off's effective day** (GE 2019-02-26, EBAY 2015-07-20,
  BIIB 2017-02-02, PFE 2020-11-17, MRK 2021-06-03, IBM 2021-11-04, CMCSA 2026-01-05). It also **omits the
  adjusted series after a spin-off**. After the EBAY/PayPal spin-off there are no EBAY rows with strikes
  of $45 or more. After BIIB/Bioverativ, whose spin-off yfinance did *not* record, pairs in pre-listed
  expiries price at the raw spot (median parity gap 0.01%), so only standard series are present. H2
  and H3 are safe as a result. H1 is not fully: EBAY's median daily O/S falls from 0.25–0.32 in the
  first half of 2015 to 0.03–0.10 in August 2015–2016. Some of that drop is real, and some is the
  missing adjusted volume. The data cannot separate the two, so this is noted, not changed.

## 2. Dividend input (defect 1)

The vault's cash dividends (`data/lse/dividends`) were compared, ex-date by ex-date, with the raw
amounts in the yfinance raw file (`Dividends × split_factor_after`), for all 91 dividend-paying names in
the universe. The other 9 (TSLA, AMZN, NFLX, BIIB, CMG, FSLR, ISRG, WDAY, CHTR) paid nothing in
2014–2019. In the development window the two sources agree to within 0.31% on every matched date,
except for these:

| Name | Ex-dates | Vault ÷ cash paid | Explanation |
|---|---|---:|---|
| GE | 2015-12-17 → 2021-06-25 | 4.7924 | back-adjusted by GE's later factors (1.04 × 0.125 × 1.281 × 1.253 = 0.2087); e.g. 2017-06-15 1.15019 vs $0.24 paid |
| T | 2014-07-08 → 2022-01-07 | 0.7553 | back-adjusted by the 2022 WarnerMedia factor 1.324 |
| COP (validation) | 2021-12-31, 2022-03-30 | 2.0 | variable-return dividends doubled |
| QCOM (validation) | 2021-03-03, 2022-03-02 | 1.07 | increase dated one quarter early |
| MGM (validation) | 2020-06 → 2022-12 | 0.83 | yfinance shows $0.0025 as $0.003 (rounding) |

For GE, PV(dividends) in 2016–2018 was about 3% of spot too high. That pushed call IVs up and put IVs
down. With the fix (the raw amount on each matching ex-date; unmatched vault rows are kept), GE is in
line with the other names, and nothing else moves materially. The table shows the 5-day rolling
signals before and after the fix, largest changes first:

| name | O/S unchanged | max abs change, spread (pp) | max abs change, skew (pp) | spread p95 before → after (%) | skew<0 before → after |
|---|---:|---:|---:|---:|---:|
| GE | yes | 38.289 | 32.007 | 23.4 → 3.9 | 0.268 → 0.027 |
| PFE | yes | 0.162 | 0.000 | 3.0 → 3.0 | 0.035 → 0.035 |
| PG | yes | 0.093 | 0.005 | 3.9 → 3.9 | 0.020 → 0.020 |
| INTC | yes | 0.018 | 0.015 | 2.8 → 2.8 | 0.030 → 0.030 |
| MRK | yes | 0.001 | 0.000 | 3.5 → 3.5 | 0.014 → 0.014 |
| IBM | yes | 0.001 | 0.000 | 3.2 → 3.2 | 0.027 → 0.027 |
| CMCSA | yes | 0.000 | 0.000 | 3.1 → 3.1 | 0.014 → 0.014 |
| AAPL | yes | 0.000 | 0.000 | 2.1 → 2.1 | 0.039 → 0.039 |

The other 28 names change by less than 0.001 pp, and O/S is unchanged for all 36 names. T is not on disk yet (rank 37). Its error is a quarter of each dividend, about 0.3% of
spot, and it is fixed the same way.

Vault rows with no yfinance counterpart are kept as registered: MSFT 2019-01-24 $0.123, QCOM 2018-02-15
$0.57 (a second copy of the 2018-02-27 dividend), HON 2016-09-15 $0.66 and 2018-09-17 $1.85 (around its
spin-offs), MDT 2018-09-27 $0.50 (probably genuine), the pre-2017 DD rows, and ex-date differences of
6–7 days for ACN 2015 and HPQ 2016. Each is at most about 1% of spot for at most one quarter.

## 3. Signal levels, development window (code as amended)

`signals.daily_signals(t, upto=2019-12-31)` → `rolling_signals`, from 2014-07-01. Coverage is the share of
trading days (and of ISO-week signal dates) with a value. Percentiles are of the 5-day rolling signal.
The ATM IV is the volume-weighted IV per day of contracts with |ln K/S| ≤ 0.05 and 10 ≤ DTE ≤ 60.

| name | days: os/spread/skew | signal dates | O/S p5/p50/p95 | spread p5/p50/p95 (%) | skew p5/p50/p95 (%) | skew<0 (days) | abs spread>5% | ATM IV median [p1, p99] |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AAPL | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.99/1.38/2.06 | -0.9/0.6/2.1 | 0.2/3.8/6.3 | 0.058 | 0.000 | 0.23 [0.15, 0.41] |
| GOOGL | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 1.09/1.64/2.52 | -2.0/0.3/2.2 | 0.7/3.9/6.4 | 0.097 | 0.005 | 0.21 [0.13, 0.39] |
| TSLA | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 1.46/2.02/2.79 | -6.0/-1.1/0.9 | 1.2/3.6/8.7 | 0.058 | 0.072 | 0.43 [0.30, 0.79] |
| AMZN | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 1.50/2.47/4.71 | -1.7/0.2/2.0 | -0.6/3.0/5.2 | 0.112 | 0.002 | 0.26 [0.15, 0.52] |
| NFLX | 1.000/0.996/0.996 | 1.000/0.993/0.993 | 0.79/1.44/3.48 | -1.5/0.2/1.9 | 0.1/2.4/5.0 | 0.114 | 0.002 | 0.36 [0.23, 0.81] |
| BAC | 1.000/1.000/0.960 | 1.000/1.000/0.969 | 0.19/0.32/0.47 | -0.8/0.6/2.1 | 0.7/3.0/6.2 | 0.076 | 0.001 | 0.24 [0.17, 0.40] |
| MSFT | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.19/0.38/0.83 | -1.2/0.7/2.7 | 1.2/4.0/6.8 | 0.061 | 0.003 | 0.20 [0.14, 0.38] |
| C | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.27/0.41/0.59 | -1.4/0.7/2.8 | 0.9/3.8/7.8 | 0.092 | 0.009 | 0.23 [0.16, 0.41] |
| MU | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.16/0.40/0.63 | -1.7/0.5/2.6 | -0.3/2.6/5.8 | 0.167 | 0.008 | 0.43 [0.30, 0.71] |
| GILD | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.24/0.41/0.64 | -1.2/1.0/3.4 | -0.0/3.3/6.9 | 0.157 | 0.007 | 0.25 [0.18, 0.42] |
| VZ | 1.000/1.000/0.995 | 1.000/1.000/1.000 | 0.13/0.20/0.43 | -1.2/0.8/3.7 | 0.4/4.3/7.8 | 0.099 | 0.014 | 0.16 [0.12, 0.26] |
| JPM | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.24/0.40/0.65 | -1.4/0.6/2.9 | 1.8/4.6/7.4 | 0.052 | 0.001 | 0.19 [0.14, 0.34] |
| GE | 0.999/0.999/0.967 | 1.000/1.000/0.993 | 0.11/0.18/0.35 | -1.6/1.1/3.9 | 0.6/3.8/8.3 | 0.092 | 0.017 | 0.20 [0.13, 0.65] |
| XOM | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.21/0.34/0.57 | -1.5/0.8/3.2 | 0.8/4.7/8.3 | 0.081 | 0.009 | 0.18 [0.11, 0.32] |
| V | 1.000/0.999/0.999 | 1.000/1.000/1.000 | 0.15/0.32/0.58 | -1.8/0.5/2.7 | 2.3/5.2/8.6 | 0.040 | 0.004 | 0.19 [0.14, 0.33] |
| INTC | 1.000/1.000/0.999 | 1.000/1.000/1.000 | 0.17/0.28/0.49 | -1.5/0.5/2.8 | 0.7/4.0/7.9 | 0.077 | 0.006 | 0.23 [0.15, 0.39] |
| EBAY | 0.999/0.995/0.988 | 1.000/0.997/0.997 | 0.05/0.15/0.43 | -1.9/0.5/3.0 | 0.4/3.3/8.0 | 0.133 | 0.010 | 0.25 [0.17, 0.48] |
| CSCO | 1.000/1.000/0.986 | 1.000/1.000/0.990 | 0.11/0.19/0.37 | -1.3/0.6/2.8 | 0.9/3.6/8.8 | 0.088 | 0.006 | 0.21 [0.13, 0.38] |
| GM | 1.000/1.000/0.999 | 1.000/1.000/1.000 | 0.17/0.31/0.60 | -1.5/0.9/3.4 | -0.1/3.5/7.8 | 0.155 | 0.003 | 0.24 [0.18, 0.41] |
| CMCSA | 1.000/0.987/0.957 | 1.000/0.986/0.972 | 0.07/0.15/0.34 | -2.5/0.3/3.1 | 1.3/5.2/10.0 | 0.084 | 0.015 | 0.21 [0.14, 0.33] |
| WFC | 1.000/1.000/0.995 | 1.000/1.000/1.000 | 0.13/0.21/0.38 | -1.0/1.0/3.3 | 1.2/4.2/8.5 | 0.088 | 0.005 | 0.20 [0.12, 0.35] |
| IBM | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.34/0.55/0.96 | -0.9/0.9/3.2 | 0.9/5.0/7.9 | 0.061 | 0.002 | 0.18 [0.13, 0.34] |
| ORCL | 1.000/1.000/0.997 | 1.000/1.000/1.000 | 0.08/0.14/0.28 | -1.4/0.8/3.1 | 1.1/4.1/8.0 | 0.076 | 0.005 | 0.19 [0.14, 0.37] |
| JNJ | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.15/0.26/0.48 | -1.4/0.8/3.4 | 2.4/5.5/9.7 | 0.038 | 0.009 | 0.15 [0.11, 0.28] |
| QCOM | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.17/0.32/0.68 | -1.7/0.8/3.7 | 0.3/4.0/8.4 | 0.125 | 0.021 | 0.26 [0.14, 0.45] |
| PFE | 1.000/1.000/0.911 | 1.000/1.000/0.931 | 0.08/0.14/0.30 | -1.3/0.9/3.0 | 0.3/3.6/7.9 | 0.101 | 0.001 | 0.17 [0.12, 0.28] |
| BA | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.34/0.61/1.82 | -1.2/0.8/3.2 | 1.2/4.3/7.2 | 0.049 | 0.004 | 0.22 [0.15, 0.39] |
| DIS | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.32/0.50/1.12 | -1.3/0.6/3.2 | 0.5/4.1/7.5 | 0.079 | 0.014 | 0.19 [0.13, 0.34] |
| PG | 1.000/1.000/0.991 | 1.000/1.000/0.997 | 0.11/0.20/0.62 | -1.4/0.9/3.9 | 1.2/4.4/8.0 | 0.072 | 0.022 | 0.15 [0.10, 0.25] |
| BIIB | 0.999/0.999/0.999 | 1.000/1.000/1.000 | 0.23/0.39/0.72 | -2.5/0.6/4.3 | -1.7/3.0/7.7 | 0.240 | 0.043 | 0.31 [0.21, 0.50] |
| MA | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.15/0.31/0.67 | -1.9/0.4/2.8 | 2.7/5.5/9.3 | 0.045 | 0.008 | 0.20 [0.14, 0.36] |
| CVX | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.22/0.35/0.59 | -1.6/1.1/4.0 | 0.3/4.5/8.4 | 0.108 | 0.014 | 0.19 [0.12, 0.40] |
| MRK | 1.000/1.000/0.996 | 1.000/1.000/1.000 | 0.10/0.17/0.37 | -1.3/1.0/3.5 | 1.1/4.4/8.6 | 0.088 | 0.004 | 0.18 [0.14, 0.30] |
| SLB | 1.000/1.000/1.000 | 1.000/1.000/1.000 | 0.13/0.23/0.40 | -2.1/0.7/3.4 | -0.1/3.5/8.0 | 0.182 | 0.016 | 0.25 [0.17, 0.44] |
| KO | 1.000/1.000/0.934 | 1.000/1.000/0.958 | 0.10/0.18/0.35 | -1.1/1.1/3.3 | 0.4/3.4/7.6 | 0.090 | 0.007 | 0.15 [0.10, 0.23] |
| GS | 1.000/1.000/0.999 | 1.000/1.000/1.000 | 0.40/0.88/1.41 | -1.6/0.6/2.5 | 1.7/4.3/7.2 | 0.048 | 0.003 | 0.22 [0.15, 0.38] |

- **Coverage** is at least 91% of days for every name and signal. The lowest is PFE's skew (79% in
  2014, 84% in 2017). PFE is a low-priced, low-volatility stock whose 5–20% OTM puts often trade below
  $0.10.
- **ATM IVs match known ranges**: KO, JNJ and PG 14.5–15%; the banks and large tech 19–26%; AAPL
  22.9%; NFLX 36%; TSLA and MU 43%. The 99th percentiles (e.g. TSLA 0.79, NFLX 0.81, GE 0.65 in 2018–19)
  fall on known stress periods.
- **IV spread** is centred slightly above zero (cross-name median of medians 0.69 pp). Only TSLA is
  negative (median −1.1 pp), which fits its hard-to-borrow, expensive puts in 2014–2019. A common
  offset does not affect a cross-sectional ranking. |spread| > 5% on at most 7.2% of days (TSLA).
- **Skew** is positive for every name (medians 2.4–5.5 pp). It is negative on 4–24% of days (JNJ lowest); the
  highest share is BIIB, where it is spread evenly across years, consistent with biotech upside-jump
  risk. Before the fix GE was the exception (negative on 27% of days); it is now 2.7%.
- **O/S** runs from 0.14 (PFE) to 2.5 (AMZN) at the median: high for the heavily optioned mega caps,
  as expected.

## 4. IV solver, parity filter and split rule

| name | contracts needing IV | IV fails | fail share | calls/puts | below σ=0.01 / above σ=3 | IV<0.02 / >2.9 | H2 pairs | parity drops | no IV on a leg | kept | pairs/day | split-rule rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AAPL | 321,117 | 12,896 | 0.040 | 0.054/0.027 | 12896 / 0 | 1 / 0 | 110,793 | 0 | 5,216 | 105,577 | 74.000 | 115,437 |
| GOOGL | 462,681 | 14,134 | 0.031 | 0.040/0.021 | 14134 / 0 | 0 / 0 | 120,560 | 1 | 9,326 | 111,234 | 71.000 | 0 |
| TSLA | 352,282 | 8,044 | 0.023 | 0.042/0.007 | 8044 / 0 | 0 / 0 | 110,603 | 1 | 2,533 | 108,069 | 75.000 | 0 |
| AMZN | 801,724 | 23,771 | 0.030 | 0.044/0.017 | 23771 / 0 | 0 / 0 | 236,160 | 0 | 14,146 | 222,014 | 125.000 | 0 |
| NFLX | 372,251 | 9,967 | 0.027 | 0.043/0.012 | 9967 / 0 | 0 / 0 | 116,770 | 2 | 4,322 | 112,447 | 79.000 | 68,219 |
| BAC | 120,690 | 7,981 | 0.066 | 0.079/0.050 | 7980 / 1 | 0 / 0 | 39,405 | 0 | 746 | 38,659 | 28.000 | 0 |
| MSFT | 246,224 | 11,519 | 0.047 | 0.061/0.032 | 11519 / 0 | 0 / 0 | 81,622 | 0 | 4,233 | 77,389 | 49.000 | 0 |
| C | 185,028 | 7,648 | 0.041 | 0.045/0.037 | 7648 / 0 | 0 / 0 | 56,327 | 0 | 3,173 | 53,154 | 37.000 | 0 |
| MU | 190,750 | 4,811 | 0.025 | 0.040/0.010 | 4809 / 2 | 0 / 1 | 62,819 | 5 | 1,172 | 61,644 | 41.000 | 0 |
| GILD | 214,554 | 6,357 | 0.030 | 0.031/0.028 | 6357 / 0 | 0 / 0 | 61,947 | 0 | 3,443 | 58,504 | 40.000 | 0 |
| VZ | 119,416 | 6,367 | 0.053 | 0.056/0.051 | 6367 / 0 | 1 / 0 | 37,691 | 0 | 1,994 | 35,697 | 24.000 | 0 |
| JPM | 199,966 | 8,320 | 0.042 | 0.048/0.035 | 8320 / 0 | 1 / 0 | 61,862 | 1 | 3,950 | 57,911 | 40.000 | 0 |
| GE | 81,634 | 4,556 | 0.056 | 0.053/0.059 | 4555 / 1 | 2 / 0 | 26,574 | 0 | 621 | 25,953 | 18.000 | 13,011 |
| XOM | 191,422 | 7,142 | 0.037 | 0.035/0.040 | 7142 / 0 | 3 / 0 | 56,162 | 0 | 3,602 | 52,560 | 37.000 | 0 |
| V | 170,518 | 6,344 | 0.037 | 0.049/0.024 | 6344 / 0 | 0 / 0 | 47,180 | 0 | 3,040 | 44,140 | 30.000 | 25,866 |
| INTC | 158,389 | 7,701 | 0.049 | 0.060/0.036 | 7701 / 0 | 0 / 0 | 53,201 | 1 | 2,211 | 50,989 | 35.000 | 0 |
| EBAY | 96,387 | 3,630 | 0.038 | 0.044/0.030 | 3630 / 0 | 1 / 0 | 28,047 | 1 | 1,079 | 26,967 | 18.000 | 6,132 |
| CSCO | 127,560 | 6,167 | 0.048 | 0.052/0.044 | 6167 / 0 | 2 / 0 | 40,268 | 1 | 1,438 | 38,829 | 24.000 | 0 |
| GM | 124,270 | 4,270 | 0.034 | 0.035/0.034 | 4270 / 0 | 0 / 0 | 37,465 | 0 | 1,463 | 36,002 | 24.000 | 0 |
| CMCSA | 82,529 | 3,394 | 0.041 | 0.047/0.035 | 3394 / 0 | 1 / 0 | 19,975 | 0 | 1,114 | 18,861 | 13.000 | 18,810 |
| WFC | 142,057 | 5,958 | 0.042 | 0.042/0.042 | 5957 / 1 | 1 / 0 | 41,143 | 0 | 2,192 | 38,951 | 27.000 | 0 |
| IBM | 165,951 | 4,662 | 0.028 | 0.025/0.031 | 4662 / 0 | 0 / 0 | 47,933 | 0 | 2,935 | 44,998 | 30.000 | 0 |
| ORCL | 105,536 | 4,354 | 0.041 | 0.038/0.045 | 4354 / 0 | 1 / 0 | 30,860 | 0 | 1,313 | 29,547 | 20.000 | 0 |
| JNJ | 142,814 | 5,404 | 0.038 | 0.042/0.033 | 5404 / 0 | 5 / 0 | 38,703 | 0 | 2,939 | 35,764 | 23.000 | 0 |
| QCOM | 159,843 | 5,369 | 0.034 | 0.036/0.031 | 5369 / 0 | 0 / 0 | 45,225 | 0 | 2,582 | 42,643 | 29.000 | 0 |
| PFE | 88,565 | 4,698 | 0.053 | 0.053/0.053 | 4698 / 0 | 5 / 0 | 26,245 | 0 | 1,095 | 25,150 | 16.000 | 0 |
| BA | 256,827 | 7,959 | 0.031 | 0.039/0.023 | 7959 / 0 | 0 / 0 | 75,414 | 0 | 4,692 | 70,722 | 40.000 | 0 |
| DIS | 211,866 | 7,388 | 0.035 | 0.043/0.027 | 7388 / 0 | 0 / 0 | 63,993 | 0 | 3,553 | 60,440 | 40.000 | 0 |
| PG | 135,766 | 6,108 | 0.045 | 0.041/0.049 | 6108 / 0 | 1 / 0 | 36,057 | 0 | 2,573 | 33,484 | 22.000 | 0 |
| BIIB | 150,460 | 3,941 | 0.026 | 0.034/0.019 | 3941 / 0 | 0 / 0 | 34,484 | 0 | 2,104 | 32,380 | 21.000 | 0 |
| MA | 156,142 | 5,567 | 0.036 | 0.048/0.023 | 5567 / 0 | 0 / 0 | 41,153 | 0 | 2,833 | 38,320 | 25.000 | 0 |
| CVX | 169,237 | 5,559 | 0.033 | 0.033/0.033 | 5558 / 1 | 1 / 0 | 45,895 | 1 | 3,281 | 42,614 | 29.000 | 0 |
| MRK | 113,641 | 4,181 | 0.037 | 0.038/0.035 | 4181 / 0 | 0 / 0 | 28,330 | 0 | 1,676 | 26,654 | 17.000 | 0 |
| SLB | 154,519 | 5,178 | 0.034 | 0.034/0.033 | 5178 / 0 | 0 / 0 | 40,587 | 0 | 2,531 | 38,056 | 26.000 | 0 |
| KO | 95,193 | 5,505 | 0.058 | 0.055/0.061 | 5505 / 0 | 1 / 0 | 28,447 | 0 | 1,106 | 27,341 | 19.000 | 0 |
| GS | 178,836 | 5,459 | 0.031 | 0.037/0.024 | 5459 / 0 | 0 / 0 | 51,379 | 0 | 3,378 | 48,001 | 33.000 | 0 |

- 7.05 M contracts needed an IV. **252,309 (3.6%) failed** (2.3–6.6% per name; BAC is highest).
  252,303 of the failures are prices *below* the σ = 1% Black–Scholes value: stale or sub-intrinsic
  last trades on ITM contracts. Only 6 were above the σ = 300% value. Among solved IVs, 27 are below
  0.02 and 1 is above 2.9, out of 6.8 M, so **nothing sticks to the bounds**.
- **The parity filter is almost inactive here**: 14 of 2.08 M H2 pairs dropped. The split rule has
  already removed split-adjusted series, and the vault holds no spin-off-adjusted series. 5.3% of
  pairs are dropped because one leg has no IV.
- **The split rule** drops rows only after recorded splits and spin-offs:

| name | event | ratio | rows dropped | of which 7≤DTE≤60 | share of rows, next 60 days | last row dropped | longest H2 gap (days) | longest H3 gap (days) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AAPL | 2014-06-09 | 7 | 115,437 | 27,919 | 0.85 | 2016-01-15 | 0 | 0 |
| NFLX | 2015-07-15 | 7 | 68,219 | 26,707 | 0.74 | 2017-01-20 | 6 | 6 |
| GE | 2019-02-26 | 1.04 | 13,011 | 3,375 | 0.67 | 2019-12-31 | 0 | 5 |
| V | 2015-03-19 | 4 | 25,866 | 6,901 | 0.69 | 2017-01-20 | 0 | 0 |
| EBAY | 2015-07-20 | 2.376 | 6,132 | 1,912 | 0.57 | 2017-01-20 | 4 | 5 |
| CMCSA | 2017-02-21 | 2 | 18,810 | 5,268 | 0.84 | 2019-01-18 | 11 | 21 |

Each event removes 57–85% of the next 60 days' rows. But weekly and newly listed expiries fill in
quickly, so the longest H2/H3 gap anywhere is 21 trading days (CMCSA skew, 2017-02-23 → 03-23). AAPL's 2014 gap
closes before the development window opens. That is well within the "at most about two months"
amendment 1.1 expected.

## 5. Evaluate: signal dates (defect 2)

`evaluate.run` found ISO-week maxima on a calendar cut at 2019-12-31. That made Tuesday 2019-12-31 a
288th signal date, but ISO week 2020-W01 ends on Friday 2020-01-03 (amendment 1.5). The new helper
`window_signal_dates` judges ISO weeks on the whole calendar. Development now has 287 dates; the last is
2019-12-27, held from the 2019-12-30 open to the 2020-01-06 open. In validation, the old code used
Thursday 2026-09-17 as a signal date. The fixed code's last date is 2026-09-11, whose registered exit
(the open after 2026-09-18) is beyond the data, so that week is not evaluated. Tests:
`tests/test_options_signals.py` gains two tests (12 pass; the cot and intraday suites, which import
from this package, also pass).

## 6. Runtime and memory

Measured per name with the official call path (a fresh process each, `rates=None` as `evaluate._one`
uses it). The time is the maximum of three runs. The peak RSS is taken just after `daily_signals`
returns.

| name | file rows (M) | rows ≤2019 kept (M) | daily_signals (s, max of 3) | peak RSS (MiB) | load / IV / H2 / H3 (s) |
|---|---:|---:|---:|---:|---:|
| AAPL | 3.16 | 0.93 | 6.00 | 1077.31 | 0.7/1.8/0.1/0.1 |
| GOOGL | 2.94 | 0.93 | 8.63 | 1019.69 | 0.6/3.0/0.2/0.2 |
| TSLA | 5.85 | 1.09 | 6.41 | 1306.53 | 1.8/2.9/0.2/0.2 |
| AMZN | 4.95 | 1.82 | 11.30 | 1608.14 | 1.0/5.4/0.3/0.2 |
| NFLX | 3.12 | 0.97 | 4.35 | 1160.17 | 0.5/2.5/0.2/0.1 |
| BAC | 1.27 | 0.34 | 2.22 | 580.69 | 0.2/0.7/0.0/0.0 |
| MSFT | 2.72 | 0.52 | 2.99 | 934.39 | 0.5/1.7/0.1/0.1 |
| C | 1.19 | 0.38 | 2.06 | 586.75 | 0.2/1.8/0.1/0.1 |
| MU | 2.21 | 0.45 | 3.60 | 830.78 | 0.4/1.2/0.1/0.1 |
| GILD | 0.96 | 0.45 | 2.37 | 570.20 | 0.2/1.2/0.1/0.1 |
| VZ | 0.81 | 0.26 | 2.16 | 467.66 | 0.2/1.4/0.1/0.1 |
| JPM | 1.37 | 0.40 | 2.90 | 628.91 | 0.2/1.4/0.1/0.1 |
| GE | 0.86 | 0.23 | 1.21 | 446.39 | 0.1/0.5/0.0/0.0 |
| XOM | 1.24 | 0.36 | 2.14 | 582.02 | 0.2/1.2/0.1/0.1 |
| V | 1.17 | 0.35 | 2.63 | 586.33 | 0.2/1.0/0.1/0.1 |
| INTC | 1.58 | 0.36 | 1.88 | 624.88 | 0.2/1.1/0.1/0.1 |
| EBAY | 0.58 | 0.19 | 1.15 | 361.44 | 0.1/0.6/0.0/0.0 |
| CSCO | 0.89 | 0.28 | 1.70 | 475.78 | 0.2/0.7/0.0/0.0 |
| GM | 0.95 | 0.27 | 1.60 | 485.31 | 0.2/0.8/0.1/0.0 |
| CMCSA | 0.53 | 0.18 | 1.17 | 351.17 | 0.1/0.5/0.0/0.0 |
| WFC | 0.98 | 0.29 | 1.97 | 493.33 | 0.3/1.1/0.1/0.0 |
| IBM | 1.11 | 0.34 | 3.53 | 572.52 | 0.2/1.7/0.1/0.1 |
| ORCL | 1.14 | 0.22 | 1.57 | 491.28 | 0.2/0.8/0.1/0.0 |
| JNJ | 0.82 | 0.28 | 1.73 | 475.06 | 0.2/0.9/0.1/0.0 |
| QCOM | 1.26 | 0.33 | 1.45 | 574.92 | 0.2/0.9/0.1/0.0 |
| PFE | 0.93 | 0.21 | 1.28 | 453.58 | 0.2/0.8/0.1/0.0 |
| BA | 2.01 | 0.57 | 2.76 | 794.70 | 0.3/1.3/0.1/0.1 |
| DIS | 1.47 | 0.42 | 2.63 | 628.47 | 0.4/1.8/0.1/0.1 |
| PG | 0.73 | 0.26 | 2.34 | 436.62 | 0.2/1.2/0.1/0.0 |
| BIIB | 0.67 | 0.34 | 1.36 | 447.31 | 0.1/0.8/0.1/0.0 |
| MA | 1.09 | 0.30 | 2.74 | 549.27 | 0.2/1.1/0.1/0.0 |
| CVX | 1.01 | 0.31 | 1.86 | 548.42 | 0.2/1.0/0.1/0.1 |
| MRK | 0.80 | 0.23 | 1.14 | 429.39 | 0.1/0.7/0.0/0.0 |
| SLB | 0.76 | 0.30 | 1.44 | 437.25 | 0.1/1.0/0.1/0.1 |
| KO | 0.78 | 0.21 | 1.49 | 391.27 | 0.2/1.0/0.1/0.1 |
| GS | 1.50 | 0.37 | 2.27 | 622.53 | 0.2/1.3/0.1/0.1 |

- Across the 36 names, time ≈ 0.38 s + 1.56 µs × file rows, and peak RSS ≈ 290 MiB + 0.23 KiB × file
  rows. Most of the time is the IV bisection. The 64 names still to come were sized from the vault
  catalog's trade counts (log-log correlation with file rows 0.96 on the 36 names); the largest
  expected is WMT at about 1.4 M rows.
- **The 100-name development run:** 196 s of `daily_signals` in total. Simulating
  `ProcessPoolExecutor(6).map` in universe order gives **~35 s**. Adding 100 stock files, the
  composite, and 8 backtests with block bootstraps (0.3 s each on synthetic 100-name data) gives
  **about 1 minute**. Even a 10× slowdown would be well inside 2 hours.
- **Memory:** the six largest files are also the first six tasks (AAPL, GOOGL, TSLA, AMZN, NFLX, BAC),
  so the peak is at the start: **~6.9 GB for ~15 s**, and under 4 GB after that. The Mac has
  16 GB, but when checked it already had 6.5 GB in the memory compressor and 4.8 of 6.1 GB of swap in
  use. Expect swapping for a few seconds, not a failure. If a worker were killed, the run would abort
  before writing any result and could simply be re-run.
- **Proposed, not applied:** a result-identical memory cut. `load_options` could push the `upto` cut
  into the parquet read (`filters=[("ts", "<", upto + 1 day)]`, UTC) and skip the unused `osi`
  column. For AMZN this gives an identical frame (checked with `assert_frame_equal`, less `osi`) and
  cuts the load peak from 1,106 to 683 MiB and the load time from 0.56 to 0.22 s. It is not needed at
  this runtime. If wanted, it should go in with a test of the UTC-midnight boundary. The zero-code
  option is to close memory-heavy apps before the run.

## 7. Names not yet on disk, and what to decide before the automated run

The pull resumed at 21:07 on 2026-09-18, re-exporting the six files over 2.5 M rows first. Its resume
test is `len(have) < 2,500,000`, which cost six export slots (~1.2 h) and will do so again on any
restart. At 5 exports an hour, the remaining 64 names finish around mid-afternoon on 2026-09-19, and
`evaluate dev` then starts immediately, with the amended code. The chain leaves no window to QA those
64 names. From the spot, dividend and catalog files, which exist for all 100:

1. **DD: identity mismatch (decision needed).** yfinance's DD raw close is Dow Chemical until 2017-08
   ($51.46 on 2014-06-30; DuPont was near $65), then DowDuPont (DWDP), then DuPont de Nemours from
   2019-06. The vault's DD options history starts in 2014 (catalog: "DuPont de Nemours, Inc.
   options"), and in 2014–2017 the OPRA root DD was E. I. du Pont. The vault's DD stock candles start
   only on 2019-06-03. For most of the development window, DD's option strikes will therefore not
   match its spot, and its O/S divides DuPont option volume by Dow share volume. The parity filter
   should remove most H2 pairs (the gap is about 25–40% of spot), but nothing registered protects H1 or
   H3. Options: (a) run as registered and accept one contaminated name out of 100; or (b) register,
   before DD's file arrives (about 04:00), a generic data-integrity rule. For example: a name-day gets
   no signal when the median parity-implied spot of near-ATM pairs differs from raw spot by more than
   5%. On the 36 names checked, that error is 8–22 bp, so the rule would bind only on identity or
   deliverable errors. Excluding DD outright would change the universe, so it is left to you.
2. **CHTR 2016-05-18** (Time Warner Cable merger; legacy holders received 0.9042 new shares).
   yfinance records no split, so the split rule will not act. The vault appears to omit adjusted
   series after such events (EBAY, BIIB), which would make this harmless. Check the parity-spot error
   when CHTR arrives; it is the last-but-two name pulled.
3. **COST special dividends** (2015-02-05 $5, 2017-05-08 $7) and **F** (2016-01-27, with a $0.25
   supplemental): OCC-protected contracts between the declaration and the ex-date would carry a ~3% PV
   error in H2/H3 for a week or two. Check when the files arrive.
4. **Handled by the split rule:** the splits and spin-offs in the development window for UNP, SBUX,
   MPC, NKE, ISRG, TJX, HPQ, MET, OXY, HON and DD (recorded by yfinance).
5. **QA gate (optional).** To QA all 100 names before the one-shot development run, the chained
   `evaluate dev` step would have to be held back. That means acting on the running
   `run_pending_pulls.sh`, which this QA did not touch. Then run, on every name:
   `research/options_signals/qa/data_qa.py`, `sig_qa.py` and `date_align.py`, which read local files
   only. Then launch `evaluate dev` once. Holding the run back before any result exists is consistent
   with the protocol.

## Files

- `research/options_signals/PLAN_AMENDMENT_3.md`, registered in `research/preregistrations.jsonl`.
- `research/options_signals/signals.py` (`raw_dividends`, `load_dividends`) and
  `research/options_signals/evaluate.py` (`window_signal_dates`): the two fixes.
- `tests/test_options_signals.py`: two new tests.
- `research/options_signals/qa/`: the QA scripts behind this report.
