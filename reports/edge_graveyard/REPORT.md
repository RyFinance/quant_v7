# The edge graveyard: which published edges survive, and where

Research agent, 2026-09-19. Phase 1 and Phase 2 of `research/EDGE_GRAVEYARD_PLAN.md`.
Meta-research only: **no strategy was backtested on quant_v7 price data.** The OSAP long-short
returns are academic portfolios (CRSP universe, gross of costs, microcaps included); no trading
decision comes straight from them. Candidates for testers are in `CANDIDATES.md`.

Code: `research/edge_graveyard/` (`tags.py` mechanism/data tags, `survival_study.py` period stats and
McLean–Pontiff regressions, `tables.py` tables and survival model). Data: `data/osap/` (Chen &
Zimmermann Open Source Asset Pricing, release 2025-10, returns through 2024-12). Outputs:
`predictor_decay.csv` (one row per predictor, every statistic), `mp_regression.csv`, `tables.md`.
Reproduce: `PYTHONPATH=. .venv/bin/python research/edge_graveyard/survival_study.py && PYTHONPATH=. .venv/bin/python research/edge_graveyard/tables.py`.

## Plain-language conclusions

1. **Publication halves an edge, and time finishes the job.** Replicating McLean & Pontiff (2016) on
   the 212 OSAP predictors: returns fall 30% (±11%) after the original sample ends and 58% (±9%)
   after publication (McLean–Pontiff report 26% and 58%). In 2015–2024 the average predictor
   earns 0.28%/month against 0.69% in-sample; the mean Sharpe falls from 0.79 to 0.23, and only 14%
   of predictors still have t ≥ 2. Chen, Lopez-Lira & Zimmermann (2024) find the same ~50% decay
   for data-mined accounting ratios, so this is mostly statistical overfitting plus arbitrage, not a
   property of peer review.
2. **Surviving edges are NOT concentrated in small caps.** This rejects the plan's "capacity niche"
   hope. Predictors whose premium depended most on microcaps decayed most (2015+ Sharpe 0.13 vs 0.29
   for big-cap-robust ones; ex-microcap 0.05 vs 0.25). "Small-cap share" is significantly negative
   in the survival regressions. Value-weighted versions are weak everywhere: VW quintile spreads
   average a 0.07 Sharpe in 2015+. **The typical published stock anomaly, traded in the stocks we
   can actually trade, is worth roughly a 0.1 Sharpe gross today.**
3. **Crash-exposed edges survive; lottery-like edges die.** Spreads with negative in-sample skew
   kept 57% of their mean in 2015+ (Sharpe 0.36); positive-skew spreads kept 8% (0.10). Skewness is
   significant in every specification. Spreads with a mild worst month also decayed most. What
   survives looks like pay for bearing a bad tail, which does not get arbitraged away.
4. **Data source matters more than the story.** Options-based (2015+ Sharpe 0.50) and institutional-
   holdings (0.56) predictors survived best; accounting 0.26, price 0.17, volume 0.12, and "other"
   alternative data −0.20. Newer, costlier data still pays; cheap public price/volume data has been
   mined out. Option skew (`SmileSlope`) is the single strongest survivor (Sharpe 1.47; 1.12 ex-
   microcap; 1.38 VW), which supports the registered options experiment.
5. **Mechanism ranking (plan hypothesis partly wrong).** The plan predicted M2/M3 survive best and
   M4/M5 fastest decay. In the cross-section:
   - **M4 slow reaction to firm news** (earnings streaks, issuance, revisions): best survivor among
     big groups (2015+ Sharpe 0.33, median 41% of in-sample kept).
   - **M1 new data** (options, holdings): 0.36, and the best in big stocks (0.45 ex-microcap).
   - **M6 risk premia**: 0.21, keep 39% of their mean, decline slowly.
   - **M3 limits to arbitrage** (illiquidity, idio-vol, lottery, size): 0.13 and −0.09 VW; mostly
     dead in anything tradable.
   - **M2 forced flows as proxied in the cross-section** (return seasonality, spinoffs,
     dividend-month): 0.12, and 0.01 ex-microcap. Caveat: the cross-section has few true forced-flow
     predictors. The literature catalogue below shows forced-flow edges *outside* the cross-section
     survive when the flow grows faster than the arbitrage capital (Treasury auctions, month-end
     rebalancing, LETF) and die when the event becomes predictable to arbitrageurs (S&P inclusion,
     Russell, commodity index rolls).
   - **M5 economic links** (customer/supplier, industry lead-lag): dead (−0.04; −0.19 VW).
   - **M7**: no OSAP predictor; see the catalogue.
6. **Our own history fits the pattern.** Plain SUE (the PEAD signal) has a 2015+ Sharpe of 0.06 in
   OSAP; streak-conditioned PEAD (`EarningsStreak`, 1.12; 0.55 ex-microcap) and revision momentum
   (`REV6`, 0.62; VW 0.64) survive. Momentum-type signals held up in big stocks (`Mom12m` 0.44
   ex-micro), but with worst months of −30% to −80%.
7. **Diversification is the only thing that keeps the cross-section attractive, and it is gross.**
   An equal-weight blend of all 212 predictors had a 2015–2024 Sharpe of 1.38 (0.86 ex-microcap,
   0.38 value-weighted), before costs. Chen & Velikov (2023, JFQA) show trading costs remove most
   of this after 2005. Not reachable with our 500-name, no-fundamentals, survivor-biased data.

## Survival model, in one paragraph

