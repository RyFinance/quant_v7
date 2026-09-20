"""Render reports/overlay_control_20260919/REPORT.md from results.json."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'reports/overlay_control_20260919'
U = ['SPMO', 'MTUM', 'SPY', 'RSP', 'QQQ', 'IWM']
O = ['O0', 'O1', 'O2', 'O3', 'O4']
OV = ['O1', 'O2', 'O3', 'O4']
W = ['2011..2018', '2019..2026', '2011..2026']
NAME = {'O0': 'buy and hold', 'O1': 'own 200d gate', 'O2': 'SPY 200d gate',
        'O3': 'const-vol 20%', 'O4': 'gate x const-vol'}

p = json.loads((OUT / 'results.json').read_text())
R, D, F, C = p['results'], p['dilution'], p['forensics'], p['causality']
S = p['starts']
L: list[str] = []


def w(s=''):
    L.append(s)


def sh(sym, ov, cl, win):
    return R[f'{sym}|{ov}'][cl][win]['sharpe']


def delta(sym, ov, cl, win):
    return sh(sym, ov, cl, win) - sh(sym, 'O0', cl, win)


# ---------------------------------------------------------------- headline
w('# Overlay control — what the same overlays do to a fund you can just buy')
w()
w('`reports/overlay_control_20260919/` · plan registered '
  '`research/overlay_control/PLAN.md` (sha256 `cf3ef76c…`) before any result was computed · '
  'run with `PYTHONPATH=. .venv/bin/python -m research.overlay_control.run`')
w()
w('Five overlays — buy-and-hold, own 200-session trend gate, SPY 200-session trend gate, '
  '126-session constant-volatility scaling, and gate x vol — applied to six buyable ETFs under the '
  'frozen project accounting. 30 variants, exactly the 30 registered. No stock panel was used and '
  '`research/momentum_lab/core.py` was not modified (its `stats` and `WINDOWS` are imported).')
w()
w('## The number the other agents need')
w()
w('**Sharpe improvement each overlay delivers on a buyable fund, as a delta from buy-and-hold on '
  'the same fund and window, base costs.** Positive means the overlay helped.')
w()
head = '| underlying | ' + ' | '.join(f'{o} {NAME[o]}' for o in OV) + ' |'
for win in W:
    w(f'### {win}')
    w()
    w(head)
    w('|---|' + '---|' * len(OV))
    for s in U:
        w(f'| {s} (B&H {sh(s,"O0","base",win):.2f}) | ' +
          ' | '.join(f'**{delta(s,o,"base",win):+.2f}**' for o in OV) + ' |')
    d = [delta(s, o, 'base', win) for s in U for o in OV]
    w('| *median across the six funds* | ' +
      ' | '.join(f'{np.median([delta(s,o,"base",win) for s in U]):+.2f}' for o in OV) + ' |')
    w()
    w(f'All 24 cells this window: median **{np.median(d):+.3f}**, mean {np.mean(d):+.3f}, '
      f'{sum(x>0 for x in d)} of 24 positive, best {max(d):+.3f}, worst {min(d):+.3f}.')
    w()

w('### Stress costs (15bps/side) — same deltas')
w()
w('| window | median ΔSharpe | positive cells | best | worst |')
w('|---|---|---|---|---|')
for win in W:
    d = [delta(s, o, 'stress', win) for s in U for o in OV]
    w(f'| {win} | {np.median(d):+.3f} | {sum(x>0 for x in d)} of 24 | {max(d):+.3f} | {min(d):+.3f} |')
w()

# ---------------------------------------------------------------- verdict
both = [(s, o) for s in U for o in OV
        if delta(s, o, 'base', '2011..2018') > 0 and delta(s, o, 'base', '2019..2026') > 0]
w('## Verdict')
w()
w(f'**Not one of the 24 overlay × underlying combinations improves Sharpe in both halves.** '
  f'{len(both)} of 24 are positive in both 2011–2018 and 2019–2026, at base costs and at stress '
  f'costs alike.')
w()
w('- **2011–2018:** 12 of 24 positive, median −0.006. A coin flip.')
w('- **2019–2026:** **0 of 24 positive.** Every overlay on every fund lost Sharpe, best case '
  '−0.02, worst −0.33, median −0.16.')
w('- **2011–2026:** 1 of 24 positive (SPMO × O1, +0.013, and that one is an artefact of SPMO\'s '
  'short history — see the caveat below).')
w()
w('By the project\'s own rule — a result only counts if it survives in both halves — **every '
  'overlay is a null on buyable funds.** That is the control number. If a stock-book overlay '
  'raises the stock book\'s Sharpe, it is not because the overlay is a good idea in general; on a '
  'fund you can just buy, the identical overlay costs Sharpe in the second half without exception.')
w()

# ---------------------------------------------------------------- per overlay
w('## How to use this against a stock-book claim')
w()
w('If a stock-book overlay reports a Sharpe gain ΔS, the honest comparison is ΔS minus the number '
  'in the matrix above for the same overlay and window. The relevant row is usually **SPY** (the '
  'market-state comparison) or **SPMO** (the thing anyone can actually buy instead of the book):')
w()
w('| overlay | ΔSharpe on SPY, 2019–2026 | ΔSharpe on SPMO, 2019–2026 | ΔSharpe on SPY, 2011–2026 |')
w('|---|---|---|---|')
for o in OV:
    w(f'| {o} {NAME[o]} | {delta("SPY", o, "base", "2019..2026"):+.2f} | '
      f'{delta("SPMO", o, "base", "2019..2026"):+.2f} | '
      f'{delta("SPY", o, "base", "2011..2026"):+.2f} |')
w()
w('All of these are negative, so an overlay that raises the stock book\'s Sharpe is doing '
  'something to the *stock book* that it does not do to a fund — it is not market timing, because '
  'market timing, measured here, subtracts Sharpe. Two consequences:')
w()
w('1. A stock-book gain is not automatically discounted by this control; there is nothing to '
  'discount by, because the control effect is negative. But it does mean the gain has to be '
  'explained by something specific to the 20-name book (turnover reduction, crash exposure of the '
  'selected names, concentration), not by "trend gates work".')
w('2. The relevant bar is still absolute: **SPMO buy-and-hold is 0.84 over 2011–2026 and 0.89 in '
  '2019–2026.** Any gated or vol-scaled stock book has to clear that, not merely clear the '
  'ungated stock book. The best overlaid ETF variant in this entire matrix is SPMO × O1 at 0.86 '
  'full-record — which is SPMO buy-and-hold plus 0.01, on a short sample, with turnover.')
w()
w('## Which overlays help, which hurt')
w()
w('| overlay | 2011–2018 mean Δ | 2019–2026 mean Δ | 2011–2026 mean Δ | survives both halves anywhere? |')
w('|---|---|---|---|---|')
for o in OV:
    a = np.mean([delta(s, o, 'base', '2011..2018') for s in U])
    b = np.mean([delta(s, o, 'base', '2019..2026') for s in U])
    c = np.mean([delta(s, o, 'base', '2011..2026') for s in U])
    hit = [s for s in U if delta(s, o, 'base', '2011..2018') > 0 and delta(s, o, 'base', '2019..2026') > 0]
    w(f'| **{o}** {NAME[o]} | {a:+.3f} | {b:+.3f} | {c:+.3f} | {"no" if not hit else ", ".join(hit)} |')
w()
w('- **O1 own 200-day gate** — the least bad. Helps a little in the first half on 4 of 6 funds, '
  'hurts on all 6 in the second. Its only large positive (SPMO +0.33 in 2011–2018) rests on 2.4 '
  'years of data, not 8.')
w('- **O2 SPY 200-day gate** — the one the stock-book agent is testing, and **the worst of the '
  'four.** Mean −0.15 over the full record, −0.27 in the second half. Applying SPY\'s market state '
  'to something that is not SPY throws away the fund\'s own information and adds nothing: on SPY '
  'itself O1 and O2 are the same series (a useful internal check — they agree to the last digit), '
  'and on the five funds that are not SPY, O2 is worse than O1 in the second half on 4 of 5 '
  '(SPMO −0.25, QQQ −0.27, MTUM −0.21, IWM −0.18; RSP is the exception at +0.01).')
w('- **O3 constant-vol scaling** — nearly inert in the first half (mean −0.01, it barely binds: '
  'average exposure 0.96–1.00) and mildly negative in the second (mean −0.10), where it binds more '
  'because realised vol was higher. It does not lose much because it does not do much.')
w('- **O4 gate × vol** — stacks O1\'s second-half damage on O3\'s. Worst full-record mean of the '
  'three own-fund overlays on 4 of 6 funds.')
w()

# ---------------------------------------------------------------- full matrix
w('## Full matrix — underlying × overlay')
w()
w('One NAV path per (underlying, overlay) from the effective start, sliced by window, exactly as '
  '`Lab.run` does. CAGR / excess Sharpe / annualised vol / max drawdown / average exposure / '
  'annual turnover. Costs charged on the traded amount at each monthly decision, plus entry and a '
  'final liquidation.')
w()
w('Effective starts (first session at which the fund\'s own 200-session MA, its own 126-session '
  'vol and SPY\'s 200-session MA are all defined): ' +
  ', '.join(f'**{s}** {S[s]}' for s in U) + '.')
w()
for cl, tag in [('base', 'Base costs — 5bps per side'), ('stress', 'Stress costs — 15bps per side')]:
    w(f'### {tag}')
    w()
    for win in W:
        w(f'**{win}**')
        w()
        w('| underlying | overlay | CAGR | Sharpe | ΔSharpe | vol | max DD | avg exp | ann turnover |')
        w('|---|---|---|---|---|---|---|---|---|')
        for s in U:
            for o in O:
                st = R[f'{s}|{o}'][cl][win]
                d = '' if o == 'O0' else f'{delta(s,o,cl,win):+.2f}'
                w(f'| {s} | {o} {NAME[o]} | {st["cagr"]*100:.2f}% | {st["sharpe"]:.2f} | {d} | '
                  f'{st["vol"]*100:.1f}% | {st["max_dd"]*100:.1f}% | {st["avg_exposure"]:.2f} | '
                  f'{st["annual_turnover"]*100:.0f}% |')
        w()
w()

# ---------------------------------------------------------------- dilution
w('## How much of each effect is just dilution')
w()
w('For every variant, a **static blend** of the same underlying with T-bills, held at the '
  'overlay\'s own average exposure for that window, monthly-rebalanced under the same cost model. '
  'An overlay that matches its own dilution control has done nothing; one that is *below* its '
  'dilution control has done harm.')
w()
_gap = max(abs(v['sharpe'] - sh(k.split('|')[0], 'O0', k.split('|')[2], k.split('|')[3]))
           for k, v in D.items())
w('The blunt fact first: **a static blend keeps the underlying\'s Sharpe almost exactly.** Across '
  f'all {len(D)} dilution cells the control\'s Sharpe never differs from buy-and-hold\'s by more '
  f'than **{_gap:.3f}** — diluting with T-bills scales return and volatility together and leaves '
  'the ratio alone. So the entire question is whether the overlay\'s *timing* beat holding the '
  'same average exposure all the time. Mostly it did not, and the Sharpe delta versus the dilution '
  'control is therefore all but identical to the Sharpe delta versus buy-and-hold reported above.')
w()
w('| underlying | overlay | window | avg exp | overlay CAGR | dilution CAGR | timing ΔCAGR | overlay Sharpe | dilution Sharpe | timing ΔSharpe |')
w('|---|---|---|---|---|---|---|---|---|---|')
for s in U:
    for o in OV:
        for win in W:
            a = R[f'{s}|{o}']['base'][win]
            d = D[f'{s}|{o}|base|{win}']
            w(f'| {s} | {o} | {win} | {a["avg_exposure"]:.2f} | {a["cagr"]*100:.2f}% | '
              f'{d["cagr"]*100:.2f}% | {(a["cagr"]-d["cagr"])*100:+.2f}% | {a["sharpe"]:.2f} | '
              f'{d["sharpe"]:.2f} | {a["sharpe"]-d["sharpe"]:+.2f} |')
w()
neg2 = sum(1 for s in U for o in OV
           if R[f'{s}|{o}']['base']['2019..2026']['cagr'] < D[f'{s}|{o}|base|2019..2026']['cagr'])
neg1 = sum(1 for s in U for o in OV
           if R[f'{s}|{o}']['base']['2011..2018']['cagr'] < D[f'{s}|{o}|base|2011..2018']['cagr'])
w(f'**In 2019–2026 the overlay lost to its own dilution control on {neg2} of 24 cells** — the '
  f'timing component was negative every time, by −0.4% to −7.0% a year. In 2011–2018 it lost on '
  f'{neg1} of 24. Over the full record the timing term costs roughly 1%–5% a year *on top of* the '
  'dilution. Read the other way: an overlay that ends up at, say, 0.80 average exposure has thrown '
  'away a fifth of the fund\'s return for no Sharpe gain, and then paid a timing penalty on top of '
  'that. Holding 80% of the fund and 20% T-bills gets the same risk reduction, no turnover, and '
  'keeps the Sharpe.')
w()

# ---------------------------------------------------------------- forensics
w('## The one thing the gates genuinely deliver: drawdown')
w()
w('Sharpe is not the only thing a risk overlay is bought for, and it would be dishonest to stop at '
  'the Sharpe table. **The trend gates cut maximum drawdown materially, and by more than dilution '
  'alone explains.** Over 2011–2026 at base costs:')
w()
w('| fund | B&H max DD | O1 max DD | O1 dilution-control max DD | O1 beyond dilution | O4 max DD | O4 beyond dilution |')
w('|---|---|---|---|---|---|---|')
for s in U:
    b = R[f'{s}|O0']['base']['2011..2026']['max_dd']
    a1 = R[f'{s}|O1']['base']['2011..2026']['max_dd']
    d1 = D[f'{s}|O1|base|2011..2026']['max_dd']
    a4 = R[f'{s}|O4']['base']['2011..2026']['max_dd']
    d4 = D[f'{s}|O4|base|2011..2026']['max_dd']
    w(f'| {s} | {b*100:.1f}% | {a1*100:.1f}% | {d1*100:.1f}% | {(a1-d1)*100:+.1f}pp | '
      f'{a4*100:.1f}% | {(a4-d4)*100:+.1f}pp |')
w()
w('O1 is shallower than buy-and-hold on all 6 funds (by 6.5 to 15.3 points) and shallower than its '
  'own dilution control on all 6 (by 1.8 to 10.6 points). O4 likewise, on all 6. O2 and O3 do not: '
  'O2 is *deeper* than its dilution control on 3 of 6, and O3 barely moves drawdown at all — it '
  'scales on trailing realised vol, which rises after a drawdown rather than before it, so it '
  'de-risks into the recovery.')
w()
w('So the honest statement is: **an own-fund 200-day trend gate buys you 6.5–15 points of maximum '
  'drawdown, and you pay 2.6%–4.6% a year of CAGR and −0.05 of Sharpe on average over the full '
  'record (−0.12 on average in 2019–2026) for it.** Whether that is a good trade is a preference, '
  'not a research finding — but it is emphatically not alpha, and it is not what a momentum stock '
  'book is being built to produce. If drawdown is the objective, say so and measure against it; if '
  'Sharpe is the objective, these overlays fail.')
w()
w('## Did the monthly gate sell the bottom?')
w()
e = p['episodes']
w(f'**2020:** SPY peak {e["2020"]["peak"]}, trough {e["2020"]["trough"]} ({e["2020"]["depth"]*100:.1f}%), '
  f'back to the peak {e["2020"]["recovery"]}. '
  f'**2025:** peak {e["2025"]["peak"]}, trough {e["2025"]["trough"]} ({e["2025"]["depth"]*100:.1f}%), '
  f'recovered {e["2025"]["recovery"]}.')
w()
w('**It did not sell the exact bottom — it sold before the bottom and bought back after the '
  'rebound, which is worse.** Both fates show up:')
w()
w('- **2020.** The gate went flat at the 2 March month start, ahead of most of the crash (the '
  'funds fell a further 17%–32% from that close to the 23 March trough, so the sell itself '
  'was timely). It was then flat for the entire April–May rebound and only re-entered on '
  '1 June — after the funds had already risen 33%–39% off the trough. On RSP and IWM the own-fund '
  'gate stayed out until 3 August.')
w('- **2025.** The gate sold at the 1 April month start, **five sessions before the 8 April '
  'trough**, after the funds had already fallen 4.8%–13.0% from the peak, with only 10.5%–12.4% '
  'of the fall left to avoid. That is selling the bottom. It re-entered on 2 June, by which point '
  'the funds had already risen 15%–29% off the trough.')
w()
w('| episode | fund | overlay | exposure on the trough day | peak→trough overlay vs B&H | trough→recovery overlay vs B&H | peak→recovery overlay vs B&H |')
w('|---|---|---|---|---|---|---|')
for k, v in F.items():
    ep, s, o = k.split('|')
    w(f'| {ep} | {s} | {o} | {v["exposure_on_trough_day"]:.2f} | '
      f'{v["peak_to_trough_overlay"]*100:+.1f}% vs {v["peak_to_trough_bh"]*100:+.1f}% | '
      f'{v["trough_to_recovery_overlay"]*100:+.1f}% vs {v["trough_to_recovery_bh"]*100:+.1f}% | '
      f'**{v["peak_to_recovery_overlay"]*100:+.1f}% vs {v["peak_to_recovery_bh"]*100:+.1f}%** |')
w()
behind = sum(1 for v in F.values() if v['peak_to_recovery_overlay'] < v['peak_to_recovery_bh'])
w(f'**{behind} of {len(F)} (fund × gate × episode) cells finish the round trip behind buy-and-hold.** '
  'The gate did reliably cut the drawdown — in 2020 it took −12% or −13% peak-to-trough on five of '
  'the six funds, against −27% to −40% for buy-and-hold (QQQ is the exception: its own 200-day '
  'gate never triggered, so O1 rode the full −27%) — and then gave all of it back and more by '
  'being in cash for the rebound. That is the mechanism behind the uniformly negative 2019–2026 '
  'deltas: the second half contains two fast V-shaped drawdowns, and a monthly-evaluated trend '
  'gate is structurally short the V.')
w()
w('The four cells that *do* finish ahead are 2020 RSP × O2 (−3.5% vs −5.1%), 2020 IWM × O2 (−0.5% '
  'vs −5.1%), 2025 IWM × O1 (−4.3% vs −4.7%) and 2025 IWM × O4 (−3.8% vs −4.7%) — all cases where '
  'the fund itself had not recovered by the SPY-defined recovery date, so the comparison is '
  'against a buy-and-hold that is still under water. None of them is a margin worth anything, and '
  'none of the four translates into a positive second-half Sharpe delta.')
w()
w('Exposure at every month start through both episodes is in `results.json` under `forensics`; the '
  'full daily exposure path for all 30 variants is `diagnostics/exposure_paths.csv`.')
w()

# ---------------------------------------------------------------- causality
n = sum(len(v) for v in C.values())
ok = all(c['prefix_unchanged'] for v in C.values() for c in v)
mv = all(c['suffix_moved'] for v in C.values() for c in v)
w('## Causality')
w()
w(f'**Passed.** Every price after a cut date was multiplied by an independent random factor drawn '
  f'uniformly on [0.3, 3.0] — for the fund and, separately, for SPY — and the exposure path was '
  f'recomputed. Across **{n} tests** (6 underlyings × O1–O4 × cut dates 2013-06-28, 2016-01-04, '
  f'2020-03-23, 2024-07-01, skipping cuts outside a fund\'s history) the exposure path on every '
  f'date at or before the cut was **bit-identical in all {n}**: `prefix_unchanged = {ok}`. As a '
  f'guard against a vacuous pass, the path after the cut *did* change in all {n} as well '
  f'(`suffix_moved = {mv}`), so the test had the power to detect leakage. Test code: '
  f'`research/overlay_control/run.py::causality_test`.')
w()
w('Construction: every signal series is stated as of its own close and read with `.shift(1)`, so a '
  'month-start decision at *t* sees closes through *t−1* only. The trade is booked at the *t−1* '
  'close and the position is held through session *t*.')
w()
w('**One-session implementation lag.** Because the *t−1* close is also the trade price, a natural '
  'objection is that the result depends on trading the signal bar. Re-running O1–O4 with the '
  'exposure applied one session later (`lag=2`, base costs, 2011–2026 Sharpe):')
w()
w('| fund | O1 | O2 | O3 | O4 |')
w('|---|---|---|---|---|')
for s in U:
    w(f'| {s} | ' + ' | '.join(
        f'{R[f"{s}|{o}"]["base"]["2011..2026"]["sharpe"]:.2f} → '
        f'{R[f"{s}|{o}"]["lag2"]["2011..2026"]["sharpe"]:.2f}' for o in OV) + ' |')
w()
w('The delay moves individual cells by up to 0.15 in both directions and changes nothing '
  'qualitatively. Under the one-session delay: **0 of 24 cells are positive over the full record** '
  '(best −0.024), **0 of 24 are positive in 2019–2026** (best −0.013, median −0.138), 12 of 24 are '
  'positive in 2011–2018 (median −0.000), and **0 of 24 survive both halves**. The conclusion is '
  'not an artefact of the fill convention — if anything the delayed version is slightly worse.')
w()

# ---------------------------------------------------------------- caveats
w('## Caveats, stated plainly')
w()
w(f'1. **SPMO and MTUM have short first halves.** SPMO\'s usable record starts {S["SPMO"]} and '
  f'MTUM\'s {S["MTUM"]}, because the 200-session moving average needs 200 sessions. The '
  '`2011..2018` row for SPMO is 2.4 years, not 8. Its +0.33 O1 delta is the single largest '
  'positive in the whole matrix and it comes from **exactly one decision**: SPMO\'s gate was on '
  'continuously from 2016-08-01, went flat at the 2018-11-01 month start, and sat out the December '
  '2018 selloff. Calendar 2018 is +7.23% for O1 against −0.92% for buy-and-hold; the 2016-07 to '
  '2017-12 stretch is identical for both (+29.32%) because the gate never moved. One month of one '
  'short sample, and it reverses to −0.07 in the second half. It is not evidence for anything.')
w('2. **O0 is charged costs.** Entry, and a final liquidation, at 5bps/15bps, like the frozen '
  'engine\'s passive. This costs buy-and-hold about 1bp a year over the full record and makes the '
  'deltas very slightly generous to the overlays.')
w('3. **All overlays for a given fund share one start date**, so O0 and O1–O4 are on identical '
  'date ranges and the deltas are clean. This is why the SPMO buy-and-hold row here reads '
  '10.75% / 0.65 for 2011–2018 rather than the README comparator\'s 0.70 — the comparator starts '
  'at SPMO\'s 2015-10-12 inception. On the funds with full history the reconstruction matches the '
  'raw comparators to 0.01 CAGR and 0.01 Sharpe in all three windows, which is the engine check.')
w('4. **This is a control, not a candidate.** Nothing here is proposed as a strategy and nothing '
  'was selected on. All 30 registered variants are reported: 6 buy-and-hold references and 24 '
  'overlay cells, of which 23 lose Sharpe over the full record, 24 lose it in the second half, and '
  '0 survive both halves.')
w()
w('## Files')
w()
w('- `research/overlay_control/PLAN.md` — the pre-registration, ledgered before any computation')
w('- `research/overlay_control/run.py` — engine, signals, causality test, forensics')
w('- `reports/overlay_control_20260919/results.json` — every number above')
w('- `reports/overlay_control_20260919/diagnostics/` — 30 daily NAV series, and the exposure paths')

(OUT / 'REPORT.md').write_text('\n'.join(L) + '\n')
print('wrote', OUT / 'REPORT.md', len(L), 'lines')
