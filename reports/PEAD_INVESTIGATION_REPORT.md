# PEAD / Customer-Supplier Spillover Investigation

Follow-up to the Phase 7 no-go on the graph-clustering mean-reversion strategy. Tests a genuinely different mechanism (post-earnings-announcement drift) with the same rigor: real data only, chronological splits, 3 disjoint holdouts, majority-baseline comparison, realistic transaction costs, honest verdict.

## 1. Data feasibility research (done first, as instructed)

**Perplexity finance connector**: checked the connector registry directly — **not installed, not found**. The spec assumed it would be available; it is not, in this environment. Documented, not worked around.

**What is actually available and used**: yfinance's `Ticker.get_earnings_dates()` — confirmed empirically to return real EPS estimate / actual / surprise% back to 1999 for AAPL, and comparable depth across the rest of the universe. This is real analyst-estimate-based data, sufficient to build a proper SUE (standardized unexpected earnings), not a weaker seasonal-random-walk proxy.

**Customer-supplier / competitor / news-comention data**: researched in parallel via a background agent (SEC EDGAR full-text search, the Cohen & Frazzini academic dataset, Wikipedia/Wikidata structured fields, GDELT news co-mention). **Verdict: not realistically obtainable for free in this session.**
- SEC EDGAR has the underlying disclosures but only as free text buried in 10-K notes — no structured (customer, supplier, %) API. Extracting it reliably would be a real NLP/entity-resolution build (days, not a data pull).
- The canonical Cohen & Frazzini customer-supplier dataset used to be hosted on Frazzini's NYU page; it has since moved to AQR's data-sets page, where **it is no longer listed** — confirmed by fetching that page directly.
- Wikipedia/Wikidata have no structured competitor/customer/supplier field for these companies.
- GDELT news co-mention is technically free and obtainable, but measures "mentioned together," not a verified supply relationship — this project already rejected a comparably weak proxy (GICS sector membership) for this exact reason, so using GDELT would be the same mistake under a different name.

**Per instruction: not built.** Stated plainly rather than substituted with something weaker. PEAD proceeded alone (the "and/or" in the original ask covers this).

## 2. PEAD build

- Real earnings history: 75/75 tickers, 5,602 total events with usable SUE after cleaning.
- **Real bug found and fixed**: raw `surprise_pct` blows up when the analyst EPS estimate is near zero (XOM 2020-05-01: **+135,997%** surprise from a ~$0.001 estimate). 95/2,759 events (3.4%) had |surprise_pct| > 100%. Winsorized to ±100% before standardizing — a standard fix for this well-known small-denominator problem, applied uniformly, not tuned to the result. A second real bug (division-by-zero → `inf` SUE when a ticker's trailing surprise history was constant post-winsorization) was also caught and fixed, with a regression test.
- SUE = winsorized surprise% ÷ trailing (strictly causal, 8-quarter) standard deviation of that ticker's own past surprises.
- Signal timing: earnings announced after 4pm ET roll to the next trading session before the reaction window starts; before-open announcements react same-day. Verified against real timestamps.
- **Honest finding before any ML filtering**: raw mean drift in the SUE-predicted direction is *negative* at every horizon tested (10/20/60 days), the opposite of textbook PEAD continuation. Plausible explanation: PEAD is a well-documented small-cap/low-coverage anomaly, and this universe was deliberately built (Phase 1) to be the most liquid, most heavily-covered large-cap subset of the S&P 500 — close to where the literature says PEAD should be weakest. Reported as found, not smoothed over — and the ML filter step proceeded anyway, since a negative unconditional mean doesn't rule out a real edge in some conditional subset.
- 20-trading-day holding period (documented reasoning in `earnings/labeling.py`), 2,723 labeled events after feature construction — **~20x fewer than the mean-reversion signal's ~123,000**, an intrinsic consequence of earnings being quarterly. Every number below carries more sampling noise than the Phase 3 mean-reversion numbers as a result — flagged throughout, not just here.

## 3. ML filter results (same D1-D4 machinery as before)

| Holdout | n | Ensemble AUC | Beats majority? | Even simple logistic regression AUC |
|---|---|---|---|---|
| holdout_a (2021-10→2022-11) | 320 | 0.531 | ✅ Yes | 0.564 |
| holdout_b (2023-01→2024-02) | 325 | **0.653** | ✅ Yes | 0.620 |
| holdout_c (2024-04→2025-06) | 360 | 0.509 | ✅ Yes | 0.541 |

**`all_holdouts_beat_majority_baseline = true`** — the mean-reversion signal failed this exact check on holdout_a. Notably, even the plain logistic-regression baseline (not the ensemble) shows real signal across all three holdouts (0.54–0.62 AUC) — evidence this isn't one overfit ensemble member finding noise, multiple independent model families see the same modest edge.

## 4. Backtest (realistic 10bps cost, same risk/circuit-breaker infrastructure reused as-is)

| Holdout | Ann. Return | Sharpe | Max DD | Trades |
|---|---|---|---|---|
| holdout_a | +2.0% | **+0.57** | −1.8% | 90 |
| holdout_b | +8.2% | **+1.87** | −2.0% | 92 |
| holdout_c | +2.5% | **+0.53** | −2.5% | 108 |

**All three holdouts positive** — qualitatively different from the mean-reversion strategy's one-winner-two-losers pattern. Drawdowns are also far shallower (≤2.5% vs. up to −13.3%).

**Cost sensitivity**: 0bps→10bps erodes but never flips any holdout negative (holdout_a 2.5%→2.0%, holdout_b 8.8%→8.2%, holdout_c 3.1%→2.5%). Turnover is ~6x annualized, roughly a quarter of the mean-reversion strategy's ~25-35x — fewer round trips, so costs matter proportionally less. This is a genuinely more cost-robust profile.

**ML filter vs. unconditional trading**: filter clearly helps in 2 of 3 holdouts (holdout_a: Sharpe −0.07→+0.57; holdout_b: −0.54→+1.87) but in holdout_c the *unfiltered* baseline was actually better (Sharpe +1.16 vs. the filtered +0.53) — the filtered result is still solidly positive on its own, but the filter subtracted some value there. Mixed, reported as found.

## 5. Honest verdict: **cautiously positive, not a slam-dunk GO**

On every specific criterion asked for, PEAD **passes where the mean-reversion signal failed**: beats majority baseline on all 3 holdouts, positive net-of-realistic-cost returns on all 3, meaningfully more cost-robust, much shallower drawdowns.

**The caveat that keeps this from being an unqualified go**: sample size. ~90–108 trades per holdout is roughly 1/150th the mean-reversion signal's per-holdout trade count. Three consistent positive holdouts is real evidence — consistency across independently-drawn samples is generally stronger evidence than any single sample's magnitude — but it is not the same statistical confidence as the mean-reversion backtest's (negative) result, which was backed by 16,000+ trades per holdout. This result **warrants a larger validation run** (a bigger universe, or waiting for more real quarters to accumulate) **before treating it as confirmed**, not immediate promotion to a go-live discussion. Reported exactly this way — not oversold as a confirmed edge, not dismissed for its small sample either.

## Test coverage

8 new tests (PEAD-specific: SUE winsorization regression, no-lookahead check, BMO/AMC timing alignment, real-data sanity checks). **109/109 tests passing** project-wide.
