# Momentum construction sweep — signal definition and portfolio construction

**Experiment** `research/momentum_construction/` · **Registered** 2026-09-19T23:03:02-0700 in
`research/preregistrations.jsonl`, sha256 `eb07e102…` · **Harness** `research/momentum_lab/core.py`,
not modified by this experiment (a fix to it landed from another session mid-run — see §4 — and the
sweep was re-run afterwards) · **Universe** point-in-time S&P 500 (`universe='pit'`) · **Costs** 5 bps/side base,
15 bps/side stress · **Windows** 2011–2018, 2019–2026, 2011–2026.

Ten pre-registered variants, all ten run, all ten reported. No amendments were filed and no variant
outside the registered list was computed.

---

## Verdict, up front

**Nothing beat SPMO in both halves. {npass} of the ten passed.** The bar is SPMO's 0.70 Sharpe in
2011–2018 *and* 0.89 in 2019–2026. The best any variant managed in the second half was {h2hi:.2f};
SPMO's 0.89 was never approached, let alone cleared, by any construction or signal choice tested.

**The baseline's parameters were arbitrary, not badly chosen.** All ten full-window Sharpes land in
a band of {lo:.2f}–{hi:.2f} (median {med:.2f}, mean {mean:.2f}, sd {sd:.3f}, spread {spread:.2f})
around the baseline's 0.67. {nabove} of ten sit above the baseline, which is roughly what you would
expect from ten draws around a point that was not optimised in the first place. CAGR ranges more
widely ({cglo:.1f}%–{cghi:.1f}%) than Sharpe does, which is the signature of a risk dial, not an
edge: the choices that raise return raise volatility in almost exact proportion.

The spread — {spread:.2f} of Sharpe across every plausible reading of "momentum, long-only, S&P
500" — is the finding. It is the right yardstick for how seriously to take the baseline's 0.67, and
it is wide enough to contain every comparator in the table except SPMO.

---

## 1. Performance, base cost (5 bps/side)

CAGR / Sharpe.

{perf_base}

## 2. Performance, stress cost (15 bps/side)

{perf_stress}

At stress cost the band drops to {slo:.2f}–{shi:.2f} (median {smed:.2f}) and the gap to SPMO widens,
since the ETF rows are already net of fees and carry no turnover bill of their own.

## 3. Risk, turnover and cost sensitivity

{risk}

## 4. FF5+UMD attribution, 2011–2026

Newey–West, 10 lags, fitted on the **base**-cost (5 bps/side) return series. `core.py` was corrected
by another session at 23:09 today — the previous version fitted the attribution on the stress series,
because the loop variable `f` still held the last execution — and this sweep was re-run after that fix,
so every row here, including the baseline reference, is base-cost and mutually consistent. Performance
figures were unaffected by the fix.

{att}

No variant produces a statistically distinguishable alpha. Every t-statistic falls between −0.62 and
+0.94, and the baseline's own is +0.03. The UMD loadings (0.30–0.75) and market betas (0.80–1.22) are
where the returns come from: after the momentum factor is charged for, there is nothing left over in
any of the ten.

## 5. Bootstrap Sharpe intervals

20-day circular block bootstrap, 5,000 draws, 95%.

{ci}

The best full-window variant is **{bestname}** at {bestsh:.2f}, interval
**[{bestci[0]:.2f}, {bestci[1]:.2f}]**. That interval **contains the baseline's 0.67 and contains
SPMO's 0.84**. It excludes neither. On sixteen years of daily data the sampling error on a Sharpe of
this size is roughly ±0.44, which is close to three times the entire spread across the ten variants —
the ranking inside the band is not statistically resolvable.

The intervals are also not independent of one another. Daily-return correlation to the baseline runs
0.75 (C9) to 0.99 (C4), with a median pairwise correlation of 0.94 among the ten. These are ten views
of one strategy, not ten strategies.

## 6. Both-halves consistency against SPMO

{ver}

## 7. Variant-by-variant read

**Breadth (C1/C2/C3) — the slot count is a volatility dial, not an edge dial.** 10 slots returns
20.80% at 29.7% vol; 50 slots returns 16.16% at 20.7% vol. Sharpe is 0.73 and 0.75 respectively —
statistically the same number. Concentration buys return and pays for it in variance at close to
one-for-one. The baseline's 20 is unremarkable in every direction, and the small Sharpe improvement
at 30–50 names comes with a *lower* CAGR, so it is a risk preference, not a discovery.