Cross-sectional OLS (Table 10) of each predictor's 2015+ Sharpe on tags. Significant: in-sample
t-stat (+: stronger original evidence survives better), small-cap share (−), in-sample skewness
(−), M5 links (−), holdings data (+, all-stock version) and, in the ex-microcap version, M2
seasonality/flow predictors (−). The other mechanism dummies are insignificant once data source,
skew and small-cap share are controlled for. Rebalance frequency and publication era do not matter.
R² is 0.23–0.32: most variation in survival is unexplained, so tags are priors, not predictions.

**Tagging caveat.** Mechanisms are assigned by rule from Chen–Zimmermann's `Cat.Economic`, with
~50 hand overrides (`research/edge_graveyard/tags.py`), using only the paper's story, not returns.
The mechanism labels are subjective; data-source labels come straight from OSAP.
Period definitions: IS = paper's sample years; OOS = sample end to publication year; POST = after
the publication year; 2015+ = 2015-01 to 2024-12 (only 6 predictors were published after 2014).
Small-cap share = 1 − IS mean(stocks above the NYSE 20th size percentile)/IS mean(all stocks).

## Where edges live (map)

| | Big, liquid stocks | Small/micro caps | Outside the cross-section |
|---|---|---|---|
| **Still alive (2015+)** | option skew and IV changes; profitability (GP); issuance/buybacks; earnings consistency and streaks; revisions; momentum (crash-prone) | little beyond what also works in big stocks; DivOmit, short interest | Treasury auction cycle; month-end rebalancing; LETF close flows; CIP deviations (not for us); merger-arb and put-writing risk premia |
| **Shrunk to marginal** | value, asset growth, accruals, short-term reversal | IPO/SEO effects, dividend-month | turn-of-month; Russell reconstitution; closed-end fund discounts; pairs trading; TSMOM/carry |
| **Dead** | SUE (plain PEAD), customer/supplier, industry lead-lag, liquidity/volume, size | lottery/idio-vol, illiquidity | S&P inclusion pop; pre-FOMC drift; weekend/January; earnings-announcement premium; Twitter/Google-Trends signals; FX fix; twin-share arbitrage |

## Decay tables

Full tables with extra columns: `tables.md`. Every predictor: `predictor_decay.csv`.

### McLean–Pontiff pooled regression (fraction of in-sample mean; predictor fixed effects; month-clustered SE)

| version | N | out-of-sample, pre-publication | post-publication |
|---|---|---|---|
| original-paper method | 208 | −0.30 (0.11) | −0.58 (0.09) |
| original method, IS t ≥ 2 | 186 | −0.27 (0.10) | −0.55 (0.08) |
| quintile EW, IS t ≥ 2 | 152 | −0.25 (0.13) | −0.62 (0.09) |
| quintile VW, IS t ≥ 2 | 83 | −0.43 (0.20) | −0.76 (0.14) |
| ex-microcap (ME > NYSE p20), IS t ≥ 2 | 129 | −0.41 (0.13) | −0.57 (0.11) |
| NYSE only, IS t ≥ 2 | 125 | −0.43 (0.10) | −0.56 (0.10) |

The unfiltered VW and ex-microcap scaled regressions are unstable because many in-sample means
there are near zero (see `mp_regression.csv`); the IS t ≥ 2 rows fix that.

### Table 1. Average predictor, by period (original-paper method, % per month; Sharpe annualised)
| stat | IS | OOS | POST | P2015 |
|---|---|---|---|---|
| mean %/mo | 0.69 | 0.41 | 0.30 | 0.28 |
| median %/mo | 0.57 | 0.37 | 0.23 | 0.20 |
| mean t | 3.93 | 1.15 | 1.29 | 0.72 |
| mean Sharpe | 0.79 | 0.55 | 0.29 | 0.23 |
| median Sharpe | 0.67 | 0.51 | 0.26 | 0.22 |
| share t>=2 | 0.88 | 0.27 | 0.28 | 0.14 |
| avg months | 350.89 | 54.62 | 237.59 | 116.44 |
| N | 212.00 | 212.00 | 212.00 | 208.00 |

### Table 2. Same, by portfolio construction (mean Sharpe; median ratio of period mean to own IS mean)
| version | SR IS | SR OOS | SR POST | SR P2015 | ratio OOS | ratio POST | ratio P2015 | N |
|---|---|---|---|---|---|---|---|---|
| original paper (mostly EW) | 0.79 | 0.55 | 0.29 | 0.23 | 0.60 | 0.40 | 0.31 | 212.00 |
| quintile EW | 0.78 | 0.57 | 0.28 | 0.20 | 0.69 | 0.36 | 0.28 | 179.00 |
| quintile VW | 0.39 | 0.25 | 0.11 | 0.07 | 0.50 | 0.27 | 0.14 | 179.00 |
| ex-microcap (ME>NYSE p20) | 0.57 | 0.34 | 0.20 | 0.16 | 0.54 | 0.36 | 0.29 | 209.00 |
| NYSE only | 0.53 | 0.29 | 0.19 | 0.15 | nan | nan | nan | 212.00 |

