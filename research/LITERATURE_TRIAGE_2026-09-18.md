# LSE research feed triage (2026-09-18)

I read the terminal's RESEARCH feed (arXiv q-fin, NBER, FED, ECB, BIS; about 120 papers from
2026-08-23 to 2026-09-18) looking for hypotheses testable with data quant_v7 actually has. Most
papers are macro, pricing theory, insurance or credit scoring, with nothing to trade.

| Paper | What it claims | Usable here? |
|---|---|---|
| Wysocki, *Harvesting the Volatility Risk Premium: A Learning-to-Rank Approach* (arXiv 2608.24786) | LightGBM LambdaRank picks one of 8 delta-targeted SPXW 0DTE short puts (or skips) daily; out-of-time Sharpe 4.3–5.8 in 2025 | **Inspiration only.** One hold-out year after per-window Optuna search, 15 feature groups and 7 sizing methods, so the headline Sharpe is not credible. The premium it harvests (short-dated index puts are overpriced; Bondarenko 2014, Carr–Wu 2009) is a documented risk premium, and our new OPRA data can test a **fixed-rule, no-ML** version on SPY: `research/putwrite/PLAN.md`. |
| Gençay, *What survives honest evaluation?* (arXiv 2608.27734) | Deflated Sharpe indexed to the recorded trial count rejects every LLM-discovered strategy; pre-registered single hypotheses face almost no deflation | **Method.** Supports the project's pre-registration protocol. Reports should add a deflated Sharpe against the project-wide trial ledger (≈40+ trials since 2026-09-17). |
| An, Su & Wang, *Quantity, Risk, and Return* (arXiv 2609.05162) | Factor premia rise when sophisticated investors have absorbed retail flows into that factor ("beta times quantity"); monthly OOS R² ≈ 1% | **No data.** Needs mutual-fund flow/holdings data; not in LSE or quant_v7. |
| Guo & Wachter, *Correlation Neglect in Asset Prices* (NBER w35753) | The market return in the 2nd month of a quarter negatively predicts the 1st month of the next quarter; the industry version works too | **Low ceiling.** Four market bets per year; even the industry version is active four months a year. Cannot approach the Sharpe target; a possible future diversifier, and forward-only if tested. |
| Kosch & Forsberg, *Seasonal Trading in Commodity Futures* (arXiv 2609.12227) | Regression and singular-spectrum seasonal signals in commodity futures | **Windows consumed.** Commodity futures 2018–2026 were the multi-asset hold-out; forward test only. |
| Kitron & Wengrowicz, *Short-horizon mean reversion in cryptocurrency markets* (arXiv 2608.21888) | 15-minute sign reversal in 90% of 183 Binance pairs, not in US stocks | **Not capturable.** The authors' own gross edge is about 1.3 bp per trade against a 5 bp round trip. |
| Tan, *Two Kinds of Nothing* (arXiv 2608.30490) | A null result is only informative if its interval excludes the smallest consequential effect | **Applied:** `reports/null_audit/REPORT.md` re-grades every past failure. |
| Heitfield et al., *Premiums or Peril* (FEDS 2026-063) | Florida house prices vs weather risk | Not tradable. |
| Guo, Nunes, *Signal Correlation, IC, and PnL Dependence*; *Large Signal Libraries* (arXiv 2609.09588, 2609.12477) | Combining many weak signals: correlation of signals vs of PnLs | Method for combining sleeves later; no hypothesis. |
| ECB, *When the Crowd Speaks* (Reddit retail sentiment) and *Measuring sentiment news with transformers* | Sentiment indices | The LSE news feed is live-only: forward test only. |

Decision: register one new experiment from this pass (SPY short-dated put writing). No other
paper yields a hypothesis that is both testable on genuinely new data and able to reach the target.
