# Validation unlock: intraday / event-day family

Registered after the development run (reports/intraday/dev/results.json), before any validation-window
number was computed.

- Development selected **I4_announcement_day** only (net base Sharpe 0.55 ≥ 0.5). I1 (−0.12), I2 (0.38)
  and I3 (−0.96) stop here and are never run on 2021–2026.
- Frozen code: research/intraday/evaluate.py sha256 01569fef25ad6099bf5b0ec60b177b86dfd0b594a06a6de09e72125007333d69. No rule, cost, calendar filter or
  gate changes.
- Window: 2021-01-01 → 2026-09-17, run once.
- Pass requires net base Sharpe ≥ 0.75, stressed mean > 0, one-sided block-bootstrap p < 0.0125, and a
  Sharpe above the PEAD benchmark of 0.70.