### Table 3. Survival by mechanism
| mechanism | N | IS Sharpe | POST Sharpe | 2015+ Sharpe | POST/IS (median) | 2015+/IS (median) | alive 2015+ (t>=1.5) | 2015+ Sharpe ex-micro | 2015+ Sharpe VW | smallcap share |
|---|---|---|---|---|---|---|---|---|---|---|
| M1 | 15.00 | 0.81 | 0.29 | 0.36 | 0.37 | 0.29 | 0.33 | 0.45 | 0.26 | 0.10 |
| M2 | 12.00 | 0.84 | 0.27 | 0.12 | 0.26 | 0.19 | 0.25 | 0.01 | 0.08 | 0.31 |
| M3 | 31.00 | 0.60 | 0.21 | 0.13 | 0.28 | 0.24 | 0.19 | 0.10 | -0.09 | 0.32 |
| M4 | 67.00 | 1.03 | 0.38 | 0.33 | 0.50 | 0.41 | 0.37 | 0.22 | 0.15 | 0.24 |
| M5 | 9.00 | 0.67 | 0.15 | -0.04 | 0.12 | -0.20 | 0.11 | -0.11 | -0.19 | 0.11 |
| M6 | 78.00 | 0.66 | 0.26 | 0.21 | 0.45 | 0.39 | 0.19 | 0.15 | 0.06 | 0.32 |

### Table 4. Survival by data source
| data source | N | IS Sharpe | POST Sharpe | 2015+ Sharpe | POST/IS (median) | 2015+/IS (median) | alive 2015+ (t>=1.5) | 2015+ Sharpe ex-micro | 2015+ Sharpe VW | smallcap share |
|---|---|---|---|---|---|---|---|---|---|---|
| accounting | 99.00 | 0.78 | 0.32 | 0.26 | 0.47 | 0.37 | 0.28 | 0.17 | 0.07 | 0.30 |
| alt_other | 12.00 | 0.43 | -0.23 | -0.20 | -0.11 | -0.31 | 0.00 | 0.00 | 0.07 | 0.14 |
| analyst | 18.00 | 1.20 | 0.34 | 0.24 | 0.30 | 0.28 | 0.17 | 0.13 | 0.20 | 0.14 |
| event | 8.00 | 0.92 | 0.46 | 0.40 | 0.56 | 0.51 | 0.50 | 0.25 | 0.45 | 0.43 |
| flows_holdings | 8.00 | 0.60 | 0.39 | 0.56 | 0.63 | 0.82 | 0.62 | 0.55 | 0.44 | 0.06 |
| options | 9.00 | 1.05 | 0.56 | 0.50 | 0.47 | 0.32 | 0.44 | 0.39 | 0.22 | 0.07 |
| price | 45.00 | 0.76 | 0.25 | 0.17 | 0.34 | 0.25 | 0.20 | 0.12 | 0.02 | 0.32 |
| volume | 13.00 | 0.63 | 0.24 | 0.12 | 0.29 | -0.02 | 0.15 | 0.04 | -0.15 | 0.32 |

### Table 5. Survival by small-cap dependence (tercile of IS premium lost when microcaps removed)
| small-cap tercile | N | IS Sharpe | POST Sharpe | 2015+ Sharpe | POST/IS (median) | 2015+/IS (median) | alive 2015+ (t>=1.5) | 2015+ Sharpe ex-micro | 2015+ Sharpe VW | smallcap share |
|---|---|---|---|---|---|---|---|---|---|---|
| low (big-cap ok) | 70.00 | 0.72 | 0.30 | 0.29 | 0.45 | 0.44 | 0.31 | 0.25 | 0.19 | -0.01 |
| mid | 69.00 | 0.90 | 0.34 | 0.28 | 0.45 | 0.30 | 0.30 | 0.22 | 0.12 | 0.26 |
| high (microcap) | 70.00 | 0.77 | 0.24 | 0.13 | 0.36 | 0.25 | 0.17 | 0.05 | -0.09 | 0.52 |

### Table 6. Survival by rebalance frequency (portfolio holding period, months)
| holding months | N | IS Sharpe | POST Sharpe | 2015+ Sharpe | POST/IS (median) | 2015+/IS (median) | alive 2015+ (t>=1.5) | 2015+ Sharpe ex-micro | 2015+ Sharpe VW | smallcap share |
|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 109.00 | 0.88 | 0.32 | 0.26 | 0.39 | 0.31 | 0.27 | 0.17 | 0.13 | 0.25 |
| 3.0 | 7.00 | 0.92 | 0.32 | 0.45 | 0.44 | 0.80 | 0.71 | 0.43 | 0.14 | 0.01 |
| 6.0 | 2.00 | 0.36 | 0.20 | 0.15 | 0.82 | 0.49 | 0.00 | 0.10 | -0.03 | 0.30 |
| 12.0 | 92.00 | 0.68 | 0.24 | 0.18 | 0.37 | 0.30 | 0.22 | 0.14 | 0.01 | 0.32 |
| 36.0 | 1.00 | 0.54 | 0.12 | 0.11 | 0.25 | 0.23 | 0.00 | -0.11 | 0.11 | 0.91 |

### Table 7. Survival by in-sample skewness
| IS skew tercile | N | IS Sharpe | POST Sharpe | 2015+ Sharpe | POST/IS (median) | 2015+/IS (median) | alive 2015+ (t>=1.5) | 2015+ Sharpe ex-micro | 2015+ Sharpe VW | smallcap share |
|---|---|---|---|---|---|---|---|---|---|---|
| neg skew | 71.00 | 0.81 | 0.39 | 0.36 | 0.56 | 0.57 | 0.41 | 0.23 | 0.19 | 0.20 |
| mid | 70.00 | 0.80 | 0.29 | 0.22 | 0.36 | 0.29 | 0.24 | 0.16 | -0.01 | 0.25 |
| pos skew | 71.00 | 0.77 | 0.19 | 0.10 | 0.24 | 0.08 | 0.13 | 0.10 | 0.01 | 0.32 |

