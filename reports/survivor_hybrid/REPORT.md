# Survivor hybrids of published anomalies (OSAP): out-of-sample result

Tester agent, 2026-09-19. Pre-registered in `research/survivor_hybrid/PLAN.md` (sha256 80713d3f…,
registered 2026-09-19T11:47:18-0700). No hybrid return after 2014 had been computed at that point.
No rule, cost or gate was changed after the results. Everything after the main table labelled
"post hoc" is diagnosis, not a new trial.

**Verdict: FAIL. None of the four hybrids passes.**

- **H1 and H4 come closest** (net Sharpe 0.72 and 0.70), but both still fail.
  - They fall just short of the 0.75 Sharpe gate.
  - They fail the deflated-Sharpe gate by a wide margin: 0.03–0.04 against 0.95.
  - About half of their net Sharpe comes from one 10-stock component in one month (GameStop,
    January 2021).
- **The diversified and large-cap versions are near zero after costs:** H2 inverse-vol 0.12 and H3
  large-cap 0.06.
- **In the stocks we can trade, the survivors are worth about 0.1 net.** This matches the graveyard
  finding.

- **Code:** `research/survivor_hybrid/core.py` (selection, weights, haircut) and `evaluate.py`
  (`select` reads data through 2014 only; `run` refuses to start unless the PLAN is registered).
- **Tests:** `tests/test_survivor_hybrid.py`, 10 passing. They check that the selection is unchanged
  when post-2014 data are scrambled, that weights use trailing data only, the haircut, the
  equal-risk grouping and the registration guard.
- **Outputs:** `survivors.csv` (sha256 4f8aa144…), `results.json`, `returns_oos.csv`,
  `components_oos.csv`.
- **Reproduce:** `PYTHONPATH=. .venv/bin/python research/survivor_hybrid/evaluate.py run`

## Caveat: the evaluation window is partly contaminated

The graveyard study (`reports/edge_graveyard/`) had already reported 2015–2024 figures:
- every predictor's 2015–2024 Sharpe;
- averages by mechanism and category;
- the top 2015+ survivors;
- the 2015–2024 Sharpe of an equal-weight blend of all 212 predictors (1.38 gross).

This composite was never computed there, and the selection uses only data through 2014. But the
rule was written by someone who had seen those tables, so 2015–2024 is not a clean holdout. Rule 1
("published before 2010") excludes the strongest known 2015+ survivors (SmileSlope, EarningsStreak,
GP, dVolCall and others), which argues against deliberate tuning. The contamination still cannot be
ruled out, and it would bias results upward, not downward.

## Selection (data through 2014-12 only)

- **Rule:** published ≤ 2009; original-paper long-short t ≥ 2 from sample end to 2014; positive mean
  after publication through 2014; ex-microcap version t ≥ 1 over the same post-sample window.
- **Result: 53 of 212** (165 pass the publication rule).
- **By mechanism:**
  - M4 slow reaction: 24
  - M6 risk premia: 19
  - M2 forced flows / seasonality: 5
  - M1 new data: 2
  - M3 limits to arbitrage: 2
  - M5 economic links: 1
- **By data source:** accounting 30, price 10, analyst 6, event 3, volume 2, options 1, 13F 1.
- **Holding period:** 28 monthly, 25 six-monthly or annual.
- The full list is in the PLAN.

## Out-of-sample result, 2015-01 → 2024-12 (120 months, net of a haircut of R = 30 bps × m(holding period))

| | H1 equal | H2 inv-vol | H3 large-cap | H4 mechanism | C0 all ≤2009 | C0_LC |
|---|---|---|---|---|---|---|
| **Net Sharpe** (gate ≥ 0.75) | **0.72** | **0.12** | **0.06** | **0.70** | 0.48 | −0.43 |
| 95% interval (gate: low > 0) | [−0.02, 1.35] | [−0.83, 0.95] | [−0.64, 0.70] | [0.02, 1.34] | [−0.24, 1.13] | [−1.21, 0.30] |
| Deflated Sharpe, N = 84 (gate ≥ 0.95) | 0.03 | 0.00 | 0.00 | 0.04 | 0.01 | 0.00 |
| **Gate** | fail | fail | fail | fail (interval only) | — | — |
| Gross Sharpe | 1.34 | 1.18 | 0.72 | 1.41 | 1.32 | 0.42 |
| Net Sharpe at R = 20 / 40 | 0.92 / 0.51 | 0.47 / −0.23 | 0.28 / −0.16 | 0.94 / 0.46 | 0.76 / 0.20 | −0.15 / −0.71 |
| Avg haircut (bps/month) | 20.5 | 20.7 | 20.5 | 23.0 | 19.9 | 19.8 |
| Net return / vol (ann.) | 2.9% / 4.0% | 0.3% / 2.4% | 0.2% / 3.7% | 2.7% / 3.9% | 1.4% / 2.9% | −1.2% / 2.8% |
| Max drawdown, net | −11.7% | −11.2% | −11.2% | −8.3% | −9.0% | −13.5% |
| Worst month / skew | −2.2% / +1.82 | −1.6% / +0.87 | −3.2% / +0.38 | −2.2% / +0.57 | −1.8% / +0.89 | −2.5% / +0.14 |
| Correlation with Mkt-RF (beta) | −0.04 (−0.01) | −0.16 (−0.02) | −0.06 (−0.01) | −0.29 (−0.07) | −0.40 (−0.07) | −0.27 (−0.05) |
| CAPM alpha, net (t) | 3.0% (2.3) | 0.6% (0.7) | 0.4% (0.3) | 3.5% (2.9) | 2.2% (2.6) | −0.6% (−0.7) |
| Net Sharpe 2015–19 / 2020–24 | −0.23 / 1.26 | −1.02 / 0.77 | −0.25 / 0.22 | 0.15 / 1.10 | −0.20 / 0.95 | −0.76 / −0.27 |
| Break-even R for net Sharpe 0.75 / 0 (bps) | 28 / 65 | 12 / 33 | 0 / 33 | 28 / 59 | 20 / 47 | 0 / 15 |
| null_kind at 0.5 | vacuous | vacuous | vacuous | positive | vacuous | bounded null |
| Gross Sharpe 2005–14 (in-sample, selection period) | 3.06 | 2.76 | 1.58 | 2.87 | 1.49 | 0.69 |

