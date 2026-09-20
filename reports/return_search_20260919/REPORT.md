# Broad return search: completed results, 19 September 2026

**Strongest return candidate: long-only stock momentum.** It returned 36.22% annually with 1.00 excess Sharpe in the continuous 2019–September 2026 record. The longer 2008–2026 extension returned 22.52% with 0.80 Sharpe and a 57.64% maximum drawdown. The stock universe consists of current listed names, so survivorship remains an unresolved limitation. These are simulated results, not a claim of a proven new anomaly.

The higher recent Sharpe candidate was cross-asset ETF momentum: 1.51 Sharpe and 59.85% annualized return in July 2025–September 2026. Its full 2008–2026 history was much weaker: 5.61% return and 0.31 Sharpe. The recent number must not be substituted for that longer record.

## What was tested

Twenty fixed candidates, four passive controls. No parameter grid or evaluation-period retuning. Seven stock candidates, seven ETF candidates, four BTC/ETH candidates and two volatility-product candidates. Learned models used annual expanding-window training, matured-label purges, and fixed ridge/gradient-boosting hyperparameters. Training included up to 175,625 earlier stock observations per annual fit. Price, volume and volatility fields were tested; enriched models also used options-volume fields for the 46 available underlyings, VIX structure, yield slope and credit/market trends. More features and learning did not beat the simple stock-momentum rule in the selection period.

The LSE Terminal MCP connection and data catalog were checked and saved. Historical options data came from the LSE vault. Official-session adjusted equity/ETF prices and continuous crypto aggregate daily prices came from the project cache. No demo/synthetic prices or broker execution were used. Revised macro data and insufficient insider history were excluded. Prior COT, FX, intraday and option-writing studies remain separate recorded trials; this run does not claim to test every conceivable market or field.

## Exact candidate rules

**Stock momentum**

1. On the first trading session close of each month, retain stocks with at least 252 sessions of history and finite price features.
2. Require trailing 63-session average dollar volume above $20 million and rank within the top 200 by that liquidity measure.
3. Score each stock as adjusted close 21 sessions ago divided by adjusted close 252 sessions ago, minus one. This skips the latest month.
4. Buy up to 20 positive-score leaders at 5% target weight each. Unused slots stay in cash.
5. Execute at the next session open, hold actual share units between monthly decisions, and mark positions daily. No shorts or leverage.

**ETF momentum** uses the same skipped-month score across the fixed cached ETF universe, selecting up to four positive leaders at 25% each. It covers international and US equities, bonds, credit, real estate, commodities and currencies.

## Chronology and selection

- Annual prediction and selection window: 2019-01-01 through 2025-06-30. Each model was fitted only to labels that ended before its prediction year.
- A selection file was written before evaluation. Stock momentum and ETF momentum were the selected winners in their respective families.
- The originally selected overall candidate subject to the preset risk limits was crypto breakout. **It failed evaluation**. The report does not retroactively replace that primary with the better-looking ETF result.
- Before evaluation, a documented reporting extension also froze the highest-returning strategy and highest-returning fitted model, without the risk limits. Both were crypto candidates. They failed to reproduce their earlier returns.
- Evaluation: 2025-07-01 to 2026-09-17, approximately 14.6 months. These dates were withheld from this selection process, but the wider project had previously used some of this history.
- Continuous 2019–2026 results, the backward 2008–2018 extension, execution-delay tests and asset-omission tests are post-evaluation diagnostics. They are not new model-selection opportunities or pristine holdouts.

## Final-period evaluation

Annualized return can look large over 14.6 months; total return is shown alongside it.

| Frozen candidate / control | Net total return | Net annualized return | Excess Sharpe | Max DD | Stress annualized return |
|---|---:|---:|---:|---:|---:|
| stocks__momentum | 91.33% | 70.63% | 1.29 | -33.42% | 69.40% |
| etf__momentum | 76.75% | 59.85% | 1.51 | -19.18% | 59.04% |
| fixed_blend | 37.59% | 30.00% | 1.08 | -12.10% | 28.87% |
| crypto__breakout | -1.56% | -1.29% | -0.13 | -21.43% | -2.78% |
| crypto__trend | -0.49% | -0.40% | 0.03 | -36.20% | -1.78% |
| crypto__ridge_price | -2.12% | -1.75% | 0.13 | -54.09% | -3.19% |
| crypto__passive | -14.95% | -12.46% | -0.07 | -60.10% | -13.12% |
| etf__passive | 21.72% | 17.57% | 1.42 | -4.64% | 17.33% |
| vol__passive | 49.38% | 39.16% | 1.21 | -22.94% | 38.71% |

SPY and QQQ passive controls over the same final period earned 20.16% and 24.85% annualized respectively. Their excess Sharpes were 1.25 and 1.09.

## Longer descriptive record

| Strategy | Window | Net CAGR | Excess Sharpe | Max DD |
|---|---|---:|---:|---:|
| stocks__momentum | 2019–2026 | 36.22% | 1.00 | -35.50% |
| stocks__momentum | 2008–2026 | 22.52% | 0.80 | -57.64% |
| etf__momentum | 2019–2026 | 17.22% | 0.72 | -42.81% |
| etf__momentum | 2008–2026 | 5.61% | 0.31 | -47.69% |
| SPY passive | 2008–2026 | 11.23% | 0.57 | -52.41% |
| QQQ passive | 2008–2026 | 16.10% | 0.72 | -50.06% |