### Table 8. Survival by publication era
| published | N | IS Sharpe | POST Sharpe | 2015+ Sharpe | POST/IS (median) | 2015+/IS (median) | alive 2015+ (t>=1.5) | 2015+ Sharpe ex-micro | 2015+ Sharpe VW | smallcap share |
|---|---|---|---|---|---|---|---|---|---|---|
| <=1995 | 28.00 | 0.82 | 0.37 | 0.17 | 0.56 | 0.38 | 0.21 | 0.11 | -0.04 | 0.34 |
| 1996-2005 | 74.00 | 0.84 | 0.24 | 0.17 | 0.30 | 0.23 | 0.22 | 0.10 | -0.01 | 0.26 |
| 2006-2010 | 69.00 | 0.72 | 0.28 | 0.27 | 0.36 | 0.31 | 0.30 | 0.19 | 0.13 | 0.22 |
| 2011-2016 | 41.00 | 0.81 | 0.33 | 0.31 | 0.40 | 0.42 | 0.29 | 0.26 | 0.14 | 0.24 |

### Table 9. Survival by Chen-Zimmermann economic category (N>=6)
| category | N | IS Sharpe | POST Sharpe | 2015+ Sharpe | POST/IS (median) | 2015+/IS (median) | alive 2015+ (t>=1.5) | 2015+ Sharpe ex-micro | 2015+ Sharpe VW | smallcap share |
|---|---|---|---|---|---|---|---|---|---|---|
| profitability | 8.00 | 0.65 | 0.55 | 0.59 | 1.00 | 1.06 | 0.62 | 0.47 | 0.49 | 0.28 |
| external financing | 12.00 | 0.87 | 0.54 | 0.49 | 0.74 | 0.83 | 0.42 | 0.27 | 0.16 | 0.38 |
| momentum | 11.00 | 0.84 | 0.29 | 0.42 | 0.43 | 0.53 | 0.45 | 0.34 | 0.17 | 0.04 |
| risk | 6.00 | 0.50 | 0.30 | 0.36 | 0.71 | 0.66 | 0.17 | 0.35 | 0.26 | 0.41 |
| valuation | 17.00 | 0.74 | 0.46 | 0.34 | 0.64 | 0.50 | 0.29 | 0.18 | -0.04 | 0.16 |
| investment | 8.00 | 0.85 | 0.35 | 0.22 | 0.37 | 0.37 | 0.12 | 0.13 | 0.05 | 0.33 |
| earnings forecast | 8.00 | 1.61 | 0.40 | 0.18 | 0.28 | 0.15 | 0.12 | 0.12 | 0.14 | 0.19 |
| volatility | 6.00 | 0.59 | 0.15 | 0.17 | 0.24 | 0.25 | 0.00 | 0.14 | 0.10 | 0.58 |
| volume | 6.00 | 0.58 | 0.22 | 0.14 | 0.32 | 0.05 | 0.17 | -0.03 | -0.26 | 0.29 |
| investment alt | 10.00 | 0.81 | 0.14 | 0.11 | 0.27 | 0.26 | 0.10 | 0.15 | -0.13 | 0.35 |
| long term reversal | 6.00 | 0.38 | 0.23 | 0.10 | 0.66 | 0.40 | 0.00 | 0.08 | -0.19 | 0.21 |
| other | 27.00 | 0.66 | 0.13 | 0.07 | 0.25 | 0.15 | 0.19 | 0.04 | 0.16 | 0.31 |
| lead lag | 9.00 | 0.67 | 0.15 | -0.04 | 0.12 | -0.20 | 0.11 | -0.11 | -0.19 | 0.11 |
| sales growth | 6.00 | 0.76 | 0.02 | -0.10 | 0.10 | 0.13 | 0.17 | 0.01 | -0.03 | 0.13 |
| liquidity | 9.00 | 0.55 | 0.07 | -0.11 | 0.11 | -0.15 | 0.00 | 0.00 | -0.21 | 0.31 |

### Table 10. Survival model: cross-sectional OLS, HC1 SE
| regressor | op_POST_ratio_c (N=209) | op_P2015_ratio_c (N=206) | P2015_sr (N=206) | me_gt_nyse20__P2015_sr (N=206) |
|---|---|---|---|---|
| M1 | -0.04 (0.46) | +0.35 (0.67) | -0.20 (0.24) | +0.48 (0.35) |
| M2 | +0.03 (0.22) | -0.31 (0.34) | -0.23 (0.13) | -0.30 (0.12)* |
| M3 | +0.14 (0.24) | +0.14 (0.29) | -0.10 (0.08) | -0.04 (0.09) |
| M4 | -0.14 (0.13) | -0.14 (0.16) | -0.06 (0.08) | -0.03 (0.06) |
| M5 | -0.27 (0.25) | -0.58 (0.35) | -0.27 (0.12)* | -0.29 (0.14)* |
| d_price | -0.16 (0.13) | -0.15 (0.18) | -0.03 (0.07) | +0.04 (0.07) |
| d_volume | -0.38 (0.29) | -0.56 (0.35) | -0.04 (0.14) | -0.07 (0.13) |
| d_analyst | -0.23 (0.13) | -0.27 (0.16) | -0.06 (0.07) | -0.05 (0.07) |
| d_options | -0.17 (0.50) | -0.67 (0.72) | +0.41 (0.30) | -0.34 (0.37) |
| d_flows_holdings | -0.02 (0.34) | +0.10 (0.38) | +0.33 (0.16)* | +0.24 (0.17) |
| d_event | +0.14 (0.27) | +0.32 (0.44) | +0.20 (0.15) | +0.23 (0.16) |
| d_alt_other | -0.75 (0.37)* | -0.66 (0.44) | -0.19 (0.10) | -0.10 (0.12) |
| log IS t | -0.17 (0.11) | -0.09 (0.14) | +0.18 (0.05)* | +0.10 (0.04)* |
| smallcap share | -0.26 (0.26) | -0.49 (0.32) | -0.16 (0.06)* | -0.26 (0.06)* |
| monthly rebal | +0.07 (0.09) | +0.12 (0.11) | +0.07 (0.05) | +0.00 (0.05) |
| IS skew | -0.18 (0.05)* | -0.22 (0.07)* | -0.10 (0.02)* | -0.04 (0.02) |
| pub year-2000 | -0.07 (0.06) | +0.05 (0.08) | +0.03 (0.03) | +0.05 (0.02) |
| const | +0.94 (0.18)* | +0.79 (0.22)* | +0.10 (0.07) | +0.13 (0.06)* |
| R2 | 0.23 | 0.23 | 0.32 | 0.27 |

