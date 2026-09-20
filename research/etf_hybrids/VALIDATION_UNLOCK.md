# ETF hybrids: validation unlock

The development run (2003-01-02 → 2014-12-31, `reports/etf_hybrids/dev/results.json`) completed under
`research/etf_hybrids/PLAN.md` (sha256 6dc99d7a…) with no change to rules, costs or gates.

Development net excess Sharpe (base costs), benchmark B = 0.53:

| Candidate | Sharpe | Gate result |
|---|---:|---|
| E1 vol-managed momentum | 0.66 | passes |
| E2 dual momentum | 0.57 | passes |
| E3 52-week high | 0.47 | fails (< 0.5) |
| E4 momentum × low vol | 0.51 | fails (not above B) |
| E5 seasonality | 0.41 | fails (< 0.5) |

**Selected for validation: E1 and E2 only.** E3, E4 and E5 stop here and are never run on 2015–2026.

- Frozen code (sha256):
  - `research/etf_hybrids/signals.py` ac8c90cf308e352f9ff54ea6c26e85e28fe4eec85251f1ba50ec6396f9dfa413
  - `research/etf_hybrids/evaluate.py` 5be4cd9dbb468bccd38cb895488e807466be5ec2e85bbcd61d9b95d89ac6acaa
  - `research/etf_hybrids/pull.py` 83377111d28dff92112ab19ef8d9fc399b4758cf4cab522d544c117fa0df9560
  - data `data/etf_hybrids/manifest.json` e5b50591eb79daa94813209e31377b1970fa820edb9d28f2f3e452dab6c45a13
- Window: signal dates 2014-12-31 → 2026-08-31, daily returns 2015-01-02 → 2026-09-18. Runs once;
  the code refuses to overwrite a validation result.
- A pass requires all of:
  - net Sharpe ≥ 0.75;
  - stress annual mean > 0;
  - one-sided block-bootstrap p < 0.01;
  - Sharpe > 0.70;
  - paired Sharpe test against B with p < 0.01.
- Also reported as fixed: the PEAD correlation, and deflated Sharpe (80 trials, using the trial
  variance recorded in development).

Noted before unlocking:
- The development edge is exposure timing, not selection. Plain 12-1 momentum (R0) scored 0.50,
  below B at 0.53. E1 and E2 differ from it by holding T-bills, and both lost about 20% in 2008
  against −41% for B.
- The development paired tests against B were far from significant (p = 0.15 for E1, 0.40 for E2).
  Passing the p < 0.01 paired gate in validation is therefore unlikely.
