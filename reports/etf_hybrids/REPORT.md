# ETF hybrids E1–E5 on sector and country ETFs: FAIL

Tester agent, 2026-09-19.

**Verdict: no candidate passes.**
- Development selected E1 (volatility-managed momentum, net Sharpe 0.66) and E2 (dual momentum,
  0.57). Both were above the equal-weight benchmark's 0.53.
- In validation (2015-01 → 2026-09, run once) E1 scored **0.38** and E2 **0.44**. The benchmark
  scored 0.55 and SPY 0.70.
- Both miss the 0.75 gate, the p < 0.01 gate and the paired test (p = 0.96 and 0.82). Neither beats
  the PEAD benchmark's 0.70, and neither beats simply holding the same ETFs at equal weight.

## Protocol

| Step | File | Registered |
|---|---|---|
| Plan: universe, signals, costs, windows, gates | `research/etf_hybrids/PLAN.md` (sha256 6dc99d7a…) | 2026-09-19T11:49:00-0700, before any strategy return |
| Validation unlock (E1, E2 only; code frozen) | `research/etf_hybrids/VALIDATION_UNLOCK.md` (sha256 aebbdb16…) | 2026-09-19T11:54:42-0700, after development, before validation |

- No rule, parameter, cost or gate was changed after any result.
- Code:
  - `research/etf_hybrids/pull.py` (data);
  - `signals.py` (point-in-time panel, signals, books);
  - `evaluate.py` (daily marking engine, statistics, lock).
- Tests: `tests/test_etf_hybrids.py`, 15 pass. They cover:
  - point-in-time eligibility, including the PLAN's first-eligible dates on real data;
  - truncation;
  - no look-ahead in any signal or book;
  - the 12-1 skip, same-month seasonality and 52-week-window definitions;
  - tercile, tie and fallback rules and the T-bill slot;
  - marking alignment, costs and stress;
  - E1 scaling;
  - the paired test;
  - the validation lock.
- The engine's gross NAV matched an independent period-by-period calculation exactly for B, E2 and E3.
- Outputs: `reports/etf_hybrids/{dev,validation}/results.json`, `daily.csv` and `weights.csv`, plus
  `dev/selection.json`.

**Scope caveat.** These are new signals on already-seen windows. The multiasset book used 11 of these 31
ETFs (SPY, EFA, EEM, EWJ, EWG, EWU, EWC, EWA, EWZ, EWY, EWT), with 12-1 cross-sectional momentum
and 12-month time-series momentum, over 2003–2026. The nine SPDR sectors, XLRE, XLC and nine of the
country funds had never been used in the project.

## Universe (survivorship-free in the sense that matters)

- 31 ETFs.
  - **Sector half:** XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY, then XLRE and XLC when they appear.
  - **Country half:** EWA, EWC, EWG, EWH, EWJ, EWU, EWS, EWL, EWP, EWQ, EWI, EWD, EWN, EWT, EWY, EWZ,
    EWW, EEM, EFA, SPY.
- An ETF enters at the first month-end with 13 months of history. Holdings per month:
  - development: 9 sectors and 19–20 country funds;
  - validation: 9–11 sectors and 20 country funds.
- None of the 31 was delisted. yfinance no longer serves the delisted Russia ETFs ERUS and RSX (HTTP
  404), and they were outside the fixed list in any case.
- Data: yfinance daily bars from each fund's inception (1993–2018), total-return adjusted. There are
  no missing sessions.
- 2003 liquidity was thin for EWN, EWD, EWI, EWL, EWP and EWQ (median $48k–$179k a day). The 8 bp
  cost is optimistic for 2003–05.

## Candidates

- Each book is long-only: the top tercile at equal weight within each half, with the two halves at
  50/50.
- It trades monthly at the next open.
- Base costs are 3 bp per side (sectors, SPY/EFA/EEM) and 8 bp (single-country); stress is ×3.
- Returns are daily marked, net, and in excess of T-bills.