Base category: M6 risk premia, accounting data. * = |t|>=1.96. smallcap share = 1 - IS mean(ex-microcap)/IS mean(all). pub year scaled per decade.

### Table 11. Strongest 2015-2024 survivors (original method t>=2 in 2015+), with ex-microcap and VW versions
| signal | mech | data | pub | IS SR | POST SR | 2015+ SR | 2015+ SR ex-micro | 2015+ SR VW | smallcap share | description |
|---|---|---|---|---|---|---|---|---|---|---|
| SmileSlope | M1 | options | 2011 | 2.59 | 1.55 | 1.47 | 1.12 | 1.38 | 0.04 | Put volatility minus call volatility |
| dCPVolSpread | M1 | options | 2014 | 1.86 | 1.20 | 1.20 | 0.71 | 0.33 | 0.07 | Change in put vol minus change in call vol |
| EarningsStreak | M4 | accounting | 2012 | 2.20 | 1.23 | 1.12 | 0.55 | 0.36 | 0.25 | Earnings surprise streak |
| RIO_Volatility | M3 | flows_holdings | 2005 | 0.85 | 0.73 | 1.00 | 0.97 | nan | 0.09 | Inst Own and Idio Vol |
| XFIN | M4 | accounting | 2006 | 0.89 | 0.84 | 0.98 | 0.47 | 0.53 | 0.20 | Net external financing |
| NetPayoutYield | M6 | accounting | 2007 | 0.58 | 0.92 | 0.96 | 0.50 | 0.59 | 0.12 | Net Payout Yield |
| OrderBacklogChg | M4 | accounting | 2007 | 0.45 | 0.62 | 0.95 | 0.33 | 0.24 | 0.24 | Change in order backlog |
| OScore | M6 | accounting | 1998 | 0.85 | 0.57 | 0.94 | 0.23 | nan | -0.81 | O Score |
| VolumeTrend | M3 | volume | 1996 | 0.74 | 0.96 | 0.89 | 0.70 | 0.43 | 0.42 | Volume Trend |
| ShareIss5Y | M4 | accounting | 2006 | 0.59 | 0.78 | 0.88 | 0.63 | 1.05 | 0.04 | Share issuance (5 year) |
| MomVol | M4 | price | 2000 | 0.91 | 0.38 | 0.87 | 0.64 | nan | 0.15 | Momentum in high volume stocks |
| GP | M6 | accounting | 2013 | 0.35 | 0.80 | 0.85 | 1.07 | 0.85 | -0.01 | gross profits / total assets |
| dVolCall | M1 | options | 2014 | 0.73 | 0.85 | 0.85 | 0.80 | 0.45 | 0.18 | Change in call vol |
| EarningsConsistency | M4 | accounting | 2009 | 0.44 | 0.54 | 0.84 | 0.67 | 0.42 | -0.14 | Earnings consistency |
| roaq | M6 | accounting | 2010 | 1.02 | 0.78 | 0.82 | 0.29 | 0.44 | 0.43 | Return on assets (qtrly) |
| DivOmit | M4 | event | 1995 | 0.57 | 0.55 | 0.82 | 0.36 | nan | 0.60 | Dividend Omission |
| ShareIss1Y | M4 | accounting | 2008 | 0.75 | 0.65 | 0.82 | 0.60 | 0.49 | 0.17 | Share issuance (1 year) |
| IO_ShortInterest | M1 | flows_holdings | 2005 | 0.64 | 0.72 | 0.81 | 0.74 | 0.59 | 0.12 | Inst own among high short interest |
| ShortInterest | M3 | volume | 2001 | 1.25 | 0.83 | 0.79 | 0.21 | 0.18 | 0.39 | Short Interest |
| NetEquityFinance | M4 | accounting | 2006 | 0.56 | 0.72 | 0.74 | 0.49 | 0.29 | 0.21 | Net equity financing |
| RDIPO | M4 | event | 2006 | 0.72 | 0.68 | 0.74 | 0.74 | nan | 0.51 | IPO and no R&D spending |
(truncated; full list in tables.md)

