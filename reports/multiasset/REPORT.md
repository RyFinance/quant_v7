# Multi-asset edge search: FAIL on the hold-out

**Question.** Can a book of several independent, literature-backed strategies outside US single
stocks reach the target of an excess Sharpe of 2 and more than 10% a year?

**Answer.** No. The pre-registered book scored an excess **Sharpe of −0.02** on its untouched
2018–2026 hold-out. Neither pass criterion was met, and neither was the target.

## Protocol (all hashes in `research/preregistrations.jsonl`)

| Step | File | Registered |
|---|---|---|
| Windows, 7 candidates, inclusion and combination rules | `research/multiasset/PLAN.md` | before any result |
| Round-2 candidates (7 more) | `PLAN_ADDENDUM_1.md` | before any round-2 result |
| Round-3 candidates (3 overnight/intraday) | `PLAN_ADDENDUM_2.md` | before any round-3 result |
| Hold-out test, frozen code hashes, pass criteria | `PREREGISTRATION_holdout.md` | before any hold-out result |

- **Development:** data through 2017-12-31, 17 sleeve specifications, every one logged in `dev_trials.jsonl`.
- **Hold-out:** 2018-01-01 → 2026-09-17, run once. Until the hold-out pre-registration was registered, the loaders refused every date after 2017.

## Results

| | Development Sharpe | **Hold-out Sharpe** | Hold-out return | Hold-out max drawdown |
|---|---:|---:|---:|---:|
| **Pre-registered book (5 sleeves)** | 0.57 | **−0.02** | 1.9% CAGR | −31% |
| Book without the stock sleeve | 0.67 | 0.41 | 6.8% CAGR | −24% |
| SPY | — | 0.67 | 14.6% CAGR | −34% |

| Sleeve (in the book) | Development | Hold-out |
|---|---:|---:|
| `vix_basis`: short VIX futures in contango | 0.98 | 0.29 (drawdown −86%) |
| `tsmom_broad`: time-series momentum, 58 instruments | 0.47 | 0.21 |
| `fx_carry`: G10 carry | 0.45 | 0.25 |
| `bond_carry`: global 10-year carry | 0.31 | 0.13 |
| `overnight_intraday_reversal` | 0.30 | −0.59 |

Of the 12 sleeves left out in development, the best hold-out Sharpes were 0.28 (bond value) and
0.27 (turn of the month). None was close to the level the target needs.

Book excess return by year: 2018 −21%, 2019 +6%, 2020 −8%, 2021 +11%, 2022 −0.3%, 2023 +5%,
2024 −11%, 2025 +7%, 2026 so far +9%.

## What was learned

1. **Standard risk premia were weak after 2018 in this implementation.** Carry, trend and bond
   premia that averaged a Sharpe near 0.4 through 2017 averaged about 0.2 afterwards. That matches
   the published record of post-2018 alternative-premia funds.
2. **Short volatility pays until it doesn't.** The VIX basis sleeve's Sharpe of 0.98 came from
   2011–2017. The hold-out holds February 2018 and March 2020, and the sleeve fell 86% at its raw
   size.
3. **The overnight/intraday "tug of war" is real but priced away.** In gross terms it was one of
   the strongest effects in the data: 20–60% a year on the decile spread in 2004–2009, at gross
   Sharpes of 4–9. By 2018–2026 the break-even was **0.7–1.1 bps per auction trade**, which is
   below any realistic cost of trading every open and close.
4. **Diversification did its job.** Sleeve correlations sat near zero. What it cannot fix is
   sleeves whose true Sharpe is about 0.2: combining ten of those still gives only about 0.6.

## Limits

- The stock sleeves use today's S&P 500 members (survivorship bias).
- Bond returns are built from yields, not traded prices.
- The author broadly knew how these strategy families fared after 2018. The parameters came from
  the literature and the selection was mechanical, and the hold-out result is poor anyway.

## Reproduce

```
PYTHONPATH=. .venv/bin/python -m data.pull_multiasset
PYTHONPATH=. .venv/bin/python -m data.pull_stock_ohlc
PYTHONPATH=. .venv/bin/python -m research.multiasset.evaluate     # development
PYTHONPATH=. .venv/bin/python -m research.multiasset.holdout      # the hold-out (already run once)
```