**C4 inverse-volatility weighting — the only construction variant that is worse than the baseline.**
0.666 vs 0.674 at base cost, 0.624 vs 0.644 at stress, and the lowest CAGR of the construction group
(15.58%). It cuts volatility from 25.9% to 23.6% but cuts return by more, and it raises turnover to
9.94x — 27% above the baseline — because weights drift with realised vol between rebalances. A dead
end.

**C5 sector cap of 4 — works exactly as advertised and changes very little.** The uncapped baseline
holds a mean of 7.2 names in its largest GICS sector, peaks at 17 of 20 in one sector, and spends 34%
of months with 8 or more in one sector. The cap binds hard and constantly, yet the result moves from
0.67 to 0.74 with essentially identical CAGR (16.94% vs 16.95%) — the gain is entirely a 3.4-point
volatility reduction. Worth having as a risk control; not an alpha source.

**C6 weekly rebalance — the costs eat it, exactly as feared.** Turnover goes from 7.84x to 16.76x a
year, a 2.14x increase, and the observed cost sensitivity scales with it almost exactly: 0.196 pp of
CAGR per bp/side against the baseline's 0.091 pp (ratio 2.15). Extrapolating linearly from the two
cost points, weekly is worth **+1.52 pp of gross (zero-cost) CAGR** — there is a real
signal-freshness gain — but it surrenders the whole of it by about 14 bps/side:

- break-even cost per side where C6's **CAGR** equals the monthly baseline's: **14.5 bps/side**
- break-even cost per side where C6's **Sharpe** equals the monthly baseline's: **13.9 bps/side**
- cost per side at which C6's CAGR falls to SPY's 14.16%: 24.3 bps/side

At the harness's own stress assumption of 15 bps/side C6 has already crossed over: 15.99% / 0.640
against the baseline's 16.04% / 0.644. Weekly rebalancing is a bet that you can trade a 20-name
large-cap book at under roughly 14 bps/side all-in, and it pays nothing whatsoever if you cannot. For
an apparent edge over monthly of +0.03 Sharpe, that is not a bet worth placing.

**C7 6-1 momentum — the top of the band, and a null.** 0.77 full-window, driven almost entirely by a
0.94 first half against a 0.69 second half. It beats SPMO's 0.70 in H1 and loses to SPMO's 0.89 in
H2 by a wide margin. Under the pre-registered rule this is a null. Its turnover is also 40% above the
baseline's (10.99x vs 7.84x) for the privilege.

**C8 rank blend — the clearest failure of the signal group, and instructive.** 0.93 in the first half
collapsing to 0.45 in the second, for 0.63 overall and an alpha of −1.22% (t = −0.47). Averaging ranks across
3-1, 6-1 and 12-1 pulls weight toward the short horizon, which is where the post-2019 regime punished
momentum hardest. Diversifying across lookbacks did not stabilise anything; it imported the worst
horizon's behaviour.

**C9 52-week-high proximity — the worst variant on every measure that matters.** 0.62 base, 0.51
stress, the lowest CAGR (11.03%), and by far the highest turnover (18.50x a year for a *monthly*
rebalance), which is why it loses 0.112 of Sharpe between base and stress cost — nearly four times
the baseline's cost sensitivity. Its alpha t of −0.62 is the most negative in the table, and its
market beta of 0.80 with a UMD loading of 0.30 — both the lowest in the set — show it is barely a
momentum strategy at all: the
bounded score selects low-volatility names sitting near their highs, producing a 16.6% vol portfolio
that underperforms SPY outright. **This variant carries no positive-momentum screen**
(`min_score=None`), unlike C1–C7 and C10, because `close / rolling(252).max()` is bounded near 1 and
the default `min_score=0.0` would filter nothing. C8 likewise runs with `min_score=None`, since an
average of percentile ranks is strictly positive. Both were declared in the plan before running. See
§8 — the screen turns out to be inert for every variant anyway.

**C10 shorter skip — the most consistent variant in the set, and still a null.** Skipping five days
instead of twenty-one gives 0.77 / 0.79 across the two halves, the only variant whose two halves are
both at or above its own full-window 0.76, and it does so at *lower* turnover than the baseline
(7.45x vs 7.84x). The honest reading: over 2011–2026, in the top-200-ADV slice of the S&P 500, the
one-month reversal skip is **not earning its keep** — dropping it costs nothing and may have helped
slightly. But "may have helped slightly" means +0.09 of Sharpe inside a band of {spread:.2f}, from one
of ten shots at history this project has already mined in full. It fails the second-half bar (0.79 vs
0.89) and it is not a finding to trade on.

