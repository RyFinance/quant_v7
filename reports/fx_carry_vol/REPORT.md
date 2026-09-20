# FX carry scaled by implied volatility: development result (stopped at the gate)

Plan: `research/fx_carry_vol/PLAN.md` (registered before any carry return). Data: LSE vault 1-week
forward points and 1-month ATM implied vols for the 9 G10 currencies against USD; vault daily spot.
The design is paired: does option-implied volatility improve carry built from the same forward points?

## Development, weekly, 2015-01 → 2019-12 (261 weeks)

| Strategy | Net Sharpe | Gross | 95% interval | Max DD | vs plain carry |
|---|---:|---:|---|---:|---|
| F1 plain carry (baseline) | −0.03 | 0.02 | [−0.73, 0.73] | −13.6% | — |
| F2 carry ÷ implied vol, inverse-vol weights | −0.22 | −0.17 | [−0.90, 0.53] | −15.8% | −1.5%/yr (p 0.97) |
| F3 F2 + 8% vol target | −0.33 | −0.27 | [−1.00, 0.38] | −19.3% | −2.7%/yr (p 0.97) |

**Nothing passes** (the gate is net Sharpe ≥ 0.5 and beating F1). Validation (2020–2026) is not run.

## Checks and reading

- The construction is right. The book is long NZD and AUD (most weeks) plus CAD/NOK, and short CHF,
  EUR and SEK: the textbook G10 carry trade. Carry values match policy-rate gaps (2017-06-06: NZD +0.9%,
  AUD +0.7%, CHF −2.0% against USD). Tests: `tests/test_fx_carry_vol.py`.
- G10 carry earned nothing in 2015–2019: −10% (2015), +8%, −3%, −2%, +6%. Rate dispersion was low and
  commodity currencies sold off in 2015.
- Scaling by implied volatility **hurt**. Dividing a negative carry by a low implied vol makes low-vol
  funding currencies (JPY) look like the best shorts: F2 shorted the yen in 115 weeks against F1's 42.
  The yen then rallied in the risk-off episodes.
- F1's interval [−0.73, 0.73] is consistent with the multi-asset sleeve's 0.25 on 2018–2026: carry here
  is a vacuous null, not a refutation. Implied-vol scaling, though, has no support at all in this
  window.

The trial ledger grows by 2 (F2, F3).
