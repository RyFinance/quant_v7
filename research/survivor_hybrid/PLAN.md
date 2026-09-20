# Survivor hybrids of published anomalies (OSAP): pre-registration

Written 2026-09-19 by a tester agent, before any 2015+ return of any hybrid, control or component
was computed in this study. Question: a single published anomaly is worth about 0.1–0.2 Sharpe after
2015 (`reports/edge_graveyard/REPORT.md`). Does a pre-registered combination of many weak,
low-correlation survivors, **selected only on data through 2014-12**, still clear a useful bar
out of sample, net of a cost haircut?

## Seen before writing (disclosed)

- **The evaluation window is partly contaminated.** The graveyard study (`reports/edge_graveyard/`)
  already reports 2015–2024 statistics for every predictor (`predictor_decay.csv`); averages by
  mechanism, data source and category; the strongest 2015+ survivors (Tables 11–12); and the
  2015–2024 Sharpe of an equal-weight blend of all 212 predictors (1.38 gross; 0.86 ex-microcap;
  0.38 value-weighted). This composite was never computed, but its ingredients' 2015+ performance was
  visible when this rule was written. The rule follows the coordinator's example rather than
  anything tuned on 2015+ data. Several of the strongest 2015+ survivors in those tables were
  published after 2009: SmileSlope, dCPVolSpread, EarningsStreak, GP, dVolCall, OrgCap, OperProfRD
  and roaq. Rule 1 excludes them all.
- **Coverage check on pre-2015 data only:** the rule below was run on series truncated at 2014-12
  (`evaluate.py select`) and gives 53 survivors. No threshold was changed after the check.

## Data

- OSAP release 2025-10, already on disk in `data/osap/` from the graveyard study (no new download):
  - `SignalDoc.csv`: 212 predictors;
  - monthly long-short returns: `ls_op` (original-paper method), `ls_me_gt_nyse20` (stocks above the
    NYSE 20th size percentile, "ex-microcap"), `ls_q5_vw` (quintile spread, value-weighted).
  - Returns end 2024-12.
- Market: French daily Mkt-RF and RF (`reports/higher_sharpe/inputs/french_daily.zip`, through
  2026-07), compounded to calendar months.
- Mechanisms: `research/edge_graveyard/tags.py`, which implements the taxonomy in
  `research/EDGE_GRAVEYARD_PLAN.md`. Tags come from Chen–Zimmermann's `Cat.Economic` plus hand
  overrides, and were assigned without looking at returns.

## Selection rule (fixed; data through 2014-12 only)

A predictor is a survivor if all four hold:

1. **Published before 2010** (`Year` ≤ 2009), so there are at least 5 post-publication years before
   2015.
2. **Post-sample evidence, all stocks.** The original-paper long-short return from January of
   `SampleEndYear`+1 to 2014-12 has t = mean/sd·√n ≥ 2.0, with n ≥ 36 months.
3. **Not dead after publication.** The same series' mean from January of `Year`+1 to 2014-12 is
   > 0 (n ≥ 36).
4. **Large-cap relevance.** The ex-microcap version over the same post-sample window as rule 2 has
   t ≥ 1.0 (n ≥ 36).

`core.select_survivors` truncates every input at 2014-12-31 before computing anything, and the tests
check this.

**Result (pre-2015 only):** 53 of 212 predictors.
- 165 pass rule 1 and 57 pass rules 1–3. Rule 4 removes DolVol, RDIPO, RevenueSurprise and
  STreversal.
- The list is fixed in `reports/survivor_hybrid/survivors.csv`, sha256
  `4f8aa144a60ebee29bcf8bfc2ac21045bd29777c57b5915f53c6cd0cceee86c4`.