The candidates:
- **E1** 12-1 momentum, with the whole book scaled by min(1, 12% / realized volatility). The
  volatility is from the unscaled book's last 126 daily returns (Barroso–Santa-Clara). The rest is
  in T-bills.
- **E2** top tercile by 12-month return. A slot goes to T-bills when that ETF's 12-month return does
  not beat T-bills (Antonacci).
- **E3** price / 52-week high (George–Hwang).
- **E4** ½ rank of 12-1 momentum + ½ rank of low 12-month volatility.
- **E5** average return in the same calendar month over the prior 10 years, needing at least 5
  years (Heston–Sadka).

References: B = equal weight of all eligible ETFs (the benchmark); R0 = plain 12-1 momentum (E1
unscaled); SPY.

## Development, 2003-01-02 → 2014-12-31 (all five)

| | E1 vol-managed mom | E2 dual mom | E3 52-wk high | E4 mom × low vol | E5 seasonality | B (EW) | R0 12-1 mom | SPY |
|---|---|---|---|---|---|---|---|---|
| **Net Sharpe** | **0.66** | **0.57** | 0.47 | 0.51 | 0.41 | 0.53 | 0.50 | 0.49 |
| 95% CI (63-day blocks) | [0.16, 1.20] | [0.10, 1.08] | [−0.03, 1.04] | [0.00, 1.12] | [−0.08, 0.99] | [0.02, 1.14] | [0.01, 1.09] | [0.02, 1.07] |
| Gross / stress Sharpe | 0.68 / 0.63 | 0.58 / 0.54 | 0.50 / 0.42 | 0.52 / 0.47 | 0.45 / 0.34 | 0.54 / 0.53 | 0.52 / 0.48 | 0.49 / 0.49 |
| Excess return / vol | 8.5% / 12.8% | 9.4% / 16.5% | 8.5% / 18.1% | 8.9% / 17.6% | 9.1% / 22.0% | 11.3% / 21.1% | 10.7% / 21.3% | 9.6% / 19.4% |
| Max drawdown (excess) | −27% | −27% | −54% | −55% | −59% | −58% | −57% | −56% |
| One-sided p (mean > 0) | 0.002 | 0.007 | 0.023 | 0.016 | 0.042 | 0.011 | 0.011 | 0.011 |
| Beta to SPY / alpha (HAC t) | 0.53 / +3.4% (1.6) | 0.55 / +4.1% (1.2) | 0.87 / +0.2% (0.1) | 0.86 / +0.7% (0.4) | 1.07 / −1.2% (−0.6) | 1.05 / +1.2% (0.8) | 1.01 / +1.0% (0.5) | 1.00 |
| Active vs B / tracking error | −2.8% / 12.3% | −1.9% / 15.0% | −2.8% / 5.8% | −2.4% / 5.6% | −2.2% / 4.3% | — | −0.5% / 5.8% | −1.7% / 5.5% |
| Paired Sharpe p vs B | 0.15 | 0.40 | 0.83 | 0.66 | 0.97 | — | 0.65 | 0.71 |
| Annual turnover / cost drag | 4.2 / 0.21% | 4.7 / 0.23% | 9.6 / 0.49% | 5.4 / 0.27% | 15.2 / 0.81% | 0.4 / 0.02% | 5.5 / 0.28% | — |
| Mean exposure | 0.71 | 0.84 (34 of 144 months with a T-bill slot) | 1 | 1 | 1 | 1 | 1 | 1 |
| Deflated Sharpe, 80 trials: candidate var / fixed 0.5 | 0.93 / 0.03 | 0.87 / 0.01 | 0.79 / 0.00 | 0.82 / 0.01 | 0.73 / 0.00 | | | |
| **Development gate** (≥ 0.5 and > B) | **pass** | **pass** | fail | fail (below B) | fail | | | |

Net excess return by year (development):