## 8. Diagnostics and caveats

- **The positive-momentum screen never binds.** At every one of the 190 monthly (824 weekly) decision
  dates, every variant filled all of its slots and ran at exactly 1.00 gross exposure — including C2
  at 50 slots. There were always at least 50 eligible names with positive 12-1 momentum. The
  `min_score=0.0` default is therefore inert over 2011–2026 in this universe, and the C8/C9 departure
  from it is a smaller difference than it appears.
- **Sector data is complete.** All 422 tickers that are ever eligible carry a GICS sector, so C5's cap
  never falls back to an unnamed bucket. The sector map is the *current* constituents file, so a name's
  sector is not point-in-time; reclassifications are rare enough that this is minor, but it is a known
  look-ahead in C5 of unknown direction.
- **3-1 momentum in C8** was implemented as `close.shift(21) / close.shift(63) - 1`, the reading
  consistent with the harness's 12-1 (`shift(21)/shift(252)`) and the registered C7 6-1
  (`shift(21)/shift(126)`). The plan named "3-1" without the formula; this is the only interpretive
  choice made after registration, and it affects no other variant.
- **Deflated Sharpe is the wrong instrument here, and quoting it would mislead.** Run against the best
  variant with the project's ~120-trial ledger it returns 0.99 — but that is the probability the true
  Sharpe exceeds *zero* after a multiplicity haircut. The benchmark in this experiment is not cash, it
  is a 0.84-Sharpe ETF with a ticker. Every variant clears zero comfortably; none clears SPMO.
- **Multiplicity.** These ten trials take the project ledger from roughly 110 to roughly 120. Ten shots
  at already-observed history will produce an apparent best by construction, and one did (C7 at 0.77).
  It is reported as the top of a distribution, not as a result. No follow-up tuning was run: 25 and 35
  slots were not tried after C1, a 3-name sector cap was not tried after C5, and no lookback between 6
  and 12 months was tried after C7.

## 9. Honest read

The baseline's five parameters were **arbitrary, and arbitrary turned out to be fine**. Nothing in the
construction group is badly chosen:

- **Slots (20)** is a pure volatility dial over 10–50; Sharpe is flat at 0.73–0.75 across the range.
- **Equal weighting** beats the one alternative tested — inverse-vol is lower on Sharpe, lower on
  CAGR, and costs 27% more turnover to run.
- **Monthly rebalancing** is correct unless you can trade below roughly 14 bps/side, and even then the
  prize is +0.03 Sharpe.
- **No sector constraint** is the one choice with a defensible alternative: capping at 4 names per
  sector adds ~0.07 Sharpe for free by removing a concentration the strategy does not need (17 of 20
  in a single sector at its worst). That is a risk-management improvement, not an edge, and it sits
  well inside the noise band.
- **12-1 with a one-month skip** is mid-pack. The skip specifically looks unnecessary here (C10), and
  a shorter lookback flattered the first half and not the second (C7).

What the experiment actually shows is that the *entire space* of reasonable momentum construction
choices lands in a Sharpe band of {lo:.2f}–{hi:.2f} at base cost and {slo:.2f}–{shi:.2f} at stress
cost, while SPMO — which anyone can buy, net of its fee, with no turnover to pay for — sits at 0.84
above all of it and SPY sits at 0.77 inside it. The baseline's 0.67 is not a bad draw from that
distribution; it is a slightly below-median one. But the distribution itself is the problem. No
rearrangement of these knobs produces a strategy worth running against a buyable ETF, and the second
half is where they all die: SPMO's 0.89 from 2019 onward is untouched by a maximum of {h2hi:.2f}
across every variant tested, while the first-half numbers (up to {h1hi:.2f}) are exactly what would
tempt you into believing otherwise.

**All ten land in a band around the baseline and none beats the ETF.**

---

## Files

- `REPORT.md` — this file
- `results.json` — all stats, both cost levels, three windows, attributions, bootstrap intervals,
  comparators, diagnostics
- `C1_slots30_nav.csv` … `C10_skip5_nav.csv` — daily NAV, return, turnover and holdings series at base
  cost for each variant
- `research/momentum_construction/PLAN.md` — the registered plan
- `research/momentum_construction/run.py` — the sweep
- `research/momentum_construction/report.py` + `REPORT_TEMPLATE.md` — this report's generator; every
  number in the tables is read from `results.json`, none is typed by hand