## Execution and robustness

All reported portfolio returns mark open positions daily and include final liquidation. Stock/ETF base costs are 5bps per side, stressed to 15bps. Crypto costs are 20bps per side, stressed to 50bps, with an extra full intervening day before execution. Volatility ETF costs are 10bps per side, stressed to 30bps. All portfolios are fully funded, so no short borrow or debit financing is needed. Cash earns the prior observable IRX rate over elapsed days. Adjusted fund returns include distributions and embedded fund expenses. Taxes, account-specific fees, capacity and measured broker fills are not established by this simulation.

A full extra session of delay plus tripled stock/ETF costs left stock momentum at 66.39% annualized return / 1.24 Sharpe in evaluation, and ETF momentum at 57.67% / 1.47. This reduces concern that the results rely on an exact next-open fill. It does not establish realized execution quality.

Removing one at a time the three most frequently allocated stocks left evaluation CAGR between 62.47% and 66.76%. Removing the equivalent ETFs left 39.94% to 51.55%. Removed slots stayed cash; no weights were reoptimized. The leading average ETF allocations were silver, South Korea equities and gold, so this remains materially dependent on the recent asset regime.

Seven focused tests passed: funded accounting and fees, full-day crypto delay, missing held-price failure, cash-slot sizing, initial-loss drawdowns, causal features under future perturbation, and annual training-label purges.

## What remains unproven

The stock list is current-member and survivor biased. Historical holdings were chosen from past prices and liquidity, but the database lacks the full historical investable universe with delisted names. That prevents calling the stock result a clean point-in-time validation. The 2008–2026 stock drawdown is 57.64%, substantially deeper than the selection-window drawdown.

The final evaluation is short. Twenty-session block bootstraps give wide uncertainty intervals, and alpha confidence intervals against SPY and QQQ include zero for both momentum candidates. The strongest conclusions are that these are reproducible higher-return candidates and their recent results survive modeled cost/delay stress—not that a durable undiscovered alpha has been statistically established. Project-wide multiple testing is not erased by this run.

The stock passive control stopped on a missing FISV open/close for 2025-11-12. A fresh Yahoo query confirmed the absent bar. No price was invented or forward-filled in execution. The selected stock strategy had no exposure to that missing bar and completed normally. SPY and QQQ provide complete additional passive comparisons.

## Full earlier-period trial ledger

| Candidate / control | 2019–June 2025 net CAGR | Excess Sharpe | Max DD | Stress CAGR |
|---|---:|---:|---:|---:|
| crypto__passive | 66.32% | 1.05 | -76.37% | 65.55% |
| crypto__trend | 54.29% | 1.03 | -67.81% | 52.55% |
| crypto__ridge_price | 46.04% | 0.88 | -76.37% | 44.50% |
| stocks__momentum | 30.66% | 0.93 | -35.50% | 29.63% |
| stocks__ridge_price | 28.80% | 0.81 | -46.97% | 27.24% |
| stocks__ridge_enriched | 28.51% | 0.83 | -50.62% | 26.78% |
| stocks__boost_price | 26.80% | 0.75 | -52.71% | 25.16% |
| stocks__trend | 25.03% | 0.93 | -32.17% | 23.73% |
| crypto__breakout | 21.71% | 0.69 | -46.26% | 19.11% |
| crypto__boost_price | 21.55% | 0.59 | -73.17% | 18.79% |
| stocks__boost_enriched | 21.47% | 0.65 | -47.65% | 20.28% |
| stocks__passive | 19.13% | 0.81 | -38.33% | 19.01% |
| vol__passive | 11.65% | 0.42 | -62.19% | 11.58% |
| stocks__breakout | 10.71% | 0.50 | -27.06% | 8.76% |
| etf__momentum | 10.57% | 0.49 | -42.81% | 9.74% |
| etf__ridge_price | 8.77% | 0.39 | -28.98% | 7.22% |
| vol__contango | 8.28% | 0.33 | -52.72% | 6.16% |
| etf__passive | 6.66% | 0.41 | -22.24% | 6.58% |
| etf__boost_enriched | 6.11% | 0.27 | -37.98% | 4.83% |
| etf__boost_price | 5.87% | 0.26 | -40.02% | 4.45% |
| vol__contango_trend | 3.88% | 0.20 | -53.89% | 1.53% |
| etf__breakout | 3.76% | 0.16 | -26.19% | 2.26% |
| etf__trend | 3.15% | 0.11 | -25.90% | 2.20% |
| etf__ridge_enriched | 2.99% | 0.10 | -29.81% | 1.14% |

## Artifacts

- [Original protocol](../../research/return_search/PLAN.md)
- [Frozen selection](selection.json)
- [Return-leader reporting extension](../../research/return_search/EVALUATION_EXTENSION.md)
- [Final evaluation](evaluation/results.json)
- [Return-leader evaluation](secondary_evaluation/results.json)
- [Execution and concentration diagnostics](diagnostics/results.json)
- [Full historical extension](diagnostics/long_record.json)
- [Frozen paper-research specifications](paper_candidates.json)

Daily NAV, targets, costs, data fingerprints and training audits are saved beside these reports. No live strategy or account was changed.