| Year | E1 | E2 | E3 | E4 | E5 | B | R0 | SPY |
|---|---|---|---|---|---|---|---|---|
| 2003 | +27% | +23% | +31% | +28% | +33% | +36% | +33% | +27% |
| 2004 | +14% | +18% | +16% | +16% | +12% | +18% | +18% | +10% |
| 2005 | +18% | +18% | +7% | +9% | +10% | +10% | +21% | +2% |
| 2006 | +7% | +11% | +11% | +15% | +11% | +17% | +11% | +10% |
| 2007 | +9% | +13% | +7% | +3% | +4% | +9% | +12% | +0% |
| 2008 | **−21%** | **−20%** | −35% | −37% | −44% | −41% | −40% | −38% |
| 2009 | +14% | +9% | +18% | +24% | +44% | +37% | +28% | +26% |
| 2010 | +8% | +18% | +10% | +16% | +15% | +15% | +17% | +15% |
| 2011 | −6% | −14% | −5% | −4% | −2% | −6% | −10% | +2% |
| 2012 | +9% | +10% | +15% | +13% | +11% | +17% | +13% | +16% |
| 2013 | +26% | +26% | +24% | +27% | +18% | +22% | +28% | +32% |
| 2014 | −1% | +0% | +2% | +2% | −1% | +4% | −1% | +14% |

## Validation, 2015-01-02 → 2026-09-18 (E1 and E2 only, run once)

| | E1 vol-managed mom | E2 dual mom | B (EW) | R0 12-1 mom | SPY |
|---|---|---|---|---|---|
| **Net Sharpe** | **0.38** | **0.44** | 0.55 | 0.54 | 0.70 |
| 95% CI / null kind at 0.70 | [−0.07, 0.92], vacuous | [−0.02, 0.96], vacuous | [0.08, 1.10] | [0.09, 1.04] | [0.26, 1.23] |
| Gross / stress Sharpe | 0.39 / 0.34 | 0.46 / 0.41 | 0.55 / 0.54 | 0.56 / 0.51 | 0.70 / 0.70 |
| Stress annual mean excess | +4.9% | +6.1% | +9.0% | +8.6% | +12.3% |
| Excess return / vol | 5.3% / 14.2% | 6.6% / 14.9% | 9.1% / 16.6% | 9.1% / 16.8% | 12.3% / 17.5% |
| One-sided p (needs < 0.01) | 0.036 | 0.024 | 0.009 | 0.006 | 0.000 |
| Paired Sharpe p vs B (needs < 0.01) | 0.96 | 0.82 | — | 0.51 | 0.08 |
| Active vs B / tracking error / IR | −3.7% / 6.5% / −0.57 | −2.5% / 7.4% / −0.34 | — | 0.0% / 5.0% / 0.00 | +3.2% / 6.0% / 0.53 |
| Beta to SPY / alpha (HAC t) | 0.72 / −3.5% (−1.9) | 0.74 / −2.5% (−1.3) | 0.89 / −1.8% (−1.0) | 0.89 / −1.8% (−1.0) | 1.00 |
| Beta to B | 0.79 | 0.80 | 1 | 0.97 | 0.99 |
| Max drawdown (excess / total) | −35% / −31% | −36% / −32% | −36% / −36% | −35% / −32% | −34% / −34% |
| Annual turnover / cost drag | 4.5 / 0.23% | 4.8 / 0.25% | 0.4 / 0.02% | 5.0 / 0.26% | — |
| Mean exposure | 0.82 (at the cap in 25% of months) | 0.90 (44 of 141 months with a T-bill slot) | 1 | 1 | 1 |
| Deflated Sharpe, 80 trials: candidate var / fixed 0.5 | 0.68 / 0.00 | 0.76 / 0.00 | | | |
| Correlation with PEAD (973 days, 2021-08 → 2025-06) | 0.61 | 0.58 | | | |
| Sharpe on the PEAD days (PEAD 0.70) | 0.29 | 0.36 | | | |
| **Passes validation** | **no** (Sharpe, p, paired) | **no** (Sharpe, p, paired) | | | |

