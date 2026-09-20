# FX carry scaled by option-implied volatility: pre-registration

Written 2026-09-18, after pulling the data and checking quoting conventions, and before any carry
return was computed. Data: LSE vault `fx_derivatives` (1-week forward points `*_SW_FWD`, 1-month ATM
implied vol `*_1M_ATM`, 2015 onward) and vault `fx` daily spot. Raw pull: `data/lse/fx_carry/raw.pkl`.

## Why, and what this test can and cannot show

- FX carry itself is **not new** to quant_v7. The multi-asset book's `fx_carry` sleeve (policy-rate
  proxy) scored 0.45 in development (≤2017) and 0.25 on the 2018–2026 hold-out: a vacuous null
  (`reports/null_audit/`).
- This window overlaps that hold-out, so a raw carry Sharpe here is not new evidence.
- What **is** new is option-implied volatility, which the project never had. The test is therefore
  paired: does ranking and sizing by carry-to-implied-vol beat plain carry built from the same forward
  points, on the same dates? (Carry-to-risk: e.g. Daniel, Hodrick & Lu 2017; the global-FX-vol link to
  carry crashes: Menkhoff, Sarno, Schmeling & Schrimpf 2012.)

## Conventions (checked against rate differentials)

- F = S + points × pip, with pip = 0.01 for USDJPY and 0.0001 otherwise. Implied vol is in percent.
- Spot is the vault's UTC-day close. EUR, GBP, AUD and NZD are quoted in USD per unit; for USDJPY,
  USDCHF, USDCAD, USDSEK and USDNOK, the foreign currency's USD price is 1/S (1/F for forwards).

## Portfolio mechanics (all candidates)

- **Signal:** each Tuesday's forward points and 1M implied vol (skipped if missing).
- **Entry:** the next trading day's (Wednesday's) spot close, buying or selling the foreign currency
  1 week forward at F = S_entry + points_entry × pip.
- **Exit:** the spot close 7 calendar days later.
- **Return, long foreign currency:** S_exit/F_entry − 1 for XXXUSD pairs; F_entry/S_exit − 1 for
  USDXXX pairs. This is already an excess return.
- **Carry of a long foreign position, annualised:** (S − F)/F × 52 for XXXUSD pairs; (F − S)/S × 52
  for USDXXX pairs.
- **Universe:** EUR, GBP, AUD, NZD, JPY, CHF, CAD, SEK and NOK against USD. A week needs at least
  7 pairs with signals.

## Strategies

- **F1_plain_carry (paired baseline; not a candidate).** Long the 3 highest-carry currencies and
  short the 3 lowest, equal-weight, 100% NAV per leg.
- **F2_carry_to_vol.** Rank by carry ÷ 1M implied vol. Long the top 3 and short the bottom 3. Within
  each leg, weights are ∝ 1/implied vol and sum to 100% NAV.
- **F3_carry_to_vol_targeted.** F2's weights scaled so ex-ante portfolio volatility is 8%/yr.
  Ex-ante covariance = implied vols × the 63-day correlation of daily log spot returns. Scale is
  capped at 3.

## Costs

- Base: 1 bp per side on traded notional for EUR, JPY, GBP, CHF, AUD and CAD; 2 bp for NZD, SEK and
  NOK. Plus 0.2 bp per week on every open position's gross notional (the weekly forward roll).
- Stress: all costs ×3.

## Windows and gates

- Development: signals 2015-01-06 → 2019-12-31. Validation: 2020-01-01 → 2026-09-17, locked until
  `research/fx_carry_vol/VALIDATION_UNLOCK.md` is registered. Validation runs F1 plus the selected
  candidates only.
- **Development gate:**
  - net base Sharpe ≥ 0.5 (weekly returns, √52);
  - and a Sharpe above F1's on the same dates.
- **Validation pass:**
  - net base Sharpe ≥ 0.75;
  - stressed mean > 0;
  - one-sided circular-block bootstrap p < 0.05/2 (8-week blocks, 5,000 draws);
  - Sharpe above the PEAD benchmark of 0.70;
  - and the paired difference (candidate − F1, weekly) has a positive mean with one-sided bootstrap
    p < 0.05.
- Also reported: intervals, bounded or vacuous at 0.5, and correlation with the PEAD benchmark.

## Expectation stated in advance

G10 carry was weak after 2015 (low rate dispersion until 2022, then yen-funded carry and its 2024
unwind). Carry-to-risk usually improves carry's Sharpe by roughly 0.1–0.3. Prior net Sharpe: −0.2 to
0.6. Beating the 0.70 benchmark would be a surprise.