### Table 12. Survivors in big stocks: ex-microcap 2015+ t>=2
| signal | mech | data | pub | ex-micro IS SR | ex-micro 2015+ SR | VW 2015+ SR | all 2015+ SR | description |
|---|---|---|---|---|---|---|---|---|
| SmileSlope | M1 | options | 2011 | 2.65 | 1.12 | 1.38 | 1.47 | Put volatility minus call volatility |
| GP | M6 | accounting | 2013 | 0.34 | 1.07 | 0.85 | 0.85 | gross profits / total assets |
| RIO_Volatility | M3 | flows_holdings | 2005 | 0.63 | 0.97 | nan | 1.00 | Inst Own and Idio Vol |
| dVolCall | M1 | options | 2014 | 0.57 | 0.80 | 0.45 | 0.85 | Change in call vol |
| Coskewness | M6 | price | 2000 | 0.41 | 0.76 | 0.49 | 0.68 | Coskewness |
| IO_ShortInterest | M1 | flows_holdings | 2005 | 0.61 | 0.74 | 0.59 | 0.81 | Inst own among high short interest |
| Tax | M4 | accounting | 2004 | 0.47 | 0.74 | 1.21 | 0.63 | Taxable income to income |
| RDIPO | M4 | event | 2006 | 0.31 | 0.74 | nan | 0.74 | IPO and no R&D spending |
| Mom12mOffSeason | M4 | price | 2008 | 0.84 | 0.74 | 0.37 | 0.68 | Momentum without the seasonal part |
| dCPVolSpread | M1 | options | 2014 | 1.69 | 0.71 | 0.33 | 1.20 | Change in put vol minus change in call vol |
| VolumeTrend | M3 | volume | 1996 | 0.49 | 0.70 | 0.43 | 0.89 | Volume Trend |
| EarningsConsistency | M4 | accounting | 2009 | 0.40 | 0.67 | 0.42 | 0.84 | Earnings consistency |
| Mom6m | M4 | price | 1993 | 0.91 | 0.66 | 0.37 | 0.56 | Momentum (6 month) |
| OrgCap | M6 | accounting | 2013 | 0.37 | 0.65 | 0.28 | 0.28 | Organizational capital |
| MomVol | M4 | price | 2000 | 0.87 | 0.64 | nan | 0.87 | Momentum in high volume stocks |
| OperProfRD | M6 | accounting | 2016 | 0.18 | 0.63 | 0.81 | 0.63 | Operating profitability R&D adjusted |

## Literature catalogue: edges outside the stock cross-section

Status: **alive** = still documented after publication in a recent study; **shrunk** = still
positive but small or only in part of the market; **dead** = gone or never replicated. "Mechanism
today" asks whether the underlying cause still exists, independent of whether the trade still pays.
Years are the first working paper / journal publication where known. Citations are from memory of
the literature except where a link is given; the linked items were checked on 2026-09-19.

