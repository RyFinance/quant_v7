# Leveraged-ETF close rebalancing on ES/NQ (A2)

Plan: `research/letf_rebalancing/PLAN.md`. It was registered in `research/preregistrations.jsonl` at
2026-09-19T03:18:39-0700, sha256 6118dad6…, before any strategy return was computed. Code:
`research/letf_rebalancing/evaluate.py`. Tests: `tests/test_letf_rebalancing.py` (8 pass). Benchmark:
**0.70**.

## Design (as registered)

- **Predicted close flow (Cheng & Madhavan 2009):** F = Σ AUM_{t−1}·L(L−1) × r_t.
  - r_t is the futures return from the prior 16:00 close to 15:30.
  - AUM is the latest ProShares value dated strictly before t.
  - Funds: TQQQ/SQQQ/QLD/QID/PSQ → NQ; UPRO/SPXU/SSO/SDS/SH → ES.
- **Scale (Shum et al. 2016):** φ = |F| / (20-day median of the 15:30-bar dollar volume, excluding
  today).
- **Candidates:**
  - L1 trades sign(F) only when φ ≥ its expanding 80th percentile.
  - L2 sizes the position by φ / expanding median, capped at 3.
- **Execution and costs:** 15:30 → 16:00 ET, 0.5 NAV per contract, 0.5 bp per side (stress 1.5 bp),
  roll days flat.
- **Relationship to I2:** the direction is identical to I2 (rest-of-day momentum, dev net 0.38), so
  both candidates are conditioned or reweighted versions of it. This was disclosed in the plan.

## Data coverage

- **ProShares daily NAV/shares/AUM files:** complete back to 2006–2010 with no missing days. AUM equals
  NAV × shares within 0.2%.
- **Direxion (SPXL/SPXS) is missing:** the site is bot-walled, yfinance shares history returns nothing,
  and SEC was out of scope. ES rebalancing gamma is therefore understated.
- **Rebalancing gamma, Σ AUM·L(L−1), mean by year, in $bn:**

| | 2016 | 2017 | 2018 | 2019 | 2020 |
|---|---:|---:|---:|---:|---:|
| NQ complex | 18 | 22 | 34 | 42 | 64 |
| ES complex | 35 | 30 | 27 | 29 | 38 |

- **Latest levels:** in 2026 TQQQ alone is about $36bn of AUM, roughly $220bn of gamma; the NQ complex is about $270bn. Nasdaq-100 LETF
  gamma grew about 15× from 2016 to 2026. S&P ProShares assets shrank in the inverse funds and grew in
  UPRO/SSO.
- **Median φ, 2016–2020:** NQ 3–9% of typical last-30-minute NQ notional; ES 0.3–1.0%.

## Development, 2016-06 → 2020-12 (1,085 tradable days, 56 roll days excluded)

| Candidate | Net Sharpe | Gross | Stress | 95% interval | Boot. p | DSR (60) | Hit | Active days | Max DD | Verdict |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---|
| L1 top-quintile flow | 0.39 | 0.52 | 0.14 | [−0.91, 1.10] | 0.21 | 0.04 | 49.3% | 337 | −6.5% | stop |
| L2 flow-scaled | 0.48 | 0.69 | 0.05 | [−0.74, 1.19] | 0.17 | 0.06 | 47.8% | 1,011 | −16.3% | stop |

- Both miss the 0.5 development gate, and both intervals are vacuous at 0.5.
- **Development selected nothing, so validation (2021–2026) was not run and stays locked.** No
  `VALIDATION_UNLOCK.md` was written.
- Correlation with PEAD could not be computed: the benchmark series spans 2021-08 → 2025-06, with no
  overlap with development.

**By year, net base:**

| | 2016 (Jun–) | 2017 | 2018 | 2019 | 2020 |
|---|---:|---:|---:|---:|---:|
| L1 | −0.4% | −0.0% | +5.3% | −1.9% | +5.2% |
| L2 | −0.7% | −4.4% | +16.5% | −5.8% | +25.5% |

The returns come from two high-volatility years (2018 Q4 and 2020). The quiet years are flat or
negative.

## Dose-response (diagnostic, development)

This is the mean gross signed last-half-hour return, sign(F)·r(15:30→16:00), by expanding quintile of
φ, pooled over ES and NQ:

| φ quintile | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---:|---:|---:|---:|---:|
| mean, bp | −0.00 | +0.95 | +1.00 | +3.29 | +4.13 |
| t | −0.0 | 0.9 | 0.7 | 2.1 | 1.5 |
| n | 379 | 362 | 361 | 389 | 531 |

- Q5 − Q1 = +4.1 bp and the Spearman correlation is +1.0, so the effect does grow with predicted flow,
  as the mechanism predicts.
- NQ, where LETF gamma is large relative to futures liquidity, shows a steeper gradient (Q5 − Q1 +6.5
  bp) than ES (+1.8 bp).
- The high-flow bucket is noisy (t = 1.5), because the top-φ days are also the most volatile days.
- A round trip at base cost is 1 bp on 0.5 NAV per contract, so Q5's gross +4 bp per contract-day is
  real but not reliable enough to clear the Sharpe gate.

## Reading

- **Direction:** the flow-conditioned versions do not beat the unconditional I2 on a net basis (0.39
  and 0.48 vs 0.38). Conditioning on φ lowers costs, but it also concentrates exposure in volatile
  days, so Sharpe does not improve.
- **Mechanism:** the monotone dose-response is the only positive evidence. It fits Shum et al. (2016)
  but is too weak in 2016–2020 to trade. That is consistent with Ivanov & Lenkey's (2018) capital-flow
  offset, which cannot be observed at 15:30.
- **Does not beat the 0.70 benchmark.** Nothing reached validation.
- **Forward test only:** the natural follow-up is L2 on NQ only in 2021+, when TQQQ-driven gamma is
  several times the 2016–2020 level (about 7× the 2016–2020 mean by 2026). That would be a new, post-hoc specification (it is suggested by this
  development table). Under the project's rules it must be a new pre-registration, evaluated only on
  data after 2026-09-19, not on 2021–2026.

The trial ledger grows by 2 (L1, L2).

Reproduce: `PYTHONPATH=. .venv/bin/python -m research.letf_rebalancing.evaluate dev`.

## References

- Cheng, M. & Madhavan, A. (2009). The dynamics of leveraged and inverse exchange-traded funds.
  *Journal of Investment Management* 7(4).
- Shum, P., Hejazi, W., Haryanto, E. & Rodier, A. (2016). Intraday share price volatility and
  leveraged ETF rebalancing. *Review of Finance* 20(6), 2379–2409.
- Ivanov, I. & Lenkey, S. (2018). Do leveraged ETFs really amplify late-day returns and volatility?
  *Journal of Financial Markets* 41, 36–56.
- Zhao, Y. (2026). Preying on leveraged ETFs. arXiv 2608.03703. See also "The Loop-Gain Matrix", arXiv
  2608.22768.
