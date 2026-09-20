# Net-of-cost strategy research protocol — draft before data access

Status: research specification only. No new backtest executed; no higher-Sharpe strategy established. Existing performance figures are user-reported and have not been independently reproduced. LSE/LSEG terminal tools are not exposed in this session. The required project knowledge graph and wiki index were absent; raw project files have not been inspected.

## Objective and scope

Find a practical strategy or diversified portfolio whose daily marked, net-of-cost performance improves on the current PEAD strategy on common evaluation dates. Separate improved portfolio efficiency from evidence of stock-selection alpha. Treat every previously inspected period as development evidence, even if earlier reports called it a holdout.

Provisional implementation assumptions, pending user clarification: USD 100,000, no leverage, long-only liquid equities and ETFs. Broker, account currency, tax treatment, shorting and futures permissions remain unknown. These assumptions are not verified account facts. No execution or live configuration changes are authorized by this document.

## Data acceptance before testing

Verify the actual terminal server, callable tools, entitlements, coverage and export limits with a small read-only sample. Record vendor field definitions, extraction time, available history and data vintage. A stated database size does not establish entitlement or point-in-time validity.

Require prices and corporate actions for both active and delisted securities; historical constituent membership; dividends; splits; trading calendars; announcement timestamps and time zones; estimate snapshots available before each release; revisions with publication dates; benchmark total returns; and attainable cash interest. Bid/ask, volume and liquidity records must support execution assumptions. For shorts require historical borrow availability and fees; for futures require individual contracts, contract sizes, settlement, margin and roll schedules. Do not substitute a currently revised consensus or current constituents for historical data.

## Measurement repair and baselines

Reproduce the current strategy before making changes. Reconcile daily cash, position quantities, marked market values, distributions, realized and unrealized P&L, expenses and external flows. NAV must reconcile to the ledger, including marks on non-exit days. Missing prices must not silently become zero returns. Include corporate actions, terminal liquidations and positions spanning evaluation boundaries. Report flow-adjusted daily returns and excess returns over a consistent cash benchmark.

Compare cash, buy-and-hold equities, a static diversified asset portfolio, the existing PEAD strategy, all-earnings entries ignoring the model, and an exposure-matched equity control. Equalize evaluation dates and initial capital; report both actual risk and risk-matched comparisons. Charge the same applicable costs to all controls.

## Small candidate set

1. Diversified slow trend: preselect liquid equity, government-bond, gold and broad commodity exposures based on availability and tradability, not realized performance. Use one fixed 12-month excess-return sign rule, monthly decisions and next-session execution. For the provisional long-only version, negative signals allocate to cash. Allocate across exposures using lagged 63-session volatility, capped at 25% of NAV per exposure and 100% aggregate gross; leave excess in cash. Freeze the exact universe, volatility floor and execution convention before seeing candidate performance. A short-enabled futures version is a distinct experiment and is conditional on account permission and cost data.
2. PEAD residual diagnostic: keep the original signal and holding horizon fixed. Measure returns relative to contemporaneous sector and market controls. If shorting is feasible, test one implementable hedge using lagged beta estimates, with borrow, hedge turnover and financing. A residual-return series alone is not a tradable portfolio.
3. One PEAD extension: earnings surprise plus point-in-time analyst estimate revisions. Fix revision horizon and definition before inspection. Predict sector-relative outcomes; compare a simple rule to the existing model. Exclude this candidate if historical publication timing cannot be established. Do not infer genuine revisions from refreshed consensus snapshots.

Do not run a broad horizon, threshold, model or universe search. Record all variants and failures. A combination of successful sleeves is another registered experiment: use predetermined weights, not weights selected to maximize realized Sharpe.

## Costs and accounting

Model commissions and minimum ticket fees, exchange/regulatory charges, spread crossing on entry and exit, slippage, impact related to order size and available liquidity, currency conversion, financing, borrow and short dividends where applicable. Include roll execution costs for futures without double-counting contract P&L. ETF expenses are generally embedded in observed fund returns and must not be deducted twice. Credit cash at an actually attainable account rate rather than assuming universal access to a theoretical risk-free rate.

Separate variable trading costs from incremental fixed data/platform expenses. Report strategy net returns and account-level economics after allocated fixed expenses. Taxes remain excluded until account jurisdiction and treatment are known; clearly label pre-tax results.

Stress spread/slippage/impact at 2x and 3x the baseline assumptions; stress borrow and financing separately. Report break-even implementation costs. Do not call an arbitrary basis-point deduction an empirical execution model.

## Validation and decision

Inventory all dates, names and results previously used. Freeze candidates, universe, costs and selection rules before evaluating new data. Use chronological expanding-window evaluation with training labels purged where their holding intervals overlap validation/test periods. Any embargo must match the information and holding-period overlap. Reserve a final period only if it truly has not been inspected; otherwise prospective paper trading supplies new evidence.

Evaluate daily net excess-return Sharpe, CAGR, drawdown, turnover, gross/net exposures, factor loadings, net alpha with autocorrelation-robust uncertainty, cost drag and concentration by year, market and event cohort. Use paired block resampling of portfolio returns for the difference versus the baseline, preserving serial dependence and common market shocks. Adjust inferential claims for the recorded candidate search. A collection of positive years is not by itself significance.

Require a positive net excess-return estimate and credible paired improvement on common untouched dates, robustness to cost stress, and acceptable drawdown and account feasibility. Do not claim established superiority when uncertainty spans no improvement. Any promising but inconclusive result remains exploratory. Do not use model probability as a Kelly input without estimating net payoff distributions and estimation uncertainty. Start paper validation with capped risk sizing.

## Required deliverable once access is restored

A reproducible run manifest and data hashes; frozen strategy specifications; complete trial ledger; daily marked NAV and holdings; orders and fill-cost ledger; common-period benchmark table with uncertainty; cost-stress and break-even tables; and a documented go/no-go recommendation for paper trading. Report an honest null result if none qualifies.

## Literature informing hypotheses, not validating this account

- Hurst, Ooi and Pedersen, *A Century of Evidence on Trend-Following Investing*: https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-JPM-Fall-2017.pdf . Long historical, multi-market evidence motivates a trend candidate; its simulated implementation is not equivalent to a small long-only ETF account. The paper acknowledges cost uncertainty and omitted additional futures rolling costs.
- Novy-Marx and Velikov, *A Taxonomy of Anomalies and their Trading Costs*: https://www.nber.org/papers/w20721 . Supports explicitly considering turnover and holding bands when evaluating anomalies after costs. Any holding-band variation here must be registered as an additional experiment.