| # | Edge | Found / published | Discovery method | What killed or shrank it | Status | Mechanism today |
|---|---|---|---|---|---|---|
| 1 | January effect (small caps) | Rozeff & Kinney 1976 JFE; Keim 1983 JFE | M1: first CRSP calendar sorts | front-running into December; Schwert (2003, Handbook) finds it much weaker after publication | shrunk (microcaps only) | tax-loss selling still exists |
| 2 | Weekend / Monday effect | French 1980 JFE | M1 calendar sort | disappeared soon after publication (Schwert 2003) | dead | no clear cause; likely data-mined |
| 3 | Pre-holiday effect | Ariel 1990 JF | calendar sort | faded after publication (Schwert 2003) | dead | weak |
| 4 | Turn-of-the-month | Ariel 1987 JFE; Lakonishok & Smidt 1988 RFS | calendar sort | partly arbitraged; now explained by payment flows | shrunk | M2: month-end cash needs (Etula, Rinne, Suominen & Vaittinen 2020 RFS, "Dash for cash") |
| 5 | Halloween / Sell-in-May | Bouman & Jacobsen 2002 AER | calendar sort, many countries | survives weakly but low Sharpe and long, noisy cycles | shrunk | unclear |
| 6 | Size effect | Banz 1981 JFE | M1 CRSP | disappeared after early 1980s; OSAP `Size` 2015+ Sharpe −0.36 | dead | only "size with quality control" (Asness et al. 2018 JFE) |
| 7 | Value Line enigma | Black 1973 FAJ; Stickel 1985 JFE | M1 proprietary rankings | rankings became widely followed; Value Line fund lagged | dead | — |
| 8 | S&P 500 inclusion pop | Shleifer 1986 JF; Harris & Gurel 1986 JF | M2 event study | anticipation, midcap migrations, pre-arranged liquidity to indexers: 7.4% (1990s) → <1% (2010s) ([Greenwood & Sammon 2025 JF](https://onlinelibrary.wiley.com/doi/10.1111/jofi.13410)) | dead | M2 flow is larger than ever but fully anticipated |
| 9 | Russell reconstitution | Madhavan 2003 FAJ | M2 event study | banding (2007) and heavy front-running; effect now mostly reverses by the effective date ([Madhavan 2003](https://www.hillsdaleinv.com/uploads/The_Russell_Reconstitution_Effect,_Ananth_Madhaven,_Financial_Analysts_Journal,_JulyAugust_2003,_Pages_51-64.pdf)) | shrunk | M2 flow exists; liquidity event, semiannual from 2026 |
| 10 | Pre-FOMC drift | Lucca & Moench 2015 JF (1994–2011) | M4/M6 event study on intraday futures | no drift after 2015 ([Kurov, Wolfe & Gilbert 2021 FRL](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3134546)); less uncertainty after liftoff/forward guidance | dead | weaker (uncertainty premium) |
| 11 | Macro-announcement-day premium | Savor & Wilson 2013 JFQA | M6 event study | smaller in recent samples; our I4 test | shrunk | M6 risk premium |
| 12 | Earnings-announcement premium | Beaver 1968; Frazzini & Lamont 2007 NBER; Barber et al. 2013 JFE | M6/attention | disappeared in the US after the 2004 8-K reform moved news to 8-K dates ([Heitz, Narayanamoorthy & Zekhnini, SSRN 3296537](https://www.ssrn.com/abstract=3296537)) | dead (US) | premium moved to 8-K filing dates |
| 13 | PEAD | Ball & Brown 1968; Bernard & Thomas 1989 JAR | M1 Compustat/IBES, M4 | faster processing and algorithms; large-cap PEAD gone (Martineau 2022 CFR, "Rest in peace PEAD"); OSAP SUE 2015+ 0.06; our own test failed | dead (large caps) | streak-conditioned version survives (OSAP) |
| 14 | Analyst revision momentum | Givoly & Lakonishok 1979; Chan, Jegadeesh & Lakonishok 1996 JF | M1 IBES | IBES became standard; OSAP `AnalystRevision` 0.22, but `REV6` 0.62 in 2015+ | shrunk | M4 alive in slower version |
| 15 | Overnight vs intraday return split | Cliff, Cooper & Gulen 2008; Lou, Polk & Skouras 2019 JFE | M1 intraday data, clientele | not a tradable spread after costs; our overnight reversal is a bounded null after 2018 | dead (for trading) | clientele effect exists |
| 16 | Intraday momentum (first → last half hour) | Gao, Han, Li & Zhou 2018 JFE | M1 intraday data | weaker after publication; explained by hedging flows (Baltussen, Da, Lammers & Martens 2021 JFE) | shrunk | M2 dealer gamma hedging, grown with 0DTE |
| 17 | Pairs trading | Gatev, Goetzmann & Rouwenhorst 2006 RFS (WP 1999) | brute-force distance search | returns declined steadily (Do & Faff 2010 FAJ); stat-arb crowding and the Aug-2007 quant crash (Khandani & Lo 2011 JFM) | dead (simple version) | M3 liquidity provision, now HFT |
| 18 | Short-term reversal (weekly/monthly) | Jegadeesh 1990 JF; Lehmann 1990 QJE | M1 CRSP | market makers compete it away; OSAP `STreversal` 2015+ 0.38 EW, −0.11 VW | shrunk (microcaps) | M3 liquidity provision |
| 19 | Merger arbitrage | Mitchell & Pulvino 2001 JF | M6 deal database | more capital, tighter spreads; payoff is a short put | shrunk | M6 deal-risk premium with crash risk |
| 20 | Closed-end fund discounts | Lee, Shleifer & Thaler 1991 JF; Pontiff 1996 QJE | M3 | activists narrow discounts; slow and costly to trade | shrunk | M3 noise-trader risk persists |
| 21 | Twin shares (Royal Dutch/Shell) | Froot & Dabora 1999 JFE | M3 | companies unified (2005) | dead | M3 limits to arbitrage |
| 22 | HFT stale-quote latency arbitrage | Budish, Cramton & Shim 2015 QJE; Aquilina, Budish & O'Neill 2022 QJE | M7 message data | arms race: ~0.4 bp "latency tax", winnable only with co-location | alive (for HFT only) | M7 continuous limit-order books |
| 23 | Index/futures basis arbitrage | 1980s program trading | M7 | HFT and ETFs | dead | — |
| 24 | IPO long-run underperformance | Ritter 1991 JF; Loughran & Ritter 1995 JF | M1 event database | concentrated in small growth IPOs (Brav & Gompers 1997 JF); shares hard to borrow; OSAP `IndIPO` 0.34 (0.51 ex-micro) | shrunk | M4/M3 persists |
| 25 | IPO first-day underpricing | Ibbotson 1975 JFE | event database | not an edge for outsiders (allocation access) | alive but inaccessible | M3 allocation |
| 26 | SEO / issuance underperformance | Loughran & Ritter 1995 JF; Pontiff & Woodgate 2008 JF | M4 | OSAP issuance family is a top survivor (2015+ 0.5–0.9) | alive | M4 manager market timing |
| 27 | Stock-split drift | Ikenberry, Rankine & Stice 1996 JFQA | event study | vanished once momentum/frictions controlled (Boehme & Danielsen 2007 JFQA) | dead | — |
| 28 | Dividend initiations/omissions | Michaely, Thaler & Womack 1995 JF | event study | OSAP `DivOmit` 2015+ 0.82 but mostly microcaps | shrunk (microcaps) | M4 |
| 29 | Dividend-month premium | Hartzmark & Solomon 2013 JFE | M2 dividend-seeking demand | OSAP `DivSeason` 0.62 all, 0.12 ex-microcap | shrunk | M2 income-seeking flows |
| 30 | Google-Trends trading | Preis, Moat & Stanley 2013 Sci. Rep. | M1 new data, keyword search | keyword data-mining; out-of-sample failures (Challet & Bel Hadj Ayed 2014, arXiv) | dead | attention effects are short-lived and reverse (Da, Engelberg & Gao 2011 JF) |
| 31 | Twitter mood predicts the DJIA | Bollen, Mao & Zeng 2011 J. Comp. Sci. | M1 text | failed replication (Lachanski & Pav 2017, Econ Journal Watch) | dead | — |
| 32 | News/text tone | Tetlock 2007 JF; Loughran & McDonald 2011 JF | M1 text | vendors (RavenPack) made it standard; short half-life | shrunk | LLM-based text is the new wave (Lopez-Lira & Tang 2023) |
| 33 | Leveraged-ETF close rebalancing | Cheng & Madhavan 2009 JIM; Shum et al. 2016 | M2 mechanical flows | some evidence the impact is small or offset (Ivanov & Lenkey 2018 JFM) | disputed | M2 flow has grown with LETF AUM (**being tested**) |
| 34 | Month-end balanced/pension rebalancing | Harvey, Mazzoleni & Melone 2025 NBER | M2 | too new to have decayed | alive (new) | M2 (**being tested**) |
| 35 | Options pinning at expiration | Ni, Pearson & Poteshman 2005 JFE | M2 dealer hedging | market makers now anticipate it; weekly/daily expiries spread it out | shrunk | M2 dealer gamma, now 0DTE |
| 36 | 0DTE-driven intraday dynamics | 2022+ market structure | M7 | early evidence finds no systematic volatility amplification (Dim, Eraker & Vilkov 2024, SSRN) | unresolved | M7 new structure (forward test only) |
| 37 | Commodity index roll ("Goldman roll") | Mou 2011 WP; Stoll & Whaley 2010 | M2 index roll schedule | roll costs small by the 2010s as providers spread and randomised rolls (Bessembinder, Carrion, Tuttle & Venkataraman 2016 JFE) | shrunk | M2 flow smaller and spread out |
| 38 | Treasury auction cycle | Lou, Yan & Zhang 2013 RFS | M2 dealer supply absorption | still found through 2016 ([Herb 2025 JBF](https://ideas.repec.org/a/eee/jbfina/v170y2025ics0378426624002309.html)); deficits keep growing | alive | M2 dealer balance-sheet limits |
| 39 | FX 4 pm WM/Reuters fix | Evans 2018 JIMF | M2/M7 | fix-rigging scandal; window widened from 1 to 5 minutes in 2015 | dead | regulation |
| 40 | Covered-interest-parity deviations | Du, Tepper & Verdelhan 2018 JF | M7 post-2008 bank regulation | persists: bank balance-sheet costs | alive (banks only) | M7 |
| 41 | Time-series momentum / trend | Moskowitz, Ooi & Pedersen 2012 JFE | M6 | weak after 2012 (Huang, Li, Wang & Zhou 2020 JFE question it); our test is a vacuous null | shrunk | M6/M4 |
| 42 | Short-vol ETPs (XIV) / VIX roll yield | Whaley 2013; Bollen, O'Neill & Whaley 2017 | M6 variance risk premium | "Volmageddon", 5 Feb 2018: XIV lost ~90% in one day | alive but crash-prone | M6; the premium is real, the crash is the price |

### Patterns from the catalogue

- **Calendar and pure-pattern edges found by sorting (1, 2, 3, 5, 7, 30, 31) die fastest.** They
  had no identifiable counterparty, so nothing kept them alive once published.
- **Forced flows die when the event becomes predictable to arbitrageurs** (S&P inclusion, Russell,
  commodity index rolls, FX fix): the flow did not shrink; liquidity providers moved in ahead of it.
  **They survive when the flow grows faster than dedicated capital and is too small or dull for big
  funds** (Treasury auctions, month-end rebalancing, possibly LETF).
- **Risk premia do not die, they crash** (merger arb, short vol, carry, momentum). This matches the
  OSAP skewness result: negative-skew spreads survive.
- **New-data edges last until the data is standard** (IBES revisions, RavenPack text, OptionMetrics).
  OPRA-derived signals are still costly to build; that is our best information edge.
- **Microstructure edges (22, 23, 40) are alive but only for balance-sheet or co-location owners.**
  Not for a $100k account.

## Sources checked on 2026-09-19

- [Greenwood & Sammon, *The Disappearing Index Effect*, JF 2025](https://onlinelibrary.wiley.com/doi/10.1111/jofi.13410)
- [Kurov, Wolfe & Gilbert, *The Disappearing Pre-FOMC Announcement Drift* (SSRN 3134546)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3134546)
- [Lou, Yan & Zhang, *Anticipated and Repeated Shocks in Liquid Markets*](https://personal.lse.ac.uk/loud/Shocks.pdf); [Herb, *The Treasury auction risk premium*, JBF 2025](https://ideas.repec.org/a/eee/jbfina/v170y2025ics0378426624002309.html)
- [Heitz, Narayanamoorthy & Zekhnini, *The Disappearing Earnings Announcement Premium* (SSRN 3296537)](https://www.ssrn.com/abstract=3296537)
- [Madhavan, *The Russell Reconstitution Effect*, FAJ 2003](https://www.hillsdaleinv.com/uploads/The_Russell_Reconstitution_Effect,_Ananth_Madhaven,_Financial_Analysts_Journal,_JulyAugust_2003,_Pages_51-64.pdf)
- [Chen, Lopez-Lira & Zimmermann, *Does Peer-Reviewed Research Help Predict Stock Returns?* (arXiv 2212.10317)](https://arxiv.org/abs/2212.10317)
- [Loh & Warachka, *Streaks in Earnings Surprises and the Cross-Section of Stock Returns*, Management Science 2012](https://pubsonline.informs.org/doi/10.1287/mnsc.1110.1485)
- Data: Chen & Zimmermann, Open Source Asset Pricing, release 2025-10 (openassetpricing.com; `openassetpricing` Python package).