| mechanism | n | survivors |
|---|---|---|
| M1 new data | 2 | IO_ShortInterest, CPVolSpread |
| M2 forced flows / seasonality | 5 | MomSeason06YrPlus, MomSeason11YrPlus, MomSeason16YrPlus, MomOffSeason06YrPlus, ExchSwitch |
| M3 limits to arbitrage | 2 | ShortInterest, VolumeTrend |
| M4 slow reaction | 24 | AgeIPO, Accruals, AnalystRevision, AnnouncementReturn, ChangeInRecommendation, CompEquIss, CompositeDebtIssuance, ConsRecomm, DebtIssuance, DelFINL, DownRecomm, EarningsSurprise, GrSaleToGrInv, IndIPO, IndMom, MS, NetDebtFinance, PS, REV6, ShareIss1Y, ShareIss5Y, Tax, UpRecomm, XFIN |
| M5 economic links | 1 | IndRetBig |
| M6 risk premia | 19 | AccrualsBM, AdExp, BM, BMdec, ChInv, ChInvIA, CoskewACX, DelEqu, DelLTI, DivYieldST, dNoa, EP, Frontier, LRreversal, MRreversal, NetPayoutYield, OperProf, RD, SP |

- Data source: accounting 30, price 10, analyst 6, event 3, volume 2, options 1, 13F 1.
- Holding period (`Portfolio Period`): monthly 27, plus 1 undocumented treated as monthly;
  6-month 1; annual 24.

## Hybrids (fixed)

Each hybrid is a portfolio of component long-short returns, with weights summing to 1 each month.
Each component is $1 long and $1 short per $1 of capital. A component with no return in a month
is skipped and the other weights are renormalised; availability is known when the portfolio is
formed. Weights for month t use only returns from months before t.

- **H1:** equal weight of the 53 survivors' original-paper (op) returns.
- **H2:** inverse volatility, w_i,t ∝ 1/σ_i,t. σ comes from op returns in months t−36 … t−1
  (at least 24 observations, otherwise the component is skipped that month).
- **H3:** large-cap versions only, equal weight. Each survivor enters as its VW quintile spread
  (44 survivors). Where no VW quintile series exists, it enters as its ex-microcap version (9
  discrete signals: ExchSwitch, DownRecomm, UpRecomm, ConsRecomm, DebtIssuance, MS, IndIPO,
  AccrualsBM, DivYieldST).
- **H4:** six mechanism groups (M1–M6).
  - Within a group: equal weight of op returns.
  - Across groups: inverse trailing 36-month volatility of each group's return, i.e. equal risk,
    ignoring correlations.
  - Single-member groups (M5 = IndRetBig) still get a full group share.

## Cost haircut (fixed)

OSAP does not document turnover.
- **Per component, per month:** haircut = R × m(PP), where PP is the paper's holding period in months.
  - m = 1 if PP ≤ 1 or PP is missing;
  - m = 1/2 if PP = 3;
  - m = 1/3 if PP ≥ 6.
- **R:** 30 bps base, with 20 and 40 bps as sensitivities. This is the coordinator's range of 20–40
  bps a month for monthly rebalances.
- **Why m falls more slowly than 1/PP:** equal-weight portfolios are re-weighted every month, and
  short-borrow fees accrue monthly.
- **Hybrid haircut** = Σ w_i·c_i. Averaged over the 53 survivors it is 20.6 bps/month at base
  (13.7 low, 27.4 high), about 2.5%/yr.

Not modelled:
- netting of trades across components, which would lower costs;
- extra turnover from H2/H4 weight changes, which is small;
- microcap spreads in the op versions. For equal-weight all-stock monthly signals, even 40 bps is
  probably optimistic (Novy-Marx & Velikov 2016).

## Window

2015-01 → 2024-12, the last month in the OSAP 2025-10 release: 120 monthly returns. It is evaluated
once.

## Gates (per hybrid; a hybrid passes only if all three hold)

1. **Net Sharpe ≥ 0.75**, net of the base haircut (R = 30).
   - Sharpe = mean/sd·√12 of monthly net returns.
   - The long-short returns are self-financing, so no risk-free rate is subtracted.
2. **Lower bound of the 95% interval > 0.** Circular-block bootstrap from
   `research/common/inference.py` `sharpe_ci`: periods = 12, 6-month blocks, 5,000 draws, default seed.
