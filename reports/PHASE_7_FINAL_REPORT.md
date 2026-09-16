# Quant v7 — Phases 1–7 Consolidated Report

Real numbers, real 2015–2026 market data (75-name liquid S&P 500 subset), real historical tail events (2005–2026 supplementary legacy dataset for 2008 GFC / 2010 Flash Crash). No synthetic price data anywhere in the reported results (synthetic data was used only in a handful of unit tests, explicitly flagged in their docstrings — never in a reported number below).

## 1. Data foundation (Phases 1–2 recap)

- Universe: 75 tickers, top-75 S&P 500 constituents by 63-day avg dollar volume.
- Data: 2015-01-02 → 2026-08-14, 0 gaps, 0 stale feeds.
- Survivorship-bias source: Wikipedia's dedicated "Historical components of the S&P 500" page (774 real add/remove events, 1990s–present).
- Clustering: explained-variance(90%) k = 22–30 (mean 27); Marchenko-Pastur k = 2–4. The two methods disagree by an order of magnitude because they measure different things (dimensionality vs. noise-signal detection) — reported honestly, not reconciled.
- Cluster **membership** is unstable day-to-day (median ARI vs. prior day ≈ 0.34) even though cluster **count** is stable (unchanged 88% of days).

## 2. Phase 3 — ML signal-quality filter

**Headline finding: the filter shows essentially no reliable edge on held-out data.**

| Holdout | Window | Ensemble AUC | Beats majority baseline? |
|---|---|---|---|
| holdout_a | 2022-06 → 2023-10 | 0.508 | **No** (0.5212 vs 0.5215) |
| holdout_b | 2023-10 → 2025-03 | 0.520 | Yes (+0.7pp) |
| holdout_c | 2025-03 → 2026-08 | 0.503 | Yes (+0.3pp) |

`all_holdouts_beat_majority_baseline = false`. AUC hovers at 0.50–0.52 across all three holdouts — barely distinguishable from a coin flip. The **fixed-threshold (50bps) label model is functionally broken**: recall of 0.3–1.5%, meaning it almost never flags a trade as good despite superficially plausible accuracy (a classic class-imbalance illusion). The **cost-adjusted label** (does the trade clear real transaction cost) is the one actually used downstream.

**Cluster-instability ablation (explicitly requested):** adding `market_ari_vs_prev` as a feature made no consistent difference (±0.001–0.006 AUC across holdouts, both directions). Segmenting predictions by high- vs. low-stability days showed **no meaningful difference** (AUC 0.510 vs 0.512). **Finding: Phase 2's cluster-instability does NOT detectably degrade the ML filter** — reported as a genuine null result, not spun as either good or bad news.

## 3. Phase 4 — Risk & sizing

Kelly sizer (quarter-Kelly, real payoff ratio b≈1.045 estimated from training data), standard risk limits (10% max position / 3% max daily loss / 60% max exposure, hard fail-safe), adaptive TP/SL (scales with entry deviation and cluster volatility, tightens over the 5-day hold), transaction cost model (10bps round-trip, documented assumption). **A real bug was caught and fixed during this phase**: an initial `MIN_PAYOFF_RATIO` safety floor (0.05) was silently overriding the true computed payoff ratio (0.0254) — a regression test now guards this specific failure mode.

## 4. Phase 5 — Circuit breaker (independent module, calibrated against real events)

| Event | Result |
|---|---|
| 2020 COVID crash (75-name universe, real data) | **True positive.** 49/63 window days triggered; reached FULL_FLATTEN. |
| 2008 GFC (legacy 20-ticker set, real data) | Magnitude fires 11/85 days; structural (correlation-spike) fires 52/85 days. |
| 2010 Flash Crash | **Not detected** — and structurally cannot be, at daily-bar resolution (real SPY close-to-close move that day was only −3.3%; the ~9% intraday plunge recovered by close). Documented as an accepted limitation, not silently skipped. |
| False positives, 20yr ex-crisis (legacy set, magnitude only) | 2 days in ~20 years (0.04%) |
| False positives, production 75-name set, ex-COVID-window | 1.79% of days — but a large share of these are real events outside the narrow COVID window used for exclusion (April 2025 tariff shock, 2018 Q4 selloff), not pure noise. |

**Key architectural finding**: the structural correlation-spike trigger must use **raw** returns, not the signal engine's residual returns — residual correlation barely moved during COVID (0.15→0.18) because Part B1's beta-stripping removes exactly the systemic co-movement signal a circuit breaker needs. Raw correlation spiked cleanly (0.54 calm-year max → 0.78 COVID peak). This is a concrete, empirical vindication of keeping the breaker's data pipeline independent from the signal engine's, beyond just code organization.