- **Market (Mkt-RF), 2015–2024:** Sharpe 0.74, max drawdown −25%.
- **Correlations among hybrids:** 0.70–0.86. They are one bet, built from the same components.
- **Deflated Sharpe under other trial variances (not gated):**
  - within-run variance: H1 0.27, H4 0.27;
  - sampling variance 1/(T−1): 0.41 and 0.39;
  - N = 80: 0.03 and 0.04.

  None comes near 0.95, so this verdict does not depend on the variance choice.

Net return by year (%):

| | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 0.1 | 5.2 | −2.6 | −2.1 | −3.1 | 1.4 | 18.4 | 8.3 | 1.5 | 3.0 |
| H2 | −1.2 | 2.2 | −3.3 | −2.2 | −3.5 | −1.0 | 9.8 | 6.0 | −3.6 | 0.1 |
| H3 | −0.7 | 3.9 | −2.3 | −2.9 | −0.9 | −3.2 | 4.8 | 8.9 | −2.1 | −3.1 |
| H4 | 1.3 | 4.6 | −0.9 | −1.7 | −1.3 | −0.0 | 15.0 | 8.0 | 0.7 | 1.9 |

## Reading

1. **The two near-misses rest on one 10-stock portfolio and one month (post hoc).**
   - IO_ShortInterest (institutional ownership among heavily shorted stocks) holds a median of 5
     stocks long and 5 short.
   - Its 2015+ mean is 8.4% a month with 36% monthly volatility. It returned +321% in January 2021,
     the GameStop squeeze.
   - At a 1/53 weight it supplies 36% of H1's gross mean, and 6.1 of H1's 6.7-point January 2021
     net return.
   - Without it, net Sharpe falls sharply:
     - H1: from 0.72 to 0.34;
     - H4: from 0.70 to 0.23 (weights recomputed);
     - C0: from 0.48 to 0.29.
   - Dropping only January 2021 leaves H1 at 0.65 and H4 at 0.63.
   - A 10-stock squeeze portfolio is not a tradable edge. Its short leg holds hard-to-borrow names,
     so the flat 30 bps haircut is far too low for it.
2. **All of the return came in 2021–2022.** This was the value/junk rebound.
   - H1 net was roughly flat from 2015 to 2020 (2015–19 Sharpe −0.23), then made +18% in 2021 and
     +8% in 2022.
   - This is one regime, not a steady premium.
3. **Decay is severe.** H1's gross Sharpe fell from 3.06 in the selection decade to 1.34 out of
   sample. This fits McLean–Pontiff: selecting on past survival does not prevent further decay.
4. **The survival filter adds little.**
   - H1 net 0.72 against C0 (no filter) 0.48 is mostly IO_ShortInterest: 0.34 against 0.29 without
     it.
   - H3 0.06 against C0_LC −0.43 is a real but small gain, and it is still near zero.
5. **Large-cap and risk-balanced versions do not survive costs.**
   - Inverse-vol weighting (H2) moves weight to low-volatility, low-return spreads. The same haircut
     then eats almost all of the mean.
   - The value-weighted versions (H3) earn 0.72 gross and 0.06 net.
   - The median survivor's own 2015+ gross Sharpe is 0.34, and its mean net Sharpe is 0.04.
6. **The hybrids diversify well** (market correlation −0.04 to −0.29; H4 CAPM alpha t = 2.9). But the
   net return is 0–3% a year at 2–4% volatility, and the deflated Sharpe rules the result out given
   about 84 trials.

## Implementability (H1, the highest base net Sharpe, as pre-registered)

