# The edge graveyard: learn how old edges were found and why they died, then reuse the methods

Written 2026-09-19. This is a research plan; no experiment is registered by this file.

## Why this approach

Published anomalies lose about a third of their return out of sample and about half after
publication (McLean & Pontiff 2016). Most US anomalies stopped working after about 2003 (Green,
Hand & Zhang 2017; Chordia, Subrahmanyam & Tong 2014). Our own record agrees: every textbook edge we
re-tested came back at 0–0.5. Re-testing famous edges is therefore the least productive search there
is. The productive question is **which mechanisms produce edges that survive, and where those
mechanisms are still at work today**.

## Phase 1: the graveyard study (evidence on what survives)

**Data:** Open Source Asset Pricing (Chen & Zimmermann, October 2025 release; `pip install
openassetpricing`):
- 212 published stock-return predictors, with monthly long-short returns through 2024-12;
- each predictor's original-paper sample period and publication date;
- predictor categories.

This is free, CRSP/Compustat-based, and nothing like it exists in the project.

**Work:**
1. For every predictor, split returns into three periods: inside the original sample, after the
   sample ends but before publication, and after publication. Measure the decay, including a 2015+
   slice.
2. Tag each predictor by **mechanism** (the taxonomy in Phase 2), **data source** (price, accounting,
   analyst, options, text, flows), **turnover**, **small-cap concentration** (capacity) and **crash
   risk**.
3. Regress post-publication survival on those tags to find which kinds of edges keep working, and
   in what kind of stock.

**Output:** `reports/edge_graveyard/`, with the decay table, a survival model and a "where edges
live" map.

**Guardrail:** this is meta-evidence. The academic long-short returns are not strategies we can
trade (CRSP universe, no costs, microcaps included). No trading decision comes straight from them.

A companion literature catalogue covers edges outside the cross-section, about 40 entries. For each:
discovery year, publication year, the discovery method, and what killed it. Examples:
- calendar effects, the small-firm effect, S&P 500 inclusion pops;
- pre-FOMC drift, overnight/intraday, pairs trading, closed-end fund discounts, merger-arb spreads;
- stale-quote/HFT latency arbitrage;
- analyst revisions, accruals, PEAD in large caps;
- Google-Trends and Twitter sentiment signals.

## Phase 2: taxonomy of discovery methods

| Method | Classic discoveries | What usually killed them |
|---|---|---|
| M1 First to a new dataset | size & value (CRSP), accruals (Compustat), PEAD & revisions (IBES), order flow (TAQ), option signals (OptionMetrics), text (EDGAR) | the data became standard, so everyone ran the same sorts |
| M2 Forced, non-informational flows | index inclusion, mutual-fund fire sales (Coval–Stafford), month-end rebalancing, LETF rebalancing, dealer hedging | front-running; sometimes the flow grew faster than the arbitrage, so these can survive |
| M3 Limits to arbitrage | short-sale-constrained, illiquid and lottery stocks | costs; the effect often lives only where big funds can't trade |
| M4 Slow reaction (behavioural) | momentum, PEAD, correlation neglect | faster information and algorithms |
| M5 Economic links diffuse slowly | customer–supplier (Cohen–Frazzini), industry lead–lag | data vendors made the links easy to see |
| M6 Risk premia | carry, variance premium, value | they don't vanish; they crash, and crowding lowers them |
| M7 Changes in market structure | decimalisation, ETFs, 0DTE options, retail apps | the new structure matures and arbitrageurs catch up |

The hypothesis Phase 1 will test: M2 and M3 edges survive publication best, M1 edges last until the
data goes mainstream, and M4/M5 decay fastest.

## Phase 3: apply the surviving methods where they still work (candidates)

Ranked by expected survival × our data access × usable at $100k:

**A. Forced flows (M2): best fit for survival and our data**
1. **Month-end and quarter-end balanced-fund rebalancing** (Harvey, Mazzoleni & Melone, NBER 2025).
   When equities are overweight, rebalancers sell stocks and buy bonds; next-day equity returns fall
   about 17 bps. Implement with ES/ZN (or SPY/IEF) around month ends. The paper is recent (2025), so
   this is the stage when an edge is usually still alive. Data: our daily futures/ETFs. The 2018+
   windows are already used, so the test is on 2003–2017 plus a forward paper test.
2. **Leveraged-ETF close rebalancing.** LETFs must buy after up days and sell after down days in
   proportion to AUM × leverage × return. The pressure lands in the last 30 minutes and has grown
   with LETF assets (TQQQ, SOXL and others). Data: our 30-minute ES/NQ bars plus LETF shares
   outstanding. The paper in the LSE feed on LETF feedback loops (loop gains) is this mechanism.
3. **Index reconstitution:** Russell June reconstitution and S&P additions. Announcement dates come
   from EDGAR or press releases.
4. **Options-expiration pinning and dealer gamma:** needs open interest. The vault's chain snapshots
   (2026+) make it forward-test only.

**B. First to a new dataset (M1)**
1. SEC Form 4 insider clusters: built and registered, blocked on the SEC contact-email decision.
2. OPRA option-implied signals: running now.
3. EDGAR 10-K "Lazy Prices" (Cohen, Malloy & Nguyen 2020): firms whose annual-report language
   changes underperform. Needs the same SEC access.
4. Retail order imbalance from sub-penny trade prices (Boehmer, Jones, Zhang & Zhang 2021). Viable
   only if the LSE stock tick export carries sub-penny prices; check that first, cheaply.

**C. Slow-diffusing links (M5):** customer–supplier momentum from 10-K major-customer disclosures
(SEC access again).

**D. Capacity niches (M3):** Phase 1's survival model shows which anomalies still pay in small caps.
Institutions can't trade those; $100k can. Blocker: our price data has no delisted stocks, so any
test needs a same-universe control and a stated survivorship bias.

## Phase 4: rules, same as every experiment

- Register the plan before results.
- Development runs on a window this project hasn't used, or the signal is new; validation runs once
  and stays locked until it is registered.
- The benchmark is the PEAD excess Sharpe of 0.70 (daily marks, net, excess over T-bills).
- A same-universe no-model control is required.
- The deflated Sharpe is computed against the whole trial ledger (about 60 trials now).
- A pass leads to a forward paper test, never straight to capital. `reports/forward_power/` shows a
  true Sharpe of 2 needs about 1.5 years of forward evidence; about 0.7 needs years.

## Phase 5: order of work

| Step | Work | Needs | Size |
|---|---|---|---|
| 1 | Graveyard study (Phase 1) and the literature catalogue | OSAP download | about half a day |
| 2 | Month-end rebalancing test (A1) | data on disk | a few hours |
| 3 | LETF close-rebalancing test (A2) | LETF shares-outstanding history | about a day |
| 4 | Survival-model-guided small-cap candidates (D) | step 1 results | after step 1 |
| 5 | Insider, 10-K text, supplier links (B1, B3, C) | SEC contact-email decision | after decision |
| 6 | Sub-penny retail-flow feasibility check (B4) | one small tick export | an hour |

Steps 1–3 and 6 can run in parallel as subagents. The OPRA options development run (B2) finishes
separately this afternoon.