**Documented accepted limitations**: no historical intraday data for flash-crash speed-trigger backtesting (free data sources don't reach back that far at minute granularity); no crypto data source was built in this project at all, so LUNA/FTX-style calibration is fully out of scope.

## 5. Phase 6 — Full backtest (signal → ML filter → Kelly → risk → circuit breaker → costs)

**Holdout results, realistic 10bps cost:**

| Holdout | Ann. Return | Sharpe | Max DD | Trades |
|---|---|---|---|---|
| holdout_a (2022-06→2023-10, bear grind) | **−2.0%** | **−0.32** | −10.4% | 4,088 |
| holdout_b (2023-10→2025-03, AI rally) | **+7.0%** | **+1.45** | −3.9% | 3,646 |
| holdout_c (2025-03→2026-08) | **−5.0%** | **−0.51** | −13.3% | 3,698 |

**Not stable across holdouts** — one strong winner, two losers. Fails Section 7's stability criterion.

**Transaction cost sensitivity** (matches the spec's own warning about the reference paper): holdout_a flips from +0.8% (0bps) to −2.0% (10bps) — cost alone erases a marginal edge. holdout_b survives (9.5%→7.0%) but loses ~1/4 of its return to cost. holdout_c is negative even at zero cost.

**ML filter vs. unconditional trading (no filter)**: the filter **clearly helps** in 2 of 3 holdouts (holdout_a: −10.2%→−2.0% annualized; holdout_b: −1.5%→+7.0%) but **hurts** in holdout_c (−0.1%→−5.0%). Mixed, not uniformly positive — reported as found.

**Walk-forward** (16 rolling quarters, 2022-Q3→2026-Q2, expanding-window retrain): mean Sharpe 0.71, std **1.51** (very high quarter-to-quarter variance — several quarters traded <50 times, making their Sharpe numbers statistically noisy). First-half mean Sharpe −0.09 vs. second-half +1.50 — no evidence of decay; if anything a later improvement, plausibly just from more training data accumulating in the expanding window, not necessarily a "the model got better at markets" story.

## 6. Section 7 Go/No-Go — honest checklist

| Criterion | Status | Real number |
|---|---|---|
| Beats majority baseline on **all** holdouts | ❌ **FAIL** | fails on holdout_a (0.5212 vs 0.5215) |
| Stable performance across 3+ holdouts | ❌ **FAIL** | Sharpe range −0.51 to +1.45, mean 0.21 |
| Positive net-of-cost returns, realistic costs | ❌ **FAIL** | 2 of 3 holdouts negative at 10bps |
| Circuit breaker tested against real tail events | ✅ **PASS** | COVID true positive; GFC coverage; 2010 limitation documented |
| 30-day paper forward test | ⬜ **NOT MET** | not possible in this offline session — no live/real-time capability |
| Full pytest suite passing, stable | ✅ **PASS** | 101/101, 2 consecutive clean runs |
| Section 3.3 data gaps resolved or documented | ✅ **DOCUMENTED** | crypto: not built; 2010 intraday: unavailable; order-book depth: not applicable to this daily-bar strategy |

## 7. Recommendation: **NO-GO** for live capital in current form

The signal (Part C mean-reversion) and ML filter (Part D) do not show a robust, holdout-stable edge — this is the honest, load-bearing finding, consistent from Phase 3's classification metrics through Phase 6's P&L simulation. The risk/sizing (Part E) and circuit breaker (Part F) infrastructure are built, tested, and calibrated correctly and are ready to sit under a better signal if one is developed — they are not the blocker. **The blocker is the core edge.**

Two honest paths forward, not a verdict on which to take:
1. **Revisit the signal/labeling design** — e.g. the E3 adaptive-exit tuning discovered during Phase 6 that many positions exit on day 1 (a possible over-tight take-profit relative to typical daily noise, not re-tuned here to avoid result-driven overfitting) is one concrete lever worth investigating with fresh eyes.
2. **Accept the honest result and stop here** — the infrastructure (Phases 1, 2, 4, 5) is real, tested, and reusable; the strategy itself, as currently specified, does not clear its own go/no-go bar.

No live trading, no real capital, no order placement occurred anywhere in this build — paper/research infrastructure only, throughout.

## Test coverage

**101/101 tests passing** across all 6 phases (16+20+23+14+18+10), confirmed stable across 2 consecutive full-suite runs. Real market/Wikipedia data used throughout except explicitly-flagged synthetic edge-case constructions (documented in each test file's docstring).
