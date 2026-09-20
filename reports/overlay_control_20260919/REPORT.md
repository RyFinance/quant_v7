# Overlay control — what the same overlays do to a fund you can just buy

`reports/overlay_control_20260919/` · plan registered `research/overlay_control/PLAN.md` (sha256 `cf3ef76c…`) before any result was computed · run with `PYTHONPATH=. .venv/bin/python -m research.overlay_control.run`

Five overlays — buy-and-hold, own 200-session trend gate, SPY 200-session trend gate, 126-session constant-volatility scaling, and gate x vol — applied to six buyable ETFs under the frozen project accounting. 30 variants, exactly the 30 registered. No stock panel was used and `research/momentum_lab/core.py` was not modified (its `stats` and `WINDOWS` are imported).

## The number the other agents need

**Sharpe improvement each overlay delivers on a buyable fund, as a delta from buy-and-hold on the same fund and window, base costs.** Positive means the overlay helped.

### 2011..2018

| underlying | O1 own 200d gate | O2 SPY 200d gate | O3 const-vol 20% | O4 gate x const-vol |
|---|---|---|---|---|
| SPMO (B&H 0.65) | **+0.33** | **-0.01** | **+0.01** | **+0.33** |
| MTUM (B&H 0.82) | **+0.06** | **-0.03** | **+0.00** | **+0.06** |
| SPY (B&H 0.78) | **-0.03** | **-0.03** | **-0.02** | **-0.06** |
| RSP (B&H 0.69) | **+0.07** | **-0.02** | **-0.02** | **+0.06** |
| QQQ (B&H 0.89) | **-0.10** | **+0.02** | **-0.02** | **-0.10** |
| IWM (B&H 0.51) | **+0.01** | **+0.03** | **-0.02** | **+0.01** |
| *median across the six funds* | +0.04 | -0.02 | -0.02 | +0.03 |

All 24 cells this window: median **-0.006**, mean +0.024, 12 of 24 positive, best +0.334, worst -0.098.

### 2019..2026

| underlying | O1 own 200d gate | O2 SPY 200d gate | O3 const-vol 20% | O4 gate x const-vol |
|---|---|---|---|---|
| SPMO (B&H 0.89) | **-0.07** | **-0.32** | **-0.10** | **-0.13** |
| MTUM (B&H 0.67) | **-0.12** | **-0.33** | **-0.09** | **-0.21** |
| SPY (B&H 0.78) | **-0.20** | **-0.20** | **-0.07** | **-0.24** |
| RSP (B&H 0.60) | **-0.22** | **-0.20** | **-0.09** | **-0.23** |
| QQQ (B&H 0.87) | **-0.02** | **-0.29** | **-0.10** | **-0.17** |
| IWM (B&H 0.46) | **-0.09** | **-0.27** | **-0.12** | **-0.15** |
| *median across the six funds* | -0.11 | -0.28 | -0.10 | -0.19 |

All 24 cells this window: median **-0.156**, mean -0.169, 0 of 24 positive, best -0.023, worst -0.333.

### 2011..2026

| underlying | O1 own 200d gate | O2 SPY 200d gate | O3 const-vol 20% | O4 gate x const-vol |
|---|---|---|---|---|
| SPMO (B&H 0.84) | **+0.01** | **-0.25** | **-0.08** | **-0.03** |
| MTUM (B&H 0.70) | **-0.05** | **-0.22** | **-0.05** | **-0.09** |
| SPY (B&H 0.77) | **-0.11** | **-0.11** | **-0.05** | **-0.14** |
| RSP (B&H 0.64) | **-0.05** | **-0.10** | **-0.05** | **-0.07** |
| QQQ (B&H 0.86) | **-0.05** | **-0.13** | **-0.06** | **-0.12** |
| IWM (B&H 0.48) | **-0.03** | **-0.12** | **-0.07** | **-0.06** |
| *median across the six funds* | -0.05 | -0.13 | -0.05 | -0.08 |

All 24 cells this window: median **-0.068**, mean -0.086, 1 of 24 positive, best +0.013, worst -0.251.

### Stress costs (15bps/side) — same deltas

| window | median ΔSharpe | positive cells | best | worst |
|---|---|---|---|---|
| 2011..2018 | -0.008 | 12 of 24 | +0.330 | -0.107 |
| 2019..2026 | -0.168 | 0 of 24 | -0.030 | -0.347 |
| 2011..2026 | -0.074 | 1 of 24 | +0.004 | -0.264 |

## Verdict

**Not one of the 24 overlay × underlying combinations improves Sharpe in both halves.** 0 of 24 are positive in both 2011–2018 and 2019–2026, at base costs and at stress costs alike.

