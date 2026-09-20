# PEAD config-sweep audit: the true Sharpe

Page: https://claude.ai/artifact/CLTiBRtEQHiqkzS6ixmeqs · code: `research/pead_audit/mtm_audit.py` · numbers: `results.json`

Every `reports/config_sweep` configuration was rebuilt daily from its own ledger: the same trades,
share counts and fills, with each position marked to market every day, the same 10 bps round trip,
and idle cash at T-bills. The rebuilt final NAV equals the bot's to the dollar ($135,411 for 2×),
with zero missing marks.

| 2× sizing (5% positions) | Sharpe |
|---|---:|
| Reported (cash-basis NAV, risk-free 0) | 1.34 |
| Same series, autocorrelation-corrected (Lo 2002) | 0.80 |
| Marked to market daily, risk-free 0 | 0.85 |
| **Marked, idle cash at T-bills, excess over T-bills** | **0.70** [−0.25, 1.70] |
| + stress: 0.5% borrow, 5 bps more a side | 0.64 |
| Control: same trades in the average universe stock | 0.60 |
| Control: same trades in SPY | 0.53 |
| Untouched 2004–2014 pre-registered hold-out | 0.52 |
| Stock selection only (model − universe control) | 0.30 [−0.61, 1.25] |

Live 2.5% configuration: reported 1.44 → true 0.73 [−0.21, 1.74]; selection only 0.44.

Causes:
1. `PaperExecutionClient.nav()` is cash-basis, so open positions are never marked. Volatility shows as
   6.0% instead of 9.6%, and daily returns are autocorrelated (lag-1 0.26).
2. `compute_metrics` defaults the risk-free rate to 0. T-bills averaged 3.6%/yr over the window.
3. The strategy is about 83% long, with beta 0.35. Alpha against the market is 4.2%/yr with t 1.15;
   most of the return is market exposure and survivorship, which the universe control shares.
4. Five configurations were chosen on this same, much-examined window. The deflated-Sharpe
   probability is 0.85 (0.95 needed).

What holds up:
- Costs matter little.
- Entry timing has no look-ahead.

**Benchmark for all future work: PEAD 2× excess Sharpe 0.70** (marked daily, net, excess over
T-bills, 2021-08 → 2025-06). Realistic forward expectation is 0.5–0.7. A challenger must use the same
accounting and also beat the no-model control (0.60).

The sweep lists 8.16%/yr net for 2×. There is no 8.28% figure in the repo.