3. **Deflated Sharpe probability ≥ 0.95** (`deflated_sharpe`).
   - N = 84 trials: about 80 project trials before this study, plus these four.
   - Trial Sharpe variance = 0.25/12 per month, an annual cross-trial SD of 0.5. This follows the
     convention in `research/letf_rebalancing/evaluate.py`. The within-run variance of four hybrids
     built from the same components would understate the dispersion of the project's ledger.
   - With 120 roughly normal months, this gate needs an annual net Sharpe of about 1.76. It is meant
     to be the binding gate.

The study passes if any hybrid passes. A pass leads only to a survivorship-free rebuild and a forward
paper test, never to capital. No rule, cost or gate changes after results. If a bug is found after
the run, the fix and its effect are disclosed.

## Reported, not gated

- **Sharpe variants:** gross Sharpe, net at R = 20 and 40, annual mean and volatility.
- **Interval reading:** `null_kind` at 0.5 (project convention) and at 0.75.
- **Risk:** compounded max drawdown (net and gross), worst month, skew, excess kurtosis.
- **Market:** correlation, beta and CAPM alpha (t) against Mkt-RF.
- **Stability:** 2015–2019 and 2020–2024 Sharpes, and net return by year.
- **Costs:** break-even R for a net Sharpe of 0.75 and of 0; average number of components and
  haircut.
- **Correlations** among the hybrids, the controls and the market.
- **DSR sensitivities:** N = 80; within-run variance; sampling variance 1/(T−1).
- **Selection-period context:** 2005–2014 Sharpe. This is in-sample and biased upward by selection.
- **Controls:**
  - C0 = equal weight of all 165 predictors published ≤ 2009 (op, no survival filter);
  - C0_LC = their large-cap versions;
  - the market's Sharpe, for reference.

  The survival filter adds value only if H1 beats C0 and H3 beats C0_LC.
- **Component table:** each survivor's own 2015+ gross and net Sharpe. This is descriptive and
  computed after the hybrids.

## Implementability (descriptive, for the hybrid with the highest base net Sharpe)

- **Haircut** and break-even cost.
- **Rebuildable components.** Which components we could rebuild, judged from the inputs each
  SignalDoc definition needs. Our data:
  - daily OHLCV for 503 current S&P names, 2003+;
  - LSE vault fundamentals, income statement only (EPS, revenue, net income, share counts), for
    about 496 names;
  - LSE dividends for 427 names;
  - OPRA option bars, pull in progress (83 names so far);
  - ETF and futures data.
  - We have no balance sheet, cash-flow statement, IBES, 13F, short interest, IPO or exchange
    history.
- **Survivorship.** Our stock universe is current members only; the same-stock equal-weight control
  scored about 1.0 Sharpe in `reports/fundamentals`. For each rebuildable component, state the
  direction of the bias:
  - if the short leg holds the higher ex-ante failure risk, the bias works against the signal;
  - if the long leg holds distressed, cheap or loser stocks, the bias works for it.

  A component is recommended only where the bias is neutral or works against it. Otherwise a
  survivorship-free database is needed.

## Expectations stated in advance

- Gross H1 near the known 1.38 of the all-predictor blend, or somewhat higher, with C0 close to it.
  H3 much lower: VW spreads averaged 0.07 in 2015+.
- A haircut of about 2.5%/yr is large next to the mean of a diversified long-short composite.
  Expected net H1: 0.3–0.9.
- Prior: no hybrid passes. The DSR gate binds, and H3 is near zero or negative net.

## Code, tests, outputs

- `research/survivor_hybrid/core.py`: selection, weights and haircut.
- `research/survivor_hybrid/evaluate.py`: `select` uses pre-2015 data only; `run` refuses to start
  unless this file's sha256 is registered.
- `tests/test_survivor_hybrid.py`: 10 tests covering the selection's blindness to post-2014 data,
  trailing-only weights, the haircut, the equal-risk grouping and the registration guard.
- `reports/survivor_hybrid/`: `survivors.csv`, `results.json`, `returns_oos.csv`,
  `components_oos.csv`, `REPORT.md`.