**Costs.**
- H1 needs monthly-rebalance costs ≤ 28 bps to reach 0.75 net, and ≤ 65 bps to stay above 0.
- These academic portfolios are equal-weighted and include microcaps. Their short legs are often
  hard to borrow, so 30 bps a month is optimistic. At 40 bps H1 nets 0.51, or 0.07 without
  IO_ShortInterest (post hoc).
- One unmodelled factor works the other way: netting trades across components would lower costs.
  That does not rescue the result.

**What we could rebuild.** Judged from each SignalDoc definition against our data:
- 33 of 53 need data we lack:
  - IBES (6): AnalystRevision, REV6, UpRecomm, DownRecomm, ConsRecomm, ChangeInRecommendation;
  - 13F or short interest (2): IO_ShortInterest, ShortInterest;
  - balance-sheet, cash-flow or tax items (22): Accruals, AccrualsBM, AdExp, BM, BMdec, ChInv,
    ChInvIA, CompositeDebtIssuance, DebtIssuance, DelEqu, DelFINL, DelLTI, dNoa, Frontier,
    GrSaleToGrInv, MS, NetDebtFinance, OperProf, PS, RD, Tax, XFIN;
  - IPO or exchange histories (3): AgeIPO, IndIPO, ExchSwitch.
- 2 need industry codes that are not on disk: IndMom and IndRetBig. IndRetBig also trades small
  firms, which are outside our universe.
- The vault's fundamentals are income statement only.

The remaining 18 can be rebuilt, at least approximately, from our data:

| component | our inputs | OSAP 2015+ Sharpe: gross / net / large-cap gross | survivorship bias in current-member data |
|---|---|---|---|
| NetPayoutYield | LSE dividends + share-count changes (proxy for buybacks − issuance) | 0.96 / 0.91 / 0.59 | against (short = issuers) |
| ShareIss5Y | vault share counts | 0.88 / 0.80 / 1.05 | against |
| ShareIss1Y | vault share counts | 0.82 / 0.75 / 0.49 | against (our F1 test of it failed dev, −0.85) |
| VolumeTrend | daily volume | 0.89 / 0.70 / 0.43 | unclear |
| AnnouncementReturn | earnings dates + prices | 0.57 / 0.08 / 0.30 | against (short = bad news) |
| CPVolSpread | OPRA ATM IV (pull in progress, 86 names) | 0.57 / 0.02 / 0.57 | neutral |
| SP | revenue, shares, price | 0.56 / 0.50 / −0.25 | for (long cheap/distressed survivors) |
| DivYieldST | LSE dividends | 0.53 / −0.10 / 0.23 | neutral |
| MomSeason16YrPlus | prices (needs 16–20 years: signals only from 2019) | 0.48 / 0.11 / 0.44 | neutral |
| CompEquIss | shares × price, returns | 0.47 / 0.01 / 0.55 | against |
| EP | EPS, price | 0.25 / −0.03 / 0.28 | for |
| CoskewACX | daily prices | 0.19 / −0.13 / 0.10 | neutral |
| MomOffSeason06YrPlus, MomSeason11YrPlus, MomSeason06YrPlus | prices | 0.13, 0.07, −0.28 gross | neutral |
| EarningsSurprise | vault EPS | 0.06 / −0.47 / −0.01 | against (plain SUE, already dead) |
| MRreversal, LRreversal | prices | −0.05, −0.17 gross | for (long past losers) |

Post hoc and descriptive, not a trial: an equal-weight blend of these 18, in OSAP's own survivor-free
CRSP data, earns 1.02 gross and 0.42 net for all stocks. In the large-cap versions it earns 0.79
gross and **0.08 net**. Even a perfect rebuild of what we can rebuild would be worth about 0.1 in the
names we can trade.

**Survivorship.** Our stock universe is current S&P members only. The same-stock control scored about
1.0 Sharpe in `reports/fundamentals`.
- **Bias for the signal** (SP, EP, MRreversal, LRreversal): these would be inflated on our data and
  cannot be validated.
- **Bias against** (the issuance/payout family, AnnouncementReturn, EarningsSurprise): these are the
  only components where a positive backtest on our data would mean something. But the bias is
  strong: our ShareIss1Y-style test already failed development at −0.85 because its short leg was
  full of later winners.
- **Neutral** (the seasonality family, DivYieldST, CoskewACX, CPVolSpread): these earn about 0 or less
  net of costs in OSAP 2015+.

**Recommendation.** Nothing here is tradable for us. The one family that is strong, low-turnover and
large-cap-relevant in OSAP is net payout / share issuance (NetPayoutYield, ShareIss5Y). Testing it
fairly needs a survivorship-free database with delisted names and point-in-time fundamentals (CRSP/
Compustat or an equivalent vendor), plus a fresh pre-registered window or a forward test. It should
not be picked from this table, which is post hoc on a contaminated window. The trial ledger rises by
4, to about 84.
