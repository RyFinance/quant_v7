# Short-dated SPY put writing: development result (stopped at the gate)

Plan: `research/putwrite/PLAN.md` (registered before any SPY option price was pulled). Data: OPRA daily
option bars for SPY, QQQ and IWM from the LSE vault, 2014-06 → 2019-12 for development.

| Candidate | Net Sharpe | Gross | Stress | CAGR (1× notional) | Max DD | Trades |
|---|---:|---:|---:|---:|---:|---:|
| P1 SPY 1-day puts, about 1σ out of the money | 0.21 | 0.44 | 0.03 | 0.65% | −4.8% | 557 |
| P2 P1 only when implied vol > realised vol | 0.15 | 0.33 | 0.01 | 0.44% | −4.8% | 403 |
| P3 SPY + QQQ + IWM | 0.04 | 0.39 | −0.25 | 0.07% | −6.1% | 1,127 |

**Nothing passes** (the gate is net Sharpe ≥ 0.5). Validation (2020–2026) is not run.

## Reading

- The trades behave as designed. Strikes average 0.4–0.9% below spot, premiums about 10 bps of strike,
  and puts finish in the money 14–21% of the time, close to the ~16% a 1σ strike implies. The worst
  losses are real events: 2018-10-09, the Brexit vote, 2019-08-02.
- Implied vol sat above realised vol every year, yet the premium beat the average payout by only
  about **1.5 bps per trade before costs**, and costs took about 0.8 bps. On SPY 1-day puts,
  2014–2019, the variance premium is too thin to harvest at retail costs. Harvesting it at these
  strikes pays about 0.5% a year.
- The live quote recorder (`research/putwrite/record_quotes.py`) will still show whether real spreads
  are narrower than assumed. Even at zero cost, the gross Sharpe of 0.44 is below the 0.70 benchmark.

The trial ledger grows by 3 (P1–P3).
