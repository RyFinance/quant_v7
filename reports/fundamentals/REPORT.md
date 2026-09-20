# Fundamentals signals F1/F2/F3 (edge-graveyard C4 + C5): development result

Tester agent, 2026-09-19. Pre-registered in `research/fundamentals/PLAN.md` (sha256 1c397451…,
registered 2026-09-19T06:45:52-0700, before any return was computed). No rule, cost or gate was changed
after results.

**Verdict: all three candidates fail development (net Sharpe well below 0.5, all negative). Nothing
was selected, so validation (2015–2026) was not unlocked or run. The 2015+ window stays unviewed
for these signals.**

Code: `research/fundamentals/signals.py` (point-in-time signals), `build_signals.py` (signal panel),
`evaluate.py` (runs; validation guard). Tests: `tests/test_fundamentals.py` (7 pass: acceptance-date
lag, placeholder fallback, split guard, no look-ahead / t−6m skip, consistency definition and filters,
costs, validation lock). Outputs: `reports/fundamentals/signals.parquet`, `dev/results.json`,
`dev/*_curve.csv`, `dev/selection.json` (empty).

## Coverage (checked before registration)

- 496 names with fundamentals and prices; 403 names file in 2003, 496 by 2024.
- 6% of 2003–2026 rows have placeholder acceptance times on or before period end → treated as available
  at period end + 45 d (quarters) / + 90 d (FY, Q4).
- Share counts and EPS are already restated to the current split basis (554 of 603 splits show no jump;
  4 raw), so the split file is used only as a residual guard, not a blanket adjustment.
- Names with a valid signal per month: F1 368 (2003) → 446 (2014); F2/F3 about 155–253 (the
  sign-consistency filter removes about half).

## Development, 2003-02 → 2015-01 (143 monthly rebalances; base costs 5 bp/side, 0.5% borrow)

| | F1 issuance | F2 consistency | F3 combined |
|---|---|---|---|
| Net Sharpe | **−0.85** | **−0.37** | **−0.63** |
| 95% CI (6-mo block) | [−1.40, −0.27] | [−0.98, 0.30] | [−1.33, 0.06] |
| Gross Sharpe | −0.75 | −0.30 | −0.54 |
| Stress Sharpe (15 bp, 3%, no rebate) | −1.36 | −0.80 | −1.14 |
| Net return / vol (ann.) | −7.1% / 8.3% | −3.8% / 10.1% | −5.6% / 8.8% |
| Max drawdown | −61% | −51% | −60% |
| One-sided p (mean > 0) | 0.996 | 0.87 | 0.97 |
| Beta to SPY / alpha (t) | −0.22 / −5.1% (−2.2) | −0.11 / −2.7% (−0.9) | −0.18 / −4.0% (−1.6) |
| Deflated Sharpe (65 trials) | 0.00 | 0.00 | 0.00 |
| Names per leg | 80 | 42 | 42 |
| Annual turnover / cost drag | 5.7 / 0.8% | 5.5 / 0.8% | 7.1 / 0.9% |
| Long − EW universe (gross, ann.) | −2.0% | +2.2% | −1.5% |
| EW universe − short (gross, ann.) | −4.3% | −5.2% | −3.3% |
| EW universe excess Sharpe (control) | 1.06 | 1.02 | 1.02 |
| null_kind at 0.5 | bounded null | bounded null | bounded null |

Net return by year:

| Year | F1 | F2 | F3 |
|---|---|---|---|
| 2003 | −26.6% | −22.8% | −25.8% |
| 2004 | −0.4% | +3.1% | −4.8% |
| 2005 | −20.6% | −2.3% | −10.3% |
| 2006 | −0.6% | −6.4% | −3.0% |
| 2007 | −11.6% | +0.5% | −8.8% |
| 2008 | +1.2% | −11.6% | −6.4% |
| 2009 | −20.6% | −18.0% | −21.0% |
| 2010 | −6.4% | +10.8% | −1.1% |
| 2011 | +7.8% | +13.3% | +16.5% |
| 2012 | +2.3% | −11.2% | −6.3% |
| 2013 | −0.7% | −0.4% | +6.1% |
| 2014 | −1.6% | +1.7% | +3.0% |

## Reading

- The loss comes from the **short leg**: the high-issuance and inconsistent-earnings names *beat* the
  universe by 3–5%/yr. This is the survivorship direction the PLAN expected. Today's S&P 500 members
  that issued heavily or had erratic earnings in 2003–2014 are the ones that later succeeded (the
  failures are absent), so the short leg is a portfolio of future winners. The same bias inflates the
  EW control (Sharpe ~1.0).
- The worst years are junk rallies (2003, 2009), when distressed issuers rebounded. The small negative
  beta adds to this.
- F2's long leg beat the universe slightly (+2.2%/yr gross), but the short leg more than cancelled it.
- The intervals are bounded nulls: all three rule out a Sharpe of 0.5 in this universe.
- The result says these signals are not tradeable in a current-member S&P 500 universe with this data.
  It does not say the published anomalies are dead: survivorship bias works directly against the short
  leg. A fair test needs a point-in-time universe that includes delisted names, which we do not have.
- PEAD correlation was pre-registered for validation only, so it was not computed.