- **2011–2018:** 12 of 24 positive, median −0.006. A coin flip.
- **2019–2026:** **0 of 24 positive.** Every overlay on every fund lost Sharpe, best case −0.02, worst −0.33, median −0.16.
- **2011–2026:** 1 of 24 positive (SPMO × O1, +0.013, and that one is an artefact of SPMO's short history — see the caveat below).

By the project's own rule — a result only counts if it survives in both halves — **every overlay is a null on buyable funds.** That is the control number. If a stock-book overlay raises the stock book's Sharpe, it is not because the overlay is a good idea in general; on a fund you can just buy, the identical overlay costs Sharpe in the second half without exception.

## How to use this against a stock-book claim

If a stock-book overlay reports a Sharpe gain ΔS, the honest comparison is ΔS minus the number in the matrix above for the same overlay and window. The relevant row is usually **SPY** (the market-state comparison) or **SPMO** (the thing anyone can actually buy instead of the book):

| overlay | ΔSharpe on SPY, 2019–2026 | ΔSharpe on SPMO, 2019–2026 | ΔSharpe on SPY, 2011–2026 |
|---|---|---|---|
| O1 own 200d gate | -0.20 | -0.07 | -0.11 |
| O2 SPY 200d gate | -0.20 | -0.32 | -0.11 |
| O3 const-vol 20% | -0.07 | -0.10 | -0.05 |
| O4 gate x const-vol | -0.24 | -0.13 | -0.14 |

All of these are negative, so an overlay that raises the stock book's Sharpe is doing something to the *stock book* that it does not do to a fund — it is not market timing, because market timing, measured here, subtracts Sharpe. Two consequences:

1. A stock-book gain is not automatically discounted by this control; there is nothing to discount by, because the control effect is negative. But it does mean the gain has to be explained by something specific to the 20-name book (turnover reduction, crash exposure of the selected names, concentration), not by "trend gates work".
2. The relevant bar is still absolute: **SPMO buy-and-hold is 0.84 over 2011–2026 and 0.89 in 2019–2026.** Any gated or vol-scaled stock book has to clear that, not merely clear the ungated stock book. The best overlaid ETF variant in this entire matrix is SPMO × O1 at 0.86 full-record — which is SPMO buy-and-hold plus 0.01, on a short sample, with turnover.

## Which overlays help, which hurt

| overlay | 2011–2018 mean Δ | 2019–2026 mean Δ | 2011–2026 mean Δ | survives both halves anywhere? |
|---|---|---|---|---|
| **O1** own 200d gate | +0.059 | -0.120 | -0.046 | no |
| **O2** SPY 200d gate | -0.006 | -0.270 | -0.154 | no |
| **O3** const-vol 20% | -0.010 | -0.096 | -0.060 | no |
| **O4** gate x const-vol | +0.052 | -0.189 | -0.084 | no |

- **O1 own 200-day gate** — the least bad. Helps a little in the first half on 4 of 6 funds, hurts on all 6 in the second. Its only large positive (SPMO +0.33 in 2011–2018) rests on 2.4 years of data, not 8.
- **O2 SPY 200-day gate** — the one the stock-book agent is testing, and **the worst of the four.** Mean −0.15 over the full record, −0.27 in the second half. Applying SPY's market state to something that is not SPY throws away the fund's own information and adds nothing: on SPY itself O1 and O2 are the same series (a useful internal check — they agree to the last digit), and on the five funds that are not SPY, O2 is worse than O1 in the second half on 4 of 5 (SPMO −0.25, QQQ −0.27, MTUM −0.21, IWM −0.18; RSP is the exception at +0.01).
- **O3 constant-vol scaling** — nearly inert in the first half (mean −0.01, it barely binds: average exposure 0.96–1.00) and mildly negative in the second (mean −0.10), where it binds more because realised vol was higher. It does not lose much because it does not do much.
- **O4 gate × vol** — stacks O1's second-half damage on O3's. Worst full-record mean of the three own-fund overlays on 4 of 6 funds.

## Full matrix — underlying × overlay

One NAV path per (underlying, overlay) from the effective start, sliced by window, exactly as `Lab.run` does. CAGR / excess Sharpe / annualised vol / max drawdown / average exposure / annual turnover. Costs charged on the traded amount at each monthly decision, plus entry and a final liquidation.

Effective starts (first session at which the fund's own 200-session MA, its own 126-session vol and SPY's 200-session MA are all defined): **SPMO** 2016-07-27, **MTUM** 2014-01-31, **SPY** 2011-01-03, **RSP** 2011-01-03, **QQQ** 2011-01-03, **IWM** 2011-01-03.

### Base costs — 5bps per side

**2011..2018**

| underlying | overlay | CAGR | Sharpe | ΔSharpe | vol | max DD | avg exp | ann turnover |
|---|---|---|---|---|---|---|---|---|
| SPMO | O0 buy and hold | 10.75% | 0.65 |  | 15.7% | -23.4% | 1.00 | 41% |
| SPMO | O1 own 200d gate | 14.41% | 0.98 | +0.33 | 13.3% | -15.2% | 0.93 | 82% |
| SPMO | O2 SPY 200d gate | 10.07% | 0.64 | -0.01 | 14.9% | -24.5% | 0.97 | 123% |
| SPMO | O3 const-vol 20% | 10.84% | 0.66 | +0.01 | 15.6% | -23.1% | 1.00 | 42% |
| SPMO | O4 gate x const-vol | 14.41% | 0.98 | +0.33 | 13.3% | -15.2% | 0.93 | 82% |
| MTUM | O0 buy and hold | 12.68% | 0.82 |  | 15.2% | -22.1% | 1.00 | 20% |
| MTUM | O1 own 200d gate | 12.32% | 0.88 | +0.06 | 13.5% | -13.6% | 0.90 | 122% |
| MTUM | O2 SPY 200d gate | 11.17% | 0.79 | -0.03 | 13.8% | -23.1% | 0.90 | 142% |
| MTUM | O3 const-vol 20% | 12.68% | 0.82 | +0.00 | 15.2% | -22.1% | 1.00 | 21% |
| MTUM | O4 gate x const-vol | 12.32% | 0.88 | +0.06 | 13.5% | -13.6% | 0.90 | 122% |
| SPY | O0 buy and hold | 11.21% | 0.78 |  | 14.5% | -19.3% | 1.00 | 13% |
| SPY | O1 own 200d gate | 9.46% | 0.75 | -0.03 | 12.6% | -20.7% | 0.90 | 113% |
| SPY | O2 SPY 200d gate | 9.46% | 0.75 | -0.03 | 12.6% | -20.7% | 0.90 | 113% |
| SPY | O3 const-vol 20% | 10.58% | 0.76 | -0.02 | 14.1% | -19.3% | 0.98 | 21% |
| SPY | O4 gate x const-vol | 9.02% | 0.72 | -0.06 | 12.6% | -20.7% | 0.89 | 112% |
| RSP | O0 buy and hold | 10.31% | 0.69 |  | 15.3% | -22.9% | 1.00 | 13% |
| RSP | O1 own 200d gate | 9.71% | 0.76 | +0.07 | 12.7% | -20.5% | 0.86 | 75% |
| RSP | O2 SPY 200d gate | 8.74% | 0.67 | -0.02 | 13.2% | -21.8% | 0.90 | 113% |
| RSP | O3 const-vol 20% | 9.59% | 0.67 | -0.02 | 14.6% | -20.5% | 0.98 | 23% |
| RSP | O4 gate x const-vol | 9.44% | 0.75 | +0.06 | 12.6% | -20.5% | 0.85 | 75% |
| QQQ | O0 buy and hold | 15.17% | 0.89 |  | 17.1% | -22.8% | 1.00 | 13% |
| QQQ | O1 own 200d gate | 12.04% | 0.79 | -0.10 | 15.4% | -24.3% | 0.90 | 150% |
| QQQ | O2 SPY 200d gate | 13.99% | 0.91 | +0.02 | 15.2% | -22.5% | 0.90 | 113% |
| QQQ | O3 const-vol 20% | 14.44% | 0.87 | -0.02 | 16.6% | -22.3% | 0.98 | 26% |
| QQQ | O4 gate x const-vol | 11.86% | 0.79 | -0.10 | 15.1% | -24.0% | 0.88 | 143% |
| IWM | O0 buy and hold | 8.52% | 0.51 |  | 18.8% | -28.9% | 1.00 | 13% |
| IWM | O1 own 200d gate | 7.45% | 0.52 | +0.01 | 15.4% | -24.5% | 0.82 | 125% |
| IWM | O2 SPY 200d gate | 8.09% | 0.54 | +0.03 | 16.2% | -28.0% | 0.90 | 113% |
| IWM | O3 const-vol 20% | 7.71% | 0.49 | -0.02 | 17.4% | -26.8% | 0.96 | 29% |
| IWM | O4 gate x const-vol | 7.34% | 0.52 | +0.01 | 15.1% | -24.5% | 0.81 | 127% |

**2019..2026**

| underlying | overlay | CAGR | Sharpe | ΔSharpe | vol | max DD | avg exp | ann turnover |
|---|---|---|---|---|---|---|---|---|
| SPMO | O0 buy and hold | 22.37% | 0.89 |  | 22.3% | -30.9% | 1.00 | 13% |
| SPMO | O1 own 200d gate | 15.95% | 0.82 | -0.07 | 16.2% | -15.6% | 0.80 | 182% |
| SPMO | O2 SPY 200d gate | 11.47% | 0.58 | -0.32 | 16.4% | -25.2% | 0.79 | 247% |
| SPMO | O3 const-vol 20% | 18.33% | 0.79 | -0.10 | 20.5% | -30.9% | 0.90 | 52% |
| SPMO | O4 gate x const-vol | 13.71% | 0.76 | -0.13 | 14.7% | -15.1% | 0.73 | 186% |
| MTUM | O0 buy and hold | 16.93% | 0.67 |  | 23.3% | -34.1% | 1.00 | 13% |
| MTUM | O1 own 200d gate | 11.37% | 0.55 | -0.12 | 17.4% | -24.1% | 0.77 | 208% |
| MTUM | O2 SPY 200d gate | 7.41% | 0.34 | -0.33 | 17.9% | -34.9% | 0.79 | 247% |
| MTUM | O3 const-vol 20% | 13.46% | 0.58 | -0.09 | 20.9% | -34.1% | 0.88 | 55% |
| MTUM | O4 gate x const-vol | 9.04% | 0.46 | -0.21 | 15.4% | -24.5% | 0.69 | 211% |
| SPY | O0 buy and hold | 17.29% | 0.78 |  | 19.3% | -33.7% | 1.00 | 13% |
| SPY | O1 own 200d gate | 9.71% | 0.58 | -0.20 | 12.6% | -24.3% | 0.79 | 247% |
| SPY | O2 SPY 200d gate | 9.71% | 0.58 | -0.20 | 12.6% | -24.3% | 0.79 | 247% |
| SPY | O3 const-vol 20% | 14.76% | 0.71 | -0.07 | 17.8% | -33.7% | 0.93 | 40% |
| SPY | O4 gate x const-vol | 8.76% | 0.54 | -0.24 | 11.8% | -22.7% | 0.75 | 242% |
| RSP | O0 buy and hold | 13.56% | 0.60 |  | 19.8% | -39.0% | 1.00 | 13% |
| RSP | O1 own 200d gate | 6.88% | 0.39 | -0.22 | 11.9% | -25.3% | 0.76 | 234% |
| RSP | O2 SPY 200d gate | 7.29% | 0.40 | -0.20 | 12.8% | -24.0% | 0.79 | 247% |
| RSP | O3 const-vol 20% | 10.93% | 0.52 | -0.09 | 17.9% | -39.0% | 0.94 | 37% |
| RSP | O4 gate x const-vol | 6.47% | 0.37 | -0.23 | 11.3% | -24.2% | 0.73 | 229% |
| QQQ | O0 buy and hold | 22.84% | 0.87 |  | 23.9% | -35.1% | 1.00 | 13% |
| QQQ | O1 own 200d gate | 18.62% | 0.84 | -0.02 | 19.2% | -28.6% | 0.81 | 130% |
| QQQ | O2 SPY 200d gate | 11.84% | 0.57 | -0.29 | 17.4% | -33.1% | 0.79 | 247% |
| QQQ | O3 const-vol 20% | 17.77% | 0.76 | -0.10 | 20.7% | -28.6% | 0.86 | 56% |
| QQQ | O4 gate x const-vol | 14.45% | 0.70 | -0.17 | 17.6% | -28.6% | 0.72 | 132% |
| IWM | O0 buy and hold | 11.72% | 0.46 |  | 24.8% | -41.1% | 1.00 | 13% |
| IWM | O1 own 200d gate | 7.61% | 0.37 | -0.09 | 15.8% | -24.4% | 0.63 | 260% |
| IWM | O2 SPY 200d gate | 4.65% | 0.19 | -0.27 | 18.3% | -38.4% | 0.79 | 247% |
| IWM | O3 const-vol 20% | 8.06% | 0.34 | -0.12 | 21.5% | -41.1% | 0.87 | 59% |
| IWM | O4 gate x const-vol | 6.39% | 0.31 | -0.15 | 14.3% | -21.3% | 0.57 | 252% |

**2011..2026**

| underlying | overlay | CAGR | Sharpe | ΔSharpe | vol | max DD | avg exp | ann turnover |
|---|---|---|---|---|---|---|---|---|
| SPMO | O0 buy and hold | 19.47% | 0.84 |  | 20.9% | -30.9% | 1.00 | 20% |
| SPMO | O1 own 200d gate | 15.58% | 0.86 | +0.01 | 15.6% | -15.6% | 0.83 | 158% |
| SPMO | O2 SPY 200d gate | 11.13% | 0.59 | -0.25 | 16.0% | -25.2% | 0.84 | 218% |
| SPMO | O3 const-vol 20% | 16.49% | 0.76 | -0.08 | 19.4% | -30.9% | 0.93 | 50% |
| SPMO | O4 gate x const-vol | 13.88% | 0.81 | -0.03 | 14.4% | -15.2% | 0.78 | 161% |
| MTUM | O0 buy and hold | 15.25% | 0.70 |  | 20.6% | -34.1% | 1.00 | 16% |
| MTUM | O1 own 200d gate | 11.74% | 0.65 | -0.05 | 16.0% | -24.1% | 0.82 | 175% |
| MTUM | O2 SPY 200d gate | 8.86% | 0.48 | -0.22 | 16.4% | -34.9% | 0.84 | 206% |
| MTUM | O3 const-vol 20% | 13.16% | 0.65 | -0.05 | 18.9% | -34.1% | 0.93 | 42% |
| MTUM | O4 gate x const-vol | 10.30% | 0.61 | -0.09 | 14.7% | -24.5% | 0.77 | 176% |
| SPY | O0 buy and hold | 14.15% | 0.77 |  | 17.0% | -33.7% | 1.00 | 13% |
| SPY | O1 own 200d gate | 9.58% | 0.67 | -0.11 | 12.6% | -24.3% | 0.85 | 179% |
| SPY | O2 SPY 200d gate | 9.58% | 0.67 | -0.11 | 12.6% | -24.3% | 0.85 | 179% |
| SPY | O3 const-vol 20% | 12.61% | 0.73 | -0.05 | 16.0% | -33.7% | 0.96 | 30% |
| SPY | O4 gate x const-vol | 8.89% | 0.63 | -0.14 | 12.2% | -22.7% | 0.82 | 176% |
| RSP | O0 buy and hold | 11.89% | 0.64 |  | 17.7% | -39.0% | 1.00 | 13% |
| RSP | O1 own 200d gate | 8.31% | 0.58 | -0.05 | 12.3% | -25.3% | 0.81 | 153% |
| RSP | O2 SPY 200d gate | 8.03% | 0.54 | -0.10 | 13.0% | -24.0% | 0.85 | 179% |
| RSP | O3 const-vol 20% | 10.24% | 0.58 | -0.05 | 16.3% | -39.0% | 0.96 | 30% |
| RSP | O4 gate x const-vol | 7.97% | 0.57 | -0.07 | 12.0% | -24.2% | 0.79 | 151% |
| QQQ | O0 buy and hold | 18.87% | 0.86 |  | 20.7% | -35.1% | 1.00 | 13% |
| QQQ | O1 own 200d gate | 15.22% | 0.81 | -0.05 | 17.4% | -28.6% | 0.85 | 140% |
| QQQ | O2 SPY 200d gate | 12.93% | 0.73 | -0.13 | 16.3% | -33.1% | 0.85 | 179% |
| QQQ | O3 const-vol 20% | 16.06% | 0.81 | -0.06 | 18.7% | -28.6% | 0.92 | 41% |
| QQQ | O4 gate x const-vol | 13.12% | 0.74 | -0.12 | 16.4% | -28.6% | 0.80 | 138% |
| IWM | O0 buy and hold | 10.08% | 0.48 |  | 22.0% | -41.1% | 1.00 | 13% |
| IWM | O1 own 200d gate | 7.53% | 0.44 | -0.03 | 15.6% | -26.1% | 0.73 | 191% |
| IWM | O2 SPY 200d gate | 6.39% | 0.36 | -0.12 | 17.3% | -38.4% | 0.85 | 179% |
| IWM | O3 const-vol 20% | 7.88% | 0.41 | -0.07 | 19.5% | -41.3% | 0.92 | 44% |
| IWM | O4 gate x const-vol | 6.88% | 0.42 | -0.06 | 14.7% | -25.1% | 0.69 | 188% |

### Stress costs — 15bps per side

**2011..2018**

| underlying | overlay | CAGR | Sharpe | ΔSharpe | vol | max DD | avg exp | ann turnover |
|---|---|---|---|---|---|---|---|---|
| SPMO | O0 buy and hold | 10.70% | 0.65 |  | 15.7% | -23.4% | 1.00 | 41% |
| SPMO | O1 own 200d gate | 14.32% | 0.98 | +0.33 | 13.3% | -15.2% | 0.93 | 82% |
| SPMO | O2 SPY 200d gate | 9.94% | 0.63 | -0.02 | 14.9% | -24.7% | 0.97 | 123% |
| SPMO | O3 const-vol 20% | 10.80% | 0.66 | +0.01 | 15.6% | -23.1% | 1.00 | 42% |
| SPMO | O4 gate x const-vol | 14.32% | 0.98 | +0.33 | 13.3% | -15.2% | 0.93 | 82% |
| MTUM | O0 buy and hold | 12.65% | 0.82 |  | 15.2% | -22.1% | 1.00 | 20% |
| MTUM | O1 own 200d gate | 12.18% | 0.87 | +0.06 | 13.5% | -13.6% | 0.90 | 122% |
| MTUM | O2 SPY 200d gate | 11.01% | 0.78 | -0.04 | 13.8% | -23.3% | 0.90 | 142% |
| MTUM | O3 const-vol 20% | 12.66% | 0.82 | +0.00 | 15.2% | -22.1% | 1.00 | 21% |
| MTUM | O4 gate x const-vol | 12.18% | 0.87 | +0.06 | 13.5% | -13.6% | 0.90 | 122% |
| SPY | O0 buy and hold | 11.19% | 0.78 |  | 14.5% | -19.3% | 1.00 | 13% |
| SPY | O1 own 200d gate | 9.33% | 0.74 | -0.04 | 12.6% | -20.9% | 0.90 | 113% |
| SPY | O2 SPY 200d gate | 9.33% | 0.74 | -0.04 | 12.6% | -20.9% | 0.90 | 113% |
| SPY | O3 const-vol 20% | 10.56% | 0.75 | -0.02 | 14.1% | -19.3% | 0.98 | 21% |
| SPY | O4 gate x const-vol | 8.90% | 0.71 | -0.07 | 12.6% | -20.9% | 0.89 | 112% |
| RSP | O0 buy and hold | 10.30% | 0.69 |  | 15.3% | -22.9% | 1.00 | 13% |
| RSP | O1 own 200d gate | 9.63% | 0.76 | +0.07 | 12.7% | -20.5% | 0.86 | 75% |
| RSP | O2 SPY 200d gate | 8.62% | 0.66 | -0.03 | 13.2% | -21.9% | 0.90 | 113% |
| RSP | O3 const-vol 20% | 9.56% | 0.67 | -0.02 | 14.6% | -20.5% | 0.98 | 23% |
| RSP | O4 gate x const-vol | 9.36% | 0.74 | +0.05 | 12.6% | -20.5% | 0.85 | 75% |
| QQQ | O0 buy and hold | 15.16% | 0.89 |  | 17.1% | -22.8% | 1.00 | 13% |
| QQQ | O1 own 200d gate | 11.87% | 0.78 | -0.11 | 15.4% | -24.8% | 0.90 | 150% |
| QQQ | O2 SPY 200d gate | 13.86% | 0.90 | +0.02 | 15.2% | -22.7% | 0.90 | 113% |
| QQQ | O3 const-vol 20% | 14.41% | 0.87 | -0.02 | 16.6% | -22.3% | 0.98 | 26% |
| QQQ | O4 gate x const-vol | 11.70% | 0.78 | -0.11 | 15.1% | -24.4% | 0.88 | 143% |
| IWM | O0 buy and hold | 8.51% | 0.51 |  | 18.8% | -28.9% | 1.00 | 13% |
| IWM | O1 own 200d gate | 7.32% | 0.51 | +0.00 | 15.4% | -24.5% | 0.82 | 125% |
| IWM | O2 SPY 200d gate | 7.97% | 0.53 | +0.02 | 16.2% | -28.1% | 0.90 | 113% |
| IWM | O3 const-vol 20% | 7.68% | 0.49 | -0.02 | 17.4% | -26.8% | 0.96 | 29% |
| IWM | O4 gate x const-vol | 7.21% | 0.51 | +0.00 | 15.1% | -24.5% | 0.81 | 126% |

**2019..2026**

| underlying | overlay | CAGR | Sharpe | ΔSharpe | vol | max DD | avg exp | ann turnover |
|---|---|---|---|---|---|---|---|---|
| SPMO | O0 buy and hold | 22.35% | 0.89 |  | 22.3% | -30.9% | 1.00 | 13% |
| SPMO | O1 own 200d gate | 15.74% | 0.81 | -0.08 | 16.2% | -15.6% | 0.80 | 182% |
| SPMO | O2 SPY 200d gate | 11.19% | 0.56 | -0.33 | 16.4% | -25.6% | 0.79 | 247% |
| SPMO | O3 const-vol 20% | 18.27% | 0.79 | -0.11 | 20.5% | -30.9% | 0.90 | 52% |
| SPMO | O4 gate x const-vol | 13.50% | 0.75 | -0.15 | 14.7% | -15.6% | 0.73 | 185% |
| MTUM | O0 buy and hold | 16.91% | 0.67 |  | 23.3% | -34.1% | 1.00 | 13% |
| MTUM | O1 own 200d gate | 11.14% | 0.54 | -0.13 | 17.4% | -24.7% | 0.77 | 208% |
| MTUM | O2 SPY 200d gate | 7.15% | 0.32 | -0.35 | 17.9% | -35.2% | 0.79 | 247% |
| MTUM | O3 const-vol 20% | 13.40% | 0.58 | -0.09 | 20.9% | -34.1% | 0.88 | 55% |
| MTUM | O4 gate x const-vol | 8.81% | 0.45 | -0.22 | 15.4% | -25.1% | 0.69 | 211% |
| SPY | O0 buy and hold | 17.28% | 0.78 |  | 19.3% | -33.7% | 1.00 | 13% |
| SPY | O1 own 200d gate | 9.44% | 0.56 | -0.22 | 12.6% | -24.8% | 0.79 | 247% |
| SPY | O2 SPY 200d gate | 9.44% | 0.56 | -0.22 | 12.6% | -24.8% | 0.79 | 247% |
| SPY | O3 const-vol 20% | 14.72% | 0.71 | -0.08 | 17.8% | -33.7% | 0.93 | 40% |
| SPY | O4 gate x const-vol | 8.50% | 0.52 | -0.26 | 11.8% | -23.2% | 0.75 | 242% |
| RSP | O0 buy and hold | 13.54% | 0.60 |  | 19.8% | -39.0% | 1.00 | 13% |
| RSP | O1 own 200d gate | 6.63% | 0.37 | -0.23 | 11.9% | -25.9% | 0.76 | 234% |
| RSP | O2 SPY 200d gate | 7.03% | 0.38 | -0.22 | 12.8% | -24.5% | 0.79 | 247% |
| RSP | O3 const-vol 20% | 10.89% | 0.51 | -0.09 | 17.9% | -39.0% | 0.94 | 37% |
| RSP | O4 gate x const-vol | 6.23% | 0.35 | -0.25 | 11.3% | -24.7% | 0.73 | 229% |
| QQQ | O0 buy and hold | 22.82% | 0.87 |  | 23.9% | -35.1% | 1.00 | 13% |
| QQQ | O1 own 200d gate | 18.47% | 0.84 | -0.03 | 19.2% | -28.6% | 0.81 | 130% |
| QQQ | O2 SPY 200d gate | 11.56% | 0.56 | -0.31 | 17.4% | -33.4% | 0.79 | 247% |
| QQQ | O3 const-vol 20% | 17.70% | 0.76 | -0.11 | 20.7% | -28.6% | 0.86 | 56% |
| QQQ | O4 gate x const-vol | 14.30% | 0.69 | -0.17 | 17.6% | -28.6% | 0.72 | 132% |
| IWM | O0 buy and hold | 11.70% | 0.46 |  | 24.8% | -41.1% | 1.00 | 13% |
| IWM | O1 own 200d gate | 7.33% | 0.35 | -0.11 | 15.8% | -25.0% | 0.63 | 260% |
| IWM | O2 SPY 200d gate | 4.39% | 0.18 | -0.28 | 18.3% | -38.7% | 0.79 | 247% |
| IWM | O3 const-vol 20% | 7.99% | 0.34 | -0.12 | 21.5% | -41.1% | 0.87 | 59% |
| IWM | O4 gate x const-vol | 6.13% | 0.30 | -0.16 | 14.3% | -21.7% | 0.57 | 252% |

**2011..2026**

| underlying | overlay | CAGR | Sharpe | ΔSharpe | vol | max DD | avg exp | ann turnover |
|---|---|---|---|---|---|---|---|---|
| SPMO | O0 buy and hold | 19.45% | 0.84 |  | 20.9% | -30.9% | 1.00 | 20% |
| SPMO | O1 own 200d gate | 15.40% | 0.85 | +0.00 | 15.6% | -15.6% | 0.83 | 158% |
| SPMO | O2 SPY 200d gate | 10.89% | 0.58 | -0.26 | 16.0% | -25.6% | 0.84 | 217% |
| SPMO | O3 const-vol 20% | 16.43% | 0.76 | -0.08 | 19.4% | -30.9% | 0.93 | 50% |
| SPMO | O4 gate x const-vol | 13.70% | 0.80 | -0.04 | 14.4% | -15.6% | 0.78 | 161% |
| MTUM | O0 buy and hold | 15.23% | 0.70 |  | 20.6% | -34.1% | 1.00 | 16% |
| MTUM | O1 own 200d gate | 11.54% | 0.64 | -0.06 | 16.0% | -24.7% | 0.82 | 175% |
| MTUM | O2 SPY 200d gate | 8.64% | 0.47 | -0.23 | 16.4% | -35.2% | 0.84 | 206% |
| MTUM | O3 const-vol 20% | 13.11% | 0.65 | -0.05 | 18.9% | -34.1% | 0.93 | 42% |
| MTUM | O4 gate x const-vol | 10.11% | 0.60 | -0.10 | 14.7% | -25.1% | 0.77 | 176% |
| SPY | O0 buy and hold | 14.14% | 0.77 |  | 17.0% | -33.7% | 1.00 | 13% |
| SPY | O1 own 200d gate | 9.38% | 0.65 | -0.12 | 12.6% | -24.8% | 0.85 | 179% |
| SPY | O2 SPY 200d gate | 9.38% | 0.65 | -0.12 | 12.6% | -24.8% | 0.85 | 179% |
| SPY | O3 const-vol 20% | 12.58% | 0.72 | -0.05 | 16.0% | -33.7% | 0.96 | 30% |
| SPY | O4 gate x const-vol | 8.70% | 0.62 | -0.15 | 12.2% | -23.2% | 0.82 | 176% |
| RSP | O0 buy and hold | 11.88% | 0.64 |  | 17.7% | -39.0% | 1.00 | 13% |
| RSP | O1 own 200d gate | 8.15% | 0.57 | -0.06 | 12.3% | -25.9% | 0.81 | 153% |
| RSP | O2 SPY 200d gate | 7.84% | 0.53 | -0.11 | 13.0% | -24.5% | 0.85 | 179% |
| RSP | O3 const-vol 20% | 10.21% | 0.58 | -0.05 | 16.3% | -39.0% | 0.96 | 30% |
| RSP | O4 gate x const-vol | 7.81% | 0.56 | -0.08 | 12.0% | -24.7% | 0.79 | 151% |
| QQQ | O0 buy and hold | 18.86% | 0.86 |  | 20.7% | -35.1% | 1.00 | 13% |
| QQQ | O1 own 200d gate | 15.06% | 0.81 | -0.06 | 17.4% | -28.6% | 0.85 | 140% |
| QQQ | O2 SPY 200d gate | 12.73% | 0.72 | -0.14 | 16.3% | -33.4% | 0.85 | 179% |
| QQQ | O3 const-vol 20% | 16.01% | 0.81 | -0.06 | 18.7% | -28.6% | 0.92 | 41% |
| QQQ | O4 gate x const-vol | 12.97% | 0.73 | -0.13 | 16.4% | -28.6% | 0.80 | 138% |
| IWM | O0 buy and hold | 10.06% | 0.48 |  | 22.0% | -41.1% | 1.00 | 13% |
| IWM | O1 own 200d gate | 7.32% | 0.43 | -0.04 | 15.6% | -26.7% | 0.73 | 191% |
| IWM | O2 SPY 200d gate | 6.20% | 0.34 | -0.13 | 17.3% | -38.7% | 0.85 | 179% |
| IWM | O3 const-vol 20% | 7.83% | 0.41 | -0.07 | 19.5% | -41.3% | 0.92 | 44% |
| IWM | O4 gate x const-vol | 6.68% | 0.41 | -0.07 | 14.7% | -25.7% | 0.69 | 188% |


## How much of each effect is just dilution

For every variant, a **static blend** of the same underlying with T-bills, held at the overlay's own average exposure for that window, monthly-rebalanced under the same cost model. An overlay that matches its own dilution control has done nothing; one that is *below* its dilution control has done harm.

The blunt fact first: **a static blend keeps the underlying's Sharpe almost exactly.** Across all 180 dilution cells the control's Sharpe never differs from buy-and-hold's by more than **0.009** — diluting with T-bills scales return and volatility together and leaves the ratio alone. So the entire question is whether the overlay's *timing* beat holding the same average exposure all the time. Mostly it did not, and the Sharpe delta versus the dilution control is therefore all but identical to the Sharpe delta versus buy-and-hold reported above.

| underlying | overlay | window | avg exp | overlay CAGR | dilution CAGR | timing ΔCAGR | overlay Sharpe | dilution Sharpe | timing ΔSharpe |
|---|---|---|---|---|---|---|---|---|---|
| SPMO | O1 | 2011..2018 | 0.93 | 14.41% | 10.09% | +4.32% | 0.98 | 0.65 | +0.34 |
| SPMO | O1 | 2019..2026 | 0.80 | 15.95% | 18.61% | -2.65% | 0.82 | 0.89 | -0.07 |
| SPMO | O1 | 2011..2026 | 0.83 | 15.58% | 16.73% | -1.14% | 0.86 | 0.84 | +0.01 |
| SPMO | O2 | 2011..2018 | 0.97 | 10.07% | 10.42% | -0.34% | 0.64 | 0.65 | -0.01 |
| SPMO | O2 | 2019..2026 | 0.79 | 11.47% | 18.41% | -6.94% | 0.58 | 0.89 | -0.31 |
| SPMO | O2 | 2011..2026 | 0.84 | 11.13% | 16.74% | -5.61% | 0.59 | 0.84 | -0.25 |
| SPMO | O3 | 2011..2018 | 1.00 | 10.84% | 10.72% | +0.13% | 0.66 | 0.65 | +0.01 |
| SPMO | O3 | 2019..2026 | 0.90 | 18.33% | 20.47% | -2.14% | 0.79 | 0.89 | -0.10 |
| SPMO | O3 | 2011..2026 | 0.93 | 16.49% | 18.23% | -1.74% | 0.76 | 0.84 | -0.08 |
| SPMO | O4 | 2011..2018 | 0.93 | 14.41% | 10.09% | +4.32% | 0.98 | 0.65 | +0.34 |
| SPMO | O4 | 2019..2026 | 0.73 | 13.71% | 17.22% | -3.51% | 0.76 | 0.89 | -0.13 |
| SPMO | O4 | 2011..2026 | 0.78 | 13.88% | 15.82% | -1.94% | 0.81 | 0.84 | -0.03 |
| MTUM | O1 | 2011..2018 | 0.90 | 12.32% | 11.45% | +0.86% | 0.88 | 0.82 | +0.07 |
| MTUM | O1 | 2019..2026 | 0.77 | 11.37% | 13.92% | -2.55% | 0.55 | 0.66 | -0.12 |
| MTUM | O1 | 2011..2026 | 0.82 | 11.74% | 12.99% | -1.26% | 0.65 | 0.70 | -0.04 |
| MTUM | O2 | 2011..2018 | 0.90 | 11.17% | 11.46% | -0.29% | 0.79 | 0.82 | -0.02 |
| MTUM | O2 | 2019..2026 | 0.79 | 7.41% | 14.21% | -6.80% | 0.34 | 0.67 | -0.33 |
| MTUM | O2 | 2011..2026 | 0.84 | 8.86% | 13.17% | -4.31% | 0.48 | 0.70 | -0.21 |
| MTUM | O3 | 2011..2018 | 1.00 | 12.68% | 12.66% | +0.02% | 0.82 | 0.82 | +0.00 |
| MTUM | O3 | 2019..2026 | 0.88 | 13.46% | 15.40% | -1.93% | 0.58 | 0.67 | -0.09 |
| MTUM | O3 | 2011..2026 | 0.93 | 13.16% | 14.36% | -1.20% | 0.65 | 0.70 | -0.05 |
| MTUM | O4 | 2011..2018 | 0.90 | 12.32% | 11.45% | +0.86% | 0.88 | 0.82 | +0.07 |
| MTUM | O4 | 2019..2026 | 0.69 | 9.04% | 12.83% | -3.79% | 0.46 | 0.66 | -0.20 |
| MTUM | O4 | 2011..2026 | 0.77 | 10.30% | 12.37% | -2.06% | 0.61 | 0.70 | -0.09 |
| SPY | O1 | 2011..2018 | 0.90 | 9.46% | 10.10% | -0.64% | 0.75 | 0.77 | -0.03 |
| SPY | O1 | 2019..2026 | 0.79 | 9.71% | 14.40% | -4.69% | 0.58 | 0.78 | -0.20 |
| SPY | O1 | 2011..2026 | 0.85 | 9.58% | 12.27% | -2.69% | 0.67 | 0.77 | -0.11 |
| SPY | O2 | 2011..2018 | 0.90 | 9.46% | 10.10% | -0.64% | 0.75 | 0.77 | -0.03 |
| SPY | O2 | 2019..2026 | 0.79 | 9.71% | 14.40% | -4.69% | 0.58 | 0.78 | -0.20 |
| SPY | O2 | 2011..2026 | 0.85 | 9.58% | 12.27% | -2.69% | 0.67 | 0.77 | -0.11 |
| SPY | O3 | 2011..2018 | 0.98 | 10.58% | 11.02% | -0.44% | 0.76 | 0.78 | -0.02 |
| SPY | O3 | 2019..2026 | 0.93 | 14.76% | 16.32% | -1.56% | 0.71 | 0.78 | -0.07 |
| SPY | O3 | 2011..2026 | 0.96 | 12.61% | 13.63% | -1.02% | 0.73 | 0.77 | -0.05 |
| SPY | O4 | 2011..2018 | 0.89 | 9.02% | 10.01% | -1.00% | 0.72 | 0.77 | -0.06 |
| SPY | O4 | 2019..2026 | 0.75 | 8.76% | 13.81% | -5.04% | 0.54 | 0.78 | -0.24 |
| SPY | O4 | 2011..2026 | 0.82 | 8.89% | 11.97% | -3.07% | 0.63 | 0.77 | -0.14 |
| RSP | O1 | 2011..2018 | 0.86 | 9.71% | 8.93% | +0.79% | 0.76 | 0.69 | +0.08 |
| RSP | O1 | 2019..2026 | 0.76 | 6.88% | 11.20% | -4.32% | 0.39 | 0.60 | -0.22 |
| RSP | O1 | 2011..2026 | 0.81 | 8.31% | 10.05% | -1.73% | 0.58 | 0.64 | -0.05 |
| RSP | O2 | 2011..2018 | 0.90 | 8.74% | 9.31% | -0.57% | 0.67 | 0.69 | -0.02 |
| RSP | O2 | 2019..2026 | 0.79 | 7.29% | 11.54% | -4.25% | 0.40 | 0.60 | -0.20 |
| RSP | O2 | 2011..2026 | 0.85 | 8.03% | 10.41% | -2.38% | 0.54 | 0.64 | -0.10 |
| RSP | O3 | 2011..2018 | 0.98 | 9.59% | 10.07% | -0.48% | 0.67 | 0.69 | -0.02 |
| RSP | O3 | 2019..2026 | 0.94 | 10.93% | 12.94% | -2.01% | 0.52 | 0.60 | -0.09 |
| RSP | O3 | 2011..2026 | 0.96 | 10.24% | 11.47% | -1.23% | 0.58 | 0.64 | -0.05 |
| RSP | O4 | 2011..2018 | 0.85 | 9.44% | 8.85% | +0.59% | 0.75 | 0.69 | +0.06 |
| RSP | O4 | 2019..2026 | 0.73 | 6.47% | 10.90% | -4.43% | 0.37 | 0.60 | -0.24 |
| RSP | O4 | 2011..2026 | 0.79 | 7.97% | 9.87% | -1.89% | 0.57 | 0.64 | -0.07 |
| QQQ | O1 | 2011..2018 | 0.90 | 12.04% | 13.65% | -1.61% | 0.79 | 0.88 | -0.10 |
| QQQ | O1 | 2019..2026 | 0.81 | 18.62% | 19.06% | -0.43% | 0.84 | 0.86 | -0.02 |
| QQQ | O1 | 2011..2026 | 0.85 | 15.22% | 16.37% | -1.14% | 0.81 | 0.86 | -0.05 |
| QQQ | O2 | 2011..2018 | 0.90 | 13.99% | 13.64% | +0.35% | 0.91 | 0.88 | +0.02 |
| QQQ | O2 | 2019..2026 | 0.79 | 11.84% | 18.82% | -6.98% | 0.57 | 0.86 | -0.29 |
| QQQ | O2 | 2011..2026 | 0.85 | 12.93% | 16.27% | -3.34% | 0.73 | 0.86 | -0.13 |
| QQQ | O3 | 2011..2018 | 0.98 | 14.44% | 14.83% | -0.40% | 0.87 | 0.89 | -0.01 |
| QQQ | O3 | 2019..2026 | 0.86 | 17.77% | 20.12% | -2.36% | 0.76 | 0.86 | -0.10 |
| QQQ | O3 | 2011..2026 | 0.92 | 16.06% | 17.52% | -1.46% | 0.81 | 0.86 | -0.05 |
| QQQ | O4 | 2011..2018 | 0.88 | 11.86% | 13.46% | -1.61% | 0.79 | 0.88 | -0.09 |
| QQQ | O4 | 2019..2026 | 0.72 | 14.45% | 17.37% | -2.92% | 0.70 | 0.86 | -0.16 |
| QQQ | O4 | 2011..2026 | 0.80 | 13.12% | 15.54% | -2.42% | 0.74 | 0.86 | -0.12 |
| IWM | O1 | 2011..2018 | 0.82 | 7.45% | 7.24% | +0.21% | 0.52 | 0.50 | +0.01 |
| IWM | O1 | 2019..2026 | 0.63 | 7.61% | 8.96% | -1.35% | 0.37 | 0.45 | -0.08 |
| IWM | O1 | 2011..2026 | 0.73 | 7.53% | 8.11% | -0.58% | 0.44 | 0.47 | -0.03 |
| IWM | O2 | 2011..2018 | 0.90 | 8.09% | 7.77% | +0.32% | 0.54 | 0.50 | +0.03 |
| IWM | O2 | 2019..2026 | 0.79 | 4.65% | 10.25% | -5.60% | 0.19 | 0.46 | -0.27 |
| IWM | O2 | 2011..2026 | 0.85 | 6.39% | 8.99% | -2.60% | 0.36 | 0.47 | -0.12 |
| IWM | O3 | 2011..2018 | 0.96 | 7.71% | 8.22% | -0.51% | 0.49 | 0.50 | -0.02 |
| IWM | O3 | 2019..2026 | 0.87 | 8.06% | 10.82% | -2.76% | 0.34 | 0.46 | -0.12 |
| IWM | O3 | 2011..2026 | 0.92 | 7.88% | 9.49% | -1.61% | 0.41 | 0.47 | -0.07 |
| IWM | O4 | 2011..2018 | 0.81 | 7.34% | 7.12% | +0.23% | 0.52 | 0.50 | +0.02 |
| IWM | O4 | 2019..2026 | 0.57 | 6.39% | 8.42% | -2.02% | 0.31 | 0.45 | -0.14 |
| IWM | O4 | 2011..2026 | 0.69 | 6.88% | 7.80% | -0.92% | 0.42 | 0.47 | -0.05 |

**In 2019–2026 the overlay lost to its own dilution control on 24 of 24 cells** — the timing component was negative every time, by −0.4% to −7.0% a year. In 2011–2018 it lost on 12 of 24. Over the full record the timing term costs roughly 1%–5% a year *on top of* the dilution. Read the other way: an overlay that ends up at, say, 0.80 average exposure has thrown away a fifth of the fund's return for no Sharpe gain, and then paid a timing penalty on top of that. Holding 80% of the fund and 20% T-bills gets the same risk reduction, no turnover, and keeps the Sharpe.

## The one thing the gates genuinely deliver: drawdown

Sharpe is not the only thing a risk overlay is bought for, and it would be dishonest to stop at the Sharpe table. **The trend gates cut maximum drawdown materially, and by more than dilution alone explains.** Over 2011–2026 at base costs:

| fund | B&H max DD | O1 max DD | O1 dilution-control max DD | O1 beyond dilution | O4 max DD | O4 beyond dilution |
|---|---|---|---|---|---|---|
| SPMO | -30.9% | -15.6% | -26.3% | +10.6pp | -15.2% | +9.5pp |
| MTUM | -34.1% | -24.1% | -28.5% | +4.4pp | -24.5% | +2.4pp |
| SPY | -33.7% | -24.3% | -29.0% | +4.7pp | -22.7% | +5.5pp |
| RSP | -39.0% | -25.3% | -32.2% | +6.9pp | -24.2% | +7.4pp |
| QQQ | -35.1% | -28.6% | -30.4% | +1.8pp | -28.6% | +0.2pp |
| IWM | -41.1% | -26.1% | -30.9% | +4.8pp | -25.1% | +4.2pp |

O1 is shallower than buy-and-hold on all 6 funds (by 6.5 to 15.3 points) and shallower than its own dilution control on all 6 (by 1.8 to 10.6 points). O4 likewise, on all 6. O2 and O3 do not: O2 is *deeper* than its dilution control on 3 of 6, and O3 barely moves drawdown at all — it scales on trailing realised vol, which rises after a drawdown rather than before it, so it de-risks into the recovery.

So the honest statement is: **an own-fund 200-day trend gate buys you 6.5–15 points of maximum drawdown, and you pay 2.6%–4.6% a year of CAGR and −0.05 of Sharpe on average over the full record (−0.12 on average in 2019–2026) for it.** Whether that is a good trade is a preference, not a research finding — but it is emphatically not alpha, and it is not what a momentum stock book is being built to produce. If drawdown is the objective, say so and measure against it; if Sharpe is the objective, these overlays fail.

## Did the monthly gate sell the bottom?

**2020:** SPY peak 2020-02-19, trough 2020-03-23 (-33.7%), back to the peak 2020-08-10. **2025:** peak 2025-02-19, trough 2025-04-08 (-18.8%), recovered 2025-06-26.

**It did not sell the exact bottom — it sold before the bottom and bought back after the rebound, which is worse.** Both fates show up:

- **2020.** The gate went flat at the 2 March month start, ahead of most of the crash (the funds fell a further 17%–32% from that close to the 23 March trough, so the sell itself was timely). It was then flat for the entire April–May rebound and only re-entered on 1 June — after the funds had already risen 33%–39% off the trough. On RSP and IWM the own-fund gate stayed out until 3 August.
- **2025.** The gate sold at the 1 April month start, **five sessions before the 8 April trough**, after the funds had already fallen 4.8%–13.0% from the peak, with only 10.5%–12.4% of the fall left to avoid. That is selling the bottom. It re-entered on 2 June, by which point the funds had already risen 15%–29% off the trough.

| episode | fund | overlay | exposure on the trough day | peak→trough overlay vs B&H | trough→recovery overlay vs B&H | peak→recovery overlay vs B&H |
|---|---|---|---|---|---|---|
| 2020 | SPMO | O1 | 0.00 | -12.3% vs -30.9% | +12.8% vs +49.8% | **-1.2% vs +7.3%** |
| 2020 | SPMO | O2 | 0.00 | -12.3% vs -30.9% | +12.8% vs +49.8% | **-1.2% vs +7.3%** |
| 2020 | SPMO | O4 | 0.00 | -12.3% vs -30.9% | +5.4% vs +49.8% | **-7.6% vs +7.3%** |
| 2020 | MTUM | O1 | 0.00 | -11.6% vs -33.9% | +12.2% vs +51.3% | **-0.8% vs +3.8%** |
| 2020 | MTUM | O2 | 0.00 | -11.6% vs -33.9% | +12.2% vs +51.3% | **-0.8% vs +3.8%** |
| 2020 | MTUM | O4 | 0.00 | -11.6% vs -33.9% | +5.3% vs +51.3% | **-6.9% vs +3.8%** |
| 2020 | SPY | O1 | 0.00 | -12.0% vs -33.4% | +10.7% vs +47.3% | **-2.6% vs +0.7%** |
| 2020 | SPY | O2 | 0.00 | -12.0% vs -33.4% | +10.7% vs +47.3% | **-2.6% vs +0.7%** |
| 2020 | SPY | O4 | 0.00 | -12.0% vs -33.4% | +4.8% vs +47.3% | **-7.8% vs +0.7%** |
| 2020 | RSP | O1 | 0.00 | -12.5% vs -38.8% | +3.6% vs +49.6% | **-9.4% vs -5.1%** |
| 2020 | RSP | O2 | 0.00 | -12.5% vs -38.8% | +10.3% vs +49.6% | **-3.5% vs -5.1%** |
| 2020 | RSP | O4 | 0.00 | -12.5% vs -38.8% | +1.4% vs +49.6% | **-11.3% vs -5.1%** |
| 2020 | QQQ | O1 | 1.00 | -27.2% vs -27.2% | +38.1% vs +59.0% | **+0.5% vs +15.6%** |
| 2020 | QQQ | O2 | 0.00 | -12.3% vs -27.2% | +16.0% vs +59.0% | **+1.7% vs +15.6%** |
| 2020 | QQQ | O4 | 1.00 | -27.2% vs -27.2% | +23.4% vs +59.0% | **-10.3% vs +15.6%** |
| 2020 | IWM | O1 | 0.00 | -12.7% vs -40.4% | +7.1% vs +56.7% | **-6.5% vs -5.1%** |
| 2020 | IWM | O2 | 0.00 | -12.7% vs -40.4% | +13.9% vs +56.7% | **-0.5% vs -5.1%** |
| 2020 | IWM | O4 | 0.00 | -12.7% vs -40.4% | +2.7% vs +56.7% | **-10.3% vs -5.1%** |
| 2025 | SPMO | O1 | 0.00 | -10.0% vs -19.6% | +18.1% vs +33.5% | **+6.3% vs +8.4%** |
| 2025 | SPMO | O2 | 0.00 | -10.0% vs -19.6% | +6.4% vs +33.5% | **-4.3% vs +8.4%** |
| 2025 | SPMO | O4 | 0.00 | -10.0% vs -19.6% | +12.5% vs +33.5% | **+1.2% vs +8.4%** |
| 2025 | MTUM | O1 | 0.00 | -11.7% vs -21.0% | +13.6% vs +30.1% | **+0.3% vs +3.8%** |
| 2025 | MTUM | O2 | 0.00 | -11.7% vs -21.0% | +3.2% vs +30.1% | **-8.8% vs +3.8%** |
| 2025 | MTUM | O4 | 0.00 | -11.7% vs -21.0% | +9.5% vs +30.1% | **-3.3% vs +3.8%** |
| 2025 | SPY | O1 | 0.00 | -8.2% vs -18.6% | +4.7% vs +21.7% | **-3.9% vs +0.7%** |
| 2025 | SPY | O2 | 0.00 | -8.2% vs -18.6% | +4.7% vs +21.7% | **-3.9% vs +0.7%** |
| 2025 | SPY | O4 | 0.00 | -8.2% vs -18.6% | +3.9% vs +21.7% | **-4.7% vs +0.7%** |
| 2025 | RSP | O1 | 0.00 | -4.6% vs -15.8% | +3.1% vs +16.1% | **-1.6% vs -0.3%** |
| 2025 | RSP | O2 | 0.00 | -4.6% vs -15.8% | +3.1% vs +16.1% | **-1.6% vs -0.3%** |
| 2025 | RSP | O4 | 0.00 | -4.6% vs -15.8% | +3.0% vs +16.1% | **-1.7% vs -0.3%** |
| 2025 | QQQ | O1 | 0.00 | -12.9% vs -22.7% | +5.9% vs +29.1% | **-7.7% vs +1.5%** |
| 2025 | QQQ | O2 | 0.00 | -12.9% vs -22.7% | +5.9% vs +29.1% | **-7.7% vs +1.5%** |
| 2025 | QQQ | O4 | 0.00 | -12.9% vs -22.7% | +4.2% vs +29.1% | **-9.2% vs +1.5%** |
| 2025 | IWM | O1 | 0.00 | -5.2% vs -22.9% | +0.9% vs +20.3% | **-4.3% vs -4.7%** |
| 2025 | IWM | O2 | 0.00 | -12.0% vs -22.9% | +5.9% vs +20.3% | **-6.8% vs -4.7%** |
| 2025 | IWM | O4 | 0.00 | -4.7% vs -22.9% | +0.9% vs +20.3% | **-3.8% vs -4.7%** |

**32 of 36 (fund × gate × episode) cells finish the round trip behind buy-and-hold.** The gate did reliably cut the drawdown — in 2020 it took −12% or −13% peak-to-trough on five of the six funds, against −27% to −40% for buy-and-hold (QQQ is the exception: its own 200-day gate never triggered, so O1 rode the full −27%) — and then gave all of it back and more by being in cash for the rebound. That is the mechanism behind the uniformly negative 2019–2026 deltas: the second half contains two fast V-shaped drawdowns, and a monthly-evaluated trend gate is structurally short the V.

The four cells that *do* finish ahead are 2020 RSP × O2 (−3.5% vs −5.1%), 2020 IWM × O2 (−0.5% vs −5.1%), 2025 IWM × O1 (−4.3% vs −4.7%) and 2025 IWM × O4 (−3.8% vs −4.7%) — all cases where the fund itself had not recovered by the SPY-defined recovery date, so the comparison is against a buy-and-hold that is still under water. None of them is a margin worth anything, and none of the four translates into a positive second-half Sharpe delta.

Exposure at every month start through both episodes is in `results.json` under `forensics`; the full daily exposure path for all 30 variants is `diagnostics/exposure_paths.csv`.

## Causality

**Passed.** Every price after a cut date was multiplied by an independent random factor drawn uniformly on [0.3, 3.0] — for the fund and, separately, for SPY — and the exposure path was recomputed. Across **84 tests** (6 underlyings × O1–O4 × cut dates 2013-06-28, 2016-01-04, 2020-03-23, 2024-07-01, skipping cuts outside a fund's history) the exposure path on every date at or before the cut was **bit-identical in all 84**: `prefix_unchanged = True`. As a guard against a vacuous pass, the path after the cut *did* change in all 84 as well (`suffix_moved = True`), so the test had the power to detect leakage. Test code: `research/overlay_control/run.py::causality_test`.

Construction: every signal series is stated as of its own close and read with `.shift(1)`, so a month-start decision at *t* sees closes through *t−1* only. The trade is booked at the *t−1* close and the position is held through session *t*.

**One-session implementation lag.** Because the *t−1* close is also the trade price, a natural objection is that the result depends on trading the signal bar. Re-running O1–O4 with the exposure applied one session later (`lag=2`, base costs, 2011–2026 Sharpe):

| fund | O1 | O2 | O3 | O4 |
|---|---|---|---|---|
| SPMO | 0.86 → 0.82 | 0.59 → 0.71 | 0.76 → 0.76 | 0.81 → 0.75 |
| MTUM | 0.65 → 0.51 | 0.48 → 0.56 | 0.65 → 0.65 | 0.61 → 0.46 |
| SPY | 0.67 → 0.75 | 0.67 → 0.75 | 0.73 → 0.73 | 0.63 → 0.71 |
| RSP | 0.58 → 0.60 | 0.54 → 0.61 | 0.58 → 0.58 | 0.57 → 0.59 |
| QQQ | 0.81 → 0.82 | 0.73 → 0.79 | 0.81 → 0.81 | 0.74 → 0.73 |
| IWM | 0.44 → 0.37 | 0.36 → 0.42 | 0.41 → 0.41 | 0.42 → 0.33 |

The delay moves individual cells by up to 0.15 in both directions and changes nothing qualitatively. Under the one-session delay: **0 of 24 cells are positive over the full record** (best −0.024), **0 of 24 are positive in 2019–2026** (best −0.013, median −0.138), 12 of 24 are positive in 2011–2018 (median −0.000), and **0 of 24 survive both halves**. The conclusion is not an artefact of the fill convention — if anything the delayed version is slightly worse.

## Caveats, stated plainly

1. **SPMO and MTUM have short first halves.** SPMO's usable record starts 2016-07-27 and MTUM's 2014-01-31, because the 200-session moving average needs 200 sessions. The `2011..2018` row for SPMO is 2.4 years, not 8. Its +0.33 O1 delta is the single largest positive in the whole matrix and it comes from **exactly one decision**: SPMO's gate was on continuously from 2016-08-01, went flat at the 2018-11-01 month start, and sat out the December 2018 selloff. Calendar 2018 is +7.23% for O1 against −0.92% for buy-and-hold; the 2016-07 to 2017-12 stretch is identical for both (+29.32%) because the gate never moved. One month of one short sample, and it reverses to −0.07 in the second half. It is not evidence for anything.
2. **O0 is charged costs.** Entry, and a final liquidation, at 5bps/15bps, like the frozen engine's passive. This costs buy-and-hold about 1bp a year over the full record and makes the deltas very slightly generous to the overlays.
3. **All overlays for a given fund share one start date**, so O0 and O1–O4 are on identical date ranges and the deltas are clean. This is why the SPMO buy-and-hold row here reads 10.75% / 0.65 for 2011–2018 rather than the README comparator's 0.70 — the comparator starts at SPMO's 2015-10-12 inception. On the funds with full history the reconstruction matches the raw comparators to 0.01 CAGR and 0.01 Sharpe in all three windows, which is the engine check.
4. **This is a control, not a candidate.** Nothing here is proposed as a strategy and nothing was selected on. All 30 registered variants are reported: 6 buy-and-hold references and 24 overlay cells, of which 23 lose Sharpe over the full record, 24 lose it in the second half, and 0 survive both halves.

## Files

- `research/overlay_control/PLAN.md` — the pre-registration, ledgered before any computation
- `research/overlay_control/run.py` — engine, signals, causality test, forensics
- `reports/overlay_control_20260919/results.json` — every number above
- `reports/overlay_control_20260919/diagnostics/` — 30 daily NAV series, and the exposure paths
