# Edge search: 18 September 2026

**Result: no qualified edge from seven new candidates and one fixed, unoptimized ETF blend.** No live strategy was changed. No post-2017 returns were evaluated by these experiments.

## Work actually executed

- Authenticated London Strategic Edge vault usage and catalog requests succeeded through the existing client. No terminal MCP tool was exposed. The provider is London Strategic Edge, not LSEG. Actual account limits were 50 GiB/month, 15 GiB/week, 200 calls/minute, two concurrent requests.
- Pulled 158,950 hourly observations for EUR/USD, GBP/USD and USD/JPY, covering October 2009 through December 2017, plus a five-minute timestamp check. Pull consumed about 18.2 MB of metered data. Input hashes are recorded locally; licensed price files are ignored by Git.
- Verified that one-hour OHLC matches aggregation of five-minute bars with left-labeled timestamps on the checked day. This verifies aggregation consistency, not historical executable bid/ask quotes.
- Registered FX rules before calculating candidate returns. Registered the separate four-pair ETF experiment before its returns. Signal definitions and cost assumptions were not optimized after viewing their results.
- Used development 2010–2013 and validation 2014–2017 for FX; development 2008–2013 and validation 2014–2017 for ETF spreads. Earlier project experiments have already used these broad market dates, so these are exploratory chronological checks, not pristine holdouts.

## Results

FX ratios use zero cash interest and zero risk-free subtraction: they are trading return/volatility ratios, not conventional excess Sharpe. ETF ratios use excess returns over French daily RF and assume free cash earns RF. Do not compare these two definitions as if identical. All ratios below include the stated trading costs.

| Candidate | Development ratio | Validation ratio | Validation CAGR | Daily max drawdown | Stressed ratio |
|---|---:|---:|---:|---:|---:|
| london_reversal | -0.35 | -0.92 | -1.30% | -5.76% | -2.10 |
| new_york_continuation | -1.98 | -0.84 | -1.38% | -6.34% | -1.96 |
| london_fix_reversal | -3.02 | -5.14 | -16.95% | -53.72% | Insolvent |
| SPY_QQQ | -0.22 | -0.27 | -0.44% | -2.87% | -0.91 |
| GLD_SLV | -0.30 | 0.14 | 0.31% | -5.93% | -0.22 |
| EFA_EEM | -0.52 | 0.23 | 0.70% | -4.17% | -0.05 |
| LQD_IEF | -0.05 | -2.31 | -2.31% | -9.31% | -4.13 |
| fixed_blend | -0.58 | -0.39 | -0.48% | -2.93% | -1.45 |

## What failed and why

The London reversal had development gross return/volatility of 0.61, but net was −0.35. Its validation gross ratio was only 0.15 and net was −0.92. The two signal FX strategies paid approximately 1.5–1.6% of NAV per year in validation costs. The fixing strategy traded far more frequently, paying about 18.6% annualized cost drag in validation as a fixed minimum commission consumed an increasing fraction of the declining account. Its stressed simulated account exhausted capital. It is rejected, not a short-volatility or leverage opportunity.

The ETF pair selected strictly on development was LQD/IEF, despite even its development excess Sharpe being negative. Its validation excess Sharpe was −2.31. EFA/EEM happened to be the strongest later-period pair at 0.23, but it was not the development-selected candidate and becomes negative under stressed costs. Selecting it after seeing validation would be another data-dependent trial. The fixed four-pair allocation also failed.

## Costs and execution

FX: illustrative $100,000 starting account; each active pair receives one third of beginning-of-day NAV, no redistribution of unused allocation. Spread/slippage 0.5 bp per side plus commission of max($2, 0.2 bp per order), charged on entry and exit. Stress doubles/triples both components. USD/JPY P&L is converted from JPY to USD at the exit rate. All positions exit intraday; daily NAV includes every trade and fee. No overnight carry is credited. Broker terms are unverified; there are no bid/ask fills or empirical impact estimates.

ETFs: total-return adjusted cached OHLC; close decisions and next-open fills, daily marks, fixed units between entry and exit. Individual pair gross target is 1, with no leverage scaling. Base 10 bps round trip and 3% annual short borrow; stress 25 bps and 10% borrow. Cash earns French RF on free cash, with no rebate on short collateral. Costs do not include minimum ticket commissions, taxes, fixed data costs or broker financing spreads. These omissions can make results optimistic; the candidates failed even under these assumptions.

## Inference and audit trail

Both selected candidates failed their predeclared gates. The FX gate required development ratio ≥0.5, validation ≥0.75, positive stress mean, all three pairs positive, and three-test Bonferroni p<0.05. The ETF gate required development excess Sharpe ≥0.5, validation ≥0.75, positive stress mean, and four-test Bonferroni p<0.05. Centered circular block bootstrap used 5,000 draws, blocks of 20 days with 63-day sensitivity. Family-level corrections do not account for the broader historical project search. No gate failure was repaired by reversing the signal or changing the threshold.

One operational amendment followed a missing Boxing Day entry bar in the fixing strategy, before that strategy P&L was calculated: orders with no entry price are recorded as unfilled; a filled position without an exit price still fails. This uses information observable at entry and does not delete a known losing trade. Original output and code hashes were preserved. Insolvent stressed runs are recorded explicitly, not silently clipped.

## Reproduce

Validation completed: 23 tests passed, covering existing mark-to-market accounting and vault pagination plus FX currency conversion, both-side minimum fees, P&L reconciliation, daylight-saving conversion, and future-data independence of both new signal implementations.

```bash
.venv/bin/python -m research.fx_session_screen
.venv/bin/python -m research.etf_convergence_screen
.venv/bin/python -m pytest tests/test_fx_session_screen.py tests/test_etf_convergence_screen.py tests/test_research_accounting.py tests/test_lse_vault.py -q
```

FX specification: `research/fx_session_spec_20260918.json`; amendment: `research/fx_session_amendment_1.md`; outputs: `reports/fx_session_20260918/`.

ETF specification: `research/etf_convergence_spec_20260918.json`; outputs: `reports/etf_convergence_20260918/`. Every candidate has daily NAV and return paths; FX candidates also have a trade/cost ledger. Code hashes, input hashes and registration times are saved.

Literature used to motivate FX hypotheses: Breedon and Ranaldo (2013), https://onlinelibrary.wiley.com/doi/10.1111/jmcb.12032 ; Krohn et al. (2024), https://onlinelibrary.wiley.com/doi/10.1111/jofi.13306 . These experiments are independently specified variants, not claimed replications or undiscovered effects.

No method in this batch merits promotion to paper trading. The infrastructure and failed-trial record are retained; no live settings, production risk gates or existing research results were overwritten.