Net excess return by year (validation):

| Year | E1 | E2 | B | R0 | SPY |
|---|---|---|---|---|---|
| 2015 | −4% | −6% | −5% | −3% | +1% |
| 2016 | +3% | −2% | +11% | +4% | +12% |
| 2017 | +18% | +19% | +23% | +18% | +22% |
| 2018 | −14% | −12% | −11% | −16% | −7% |
| 2019 | +16% | +9% | +22% | +20% | +28% |
| 2020 | **−8%** | +6% | +9% | +16% | +18% |
| 2021 | +15% | +19% | +20% | +20% | +29% |
| 2022 | −7% | −8% | −13% | −9% | −19% |
| 2023 | +7% | +5% | +13% | +8% | +20% |
| 2024 | +3% | +5% | +3% | +3% | +19% |
| 2025 | +11% | +18% | +20% | +18% | +12% |
| 2026 YTD | +17% | +20% | +11% | +21% | +10% |

## Reading

1. **The development edge was crash timing, not selection.**
   - Plain 12-1 momentum (R0) did not beat equal weight in either window: 0.50 against 0.53, then
     0.54 against 0.55, with a validation information ratio of 0.00.
   - What lifted E1 and E2 in development was holding T-bills into 2008. They lost about 20% that
     year against −41% for B.
   - One crash in a 12-year window is thin evidence. The development paired tests were already
     unconvincing (p = 0.15 and 0.40).
2. **In 2015–2026 the same timing cost money.** The declines were short and V-shaped:
   - After the March 2020 crash, E1's volatility scaling cut exposure to about 0.30 from April to
     August, and it was still 0.65 in November. It missed the rebound: −8% for the year against +9%
     for B.
   - E2's 12-month filter moved a third to two thirds of the book into T-bills near the lows of
     early 2016 and late 2018. It missed both rebounds: 2016 −2% against +11% for B, and 2019 +9%
     against +22%.
   - Cutting exposure lowered volatility (14–15% against 17%), but it lowered returns more.
3. **No selection signal added value in development.** Every fully invested hybrid (E3, E4, E5)
   trailed B, with active returns of −2% to −3% a year and paired p of 0.66–0.97. E5 also turned
   over 15 times a year.
4. **Against the project's bar**, a buy-and-hold SPY position (0.70) beat everything here in
   validation. The candidates correlate about 0.6 with the PEAD benchmark, because both are long
   US-heavy equity, so they would add little diversification to PEAD even at equal Sharpe.
5. **The intervals are vacuous.** They cannot rule out a Sharpe of 0.70, but they also include zero.
   The deflated Sharpe with the project-wide dispersion (0.5) is 0.00. This is a failure under the
   registered rules, not proof that the effects are zero.

## Limits

- The validation years had already been seen for momentum on 11 of the funds (multiasset book). The
  author also knew in broad terms how US and international markets behaved after 2015. The result
  is negative anyway.
- The base cost is optimistic for 2003–05 for the thin country funds. That makes development easier
  and does not rescue validation. Stress costs barely move the Sharpes (−0.03 to −0.07).
- The prices are yfinance adjusted data. The French RF ends on 2026-07-31, and the last value is
  carried forward to 2026-09-18.
- E3 holds for one month, where George–Hwang used 6 months. E5 has only 5–10 same-month observations
  per fund.

## Reproduce

```
PYTHONPATH=. .venv/bin/python -m research.etf_hybrids.pull          # yfinance pull (re-pull may re-adjust prices)
PYTHONPATH=. .venv/bin/python -m pytest tests/test_etf_hybrids.py -q
PYTHONPATH=. .venv/bin/python -m research.etf_hybrids.evaluate dev
PYTHONPATH=. .venv/bin/python -m research.etf_hybrids.evaluate validation   # already run once; refuses to overwrite
```
