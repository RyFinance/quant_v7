"""Overlay control: what do these overlays do to a fund you can just buy?

Applies the same five overlays the stock-book agents are testing (buy-and-hold, own 200-session
trend gate, SPY 200-session trend gate, 126-session constant-volatility scaling, gate x vol) to six
buyable ETFs, under the frozen project accounting: monthly decisions, 5bps/15bps per side on the
traded amount, daily marking, idle cash at the prior observable 13-week bill, excess Sharpe over the
same bill.

No stock panel is touched.  `research/momentum_lab/core.py` is imported, never modified.

    PYTHONPATH=. .venv/bin/python -m research.overlay_control.run
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import research.momentum_verification.benchmarks as bm
from research.momentum_lab.core import WINDOWS, stats

ROOT = Path(__file__).resolve().parents[2]
IN = ROOT / 'reports/momentum_verification_20260919/inputs'
OUT = ROOT / 'reports/overlay_control_20260919'
END = '2026-09-17'
START = '2011-01-01'

UNDERLYINGS = ['SPMO', 'MTUM', 'SPY', 'RSP', 'QQQ', 'IWM']
OVERLAYS = ['O0', 'O1', 'O2', 'O3', 'O4']
OVERLAY_LABEL = {
    'O0': 'buy and hold',
    'O1': 'own 200d gate',
    'O2': 'SPY 200d gate',
    'O3': 'const-vol 20%',
    'O4': 'gate x const-vol',
}
COST = {'base': 5 / 10000, 'stress': 15 / 10000}
MA_WINDOW = 200
VOL_WINDOW = 126
VOL_TARGET = 0.20


# ---------------------------------------------------------------- data


def closes(symbol: str) -> pd.Series:
    """Adjusted closes, same file and index handling as benchmarks.etf_returns."""
    d = pd.read_parquet(IN / f'{symbol}.parquet')
    d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
    return d['Close'].sort_index().loc[:END].astype(float)


def cash_accrual(dates: pd.DatetimeIndex) -> pd.Series:
    """Per-session cash accrual: prior observable 13-week bill over elapsed days / 365.25.

    Identical construction to research.return_search.run.cash_rates.
    """
    s = bm.rf_daily()
    elapsed = pd.Series(dates, index=dates).diff().dt.days.fillna(1)
    rate = s.reindex(s.index.union(dates)).ffill().reindex(dates).shift().fillna(0)
    return rate * elapsed / 365.25


# ---------------------------------------------------------------- signals


def signal_frames(symbol: str) -> dict:
    """Everything an overlay may look at, indexed on the fund's own sessions.

    Each series is stated as of the close of its own date; the overlay reads it with .shift(1) so a
    month-start decision at t can only see data through t-1.
    """
    c = closes(symbol)
    r = c.pct_change()
    spy = closes('SPY')
    spy_above = (spy > spy.rolling(MA_WINDOW).mean()).where(spy.rolling(MA_WINDOW).mean().notna())
    return {
        'close': c,
        'ret': r,
        'above': (c > c.rolling(MA_WINDOW).mean()).where(c.rolling(MA_WINDOW).mean().notna()),
        'vol': r.rolling(VOL_WINDOW).std() * np.sqrt(252),
        'spy_above': spy_above.reindex(c.index),
    }


def exposure_path(sig: dict, overlay: str, dates: pd.DatetimeIndex, lag: int = 1) -> pd.Series:
    """Exposure in force for each session, decided only at month starts from data through t-lag."""
    own = sig['above'].shift(lag).reindex(dates)
    spy = sig['spy_above'].shift(lag).reindex(dates)
    vol = sig['vol'].shift(lag).reindex(dates)

    if overlay == 'O0':
        target = pd.Series(1.0, index=dates)
    elif overlay == 'O1':
        target = own.astype(float)
    elif overlay == 'O2':
        target = spy.astype(float)
    elif overlay == 'O3':
        target = np.minimum(1.0, VOL_TARGET / vol)
    elif overlay == 'O4':
        target = own.astype(float) * np.minimum(1.0, VOL_TARGET / vol)
    else:
        raise ValueError(overlay)
    target = target.clip(0.0, 1.0)

    month = pd.Series(dates.to_period('M'), index=dates)
    decision = month.ne(month.shift()).to_numpy()
    decision[0] = True                                    # fund the book on day one
    e = pd.Series(np.nan, index=dates)
    e[decision] = target[decision]
    return e.ffill().fillna(0.0), pd.Series(decision, index=dates)


# ---------------------------------------------------------------- execution


def simulate(r: pd.Series, e: pd.Series, decision: pd.Series, dates: pd.DatetimeIndex,
             cost: float) -> pd.DataFrame:
    """Daily-marked NAV.  Trade at the decision close, then hold through the session.

    Costs are charged on the traded amount at each decision; a final liquidation is charged, as the
    frozen engine does.  Cash earns the prior observable bill over elapsed days.
    """
    acc = cash_accrual(dates).to_numpy()
    ret = r.reindex(dates).to_numpy()
    exp = e.to_numpy()
    dec = decision.to_numpy()
    cash, eq, prior = 1.0, 0.0, 1.0
    rows = []
    for i in range(len(dates)):
        nav0 = cash + eq
        fee = 0.0
        traded = 0.0
        if dec[i]:
            new_nav = nav0
            for _ in range(15):                            # fee is charged out of the same NAV
                desired = exp[i] * new_nav
                fee = abs(desired - eq) * cost
                new_nav = nav0 - fee
            traded = abs(desired - eq) / nav0
            cash = nav0 - fee - desired
            eq = desired
        if not np.isfinite(ret[i]):
            raise ValueError(f'missing mark {dates[i]}')
        eq *= 1 + ret[i]
        cash *= 1 + acc[i]
        nav = cash + eq
        if nav <= 0 or cash < -1e-9:
            raise ValueError(f'insolvency or leverage {dates[i]}')
        rows.append((dates[i], nav / prior - 1, nav, fee / nav0, traded, eq / nav))
        prior = nav
    f = pd.DataFrame(rows, columns=['date', 'return', 'nav', 'cost', 'turnover', 'gross']).set_index('date')
    liquidation = eq * cost
    prev = f.nav.iloc[-2] if len(f) > 1 else 1.0
    f.iloc[-1, f.columns.get_loc('nav')] -= liquidation
    f.iloc[-1, f.columns.get_loc('return')] = f.nav.iloc[-1] / prev - 1
    f.iloc[-1, f.columns.get_loc('cost')] += liquidation / prev
    f.iloc[-1, f.columns.get_loc('turnover')] += eq / prev
    return f


def window_stats(f: pd.DataFrame, rf: pd.Series) -> dict:
    out = {}
    for label, (a, b) in WINDOWS.items():
        g = f.loc[a:b]
        s = stats(g['return'], rf)
        if s:
            s['avg_exposure'] = float(g.gross.mean())
            s['annual_turnover'] = float(g.turnover.mean() * 252)
            s['annual_cost'] = float(g.cost.mean() * 252)
            s['start'] = str(g.index[0].date())
            s['end'] = str(g.index[-1].date())
        out[label] = s
    return out


# ---------------------------------------------------------------- causality


def causality_test(sig: dict, dates: pd.DatetimeIndex) -> list[dict]:
    """Perturb every price after a cut date; the exposure path up to the cut must not move."""
    results = []
    rng = np.random.default_rng(20260919)
    for cut in ['2013-06-28', '2016-01-04', '2020-03-23', '2024-07-01']:
        cut_ts = pd.Timestamp(cut)
        if cut_ts <= dates[0] or cut_ts >= dates[-1]:
            continue
        c = sig['close'].copy()
        future = c.index > cut_ts
        shock = pd.Series(rng.uniform(0.3, 3.0, size=int(future.sum())), index=c.index[future])
        c.loc[future] = c.loc[future] * shock                       # arbitrary future prices
        r = c.pct_change()
        spy = sig['spy_above']                                       # SPY perturbed separately below
        perturbed = {
            'close': c, 'ret': r,
            'above': (c > c.rolling(MA_WINDOW).mean()).where(c.rolling(MA_WINDOW).mean().notna()),
            'vol': r.rolling(VOL_WINDOW).std() * np.sqrt(252),
            'spy_above': spy,
        }
        sc = closes('SPY').copy()
        fut2 = sc.index > cut_ts
        sc.loc[fut2] = sc.loc[fut2] * rng.uniform(0.3, 3.0, size=int(fut2.sum()))
        sma = sc.rolling(MA_WINDOW).mean()
        perturbed['spy_above'] = (sc > sma).where(sma.notna()).reindex(sig['close'].index)
        for ov in ['O1', 'O2', 'O3', 'O4']:
            base, _ = exposure_path(sig, ov, dates)
            pert, _ = exposure_path(perturbed, ov, dates)
            upto = dates <= cut_ts
            same = bool(np.allclose(base[upto].to_numpy(), pert[upto].to_numpy(), equal_nan=True))
            moved = bool(not np.allclose(base[~upto].to_numpy(), pert[~upto].to_numpy(), equal_nan=True))
            results.append({'cut': cut, 'overlay': ov, 'prefix_unchanged': same,
                            'suffix_moved': moved, 'n_prefix': int(upto.sum())})
    return results


# ---------------------------------------------------------------- drawdown forensics


def episodes(spy: pd.Series) -> dict:
    """Peak / trough / recovery of the two fast drawdowns the brief asks about."""
    out = {}
    for name, (a, b) in {'2020': ('2020-01-01', '2021-06-30'), '2025': ('2025-01-01', '2026-09-17')}.items():
        s = spy.loc[a:b]
        dd = s / s.cummax() - 1
        trough = dd.idxmin()
        peak = s.loc[:trough].idxmax()
        after = s.loc[trough:]
        rec = after[after >= s.loc[peak]]
        out[name] = {'peak': peak, 'trough': trough,
                     'recovery': rec.index[0] if len(rec) else s.index[-1],
                     'depth': float(dd.min())}
    return out


# ---------------------------------------------------------------- main


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rf = bm.rf_daily()
    spy_close = closes('SPY')
    eps = episodes(spy_close)

    results: dict = {}
    navs: dict = {}
    exposures: dict = {}
    starts: dict = {}
    causality: dict = {}

    for sym in UNDERLYINGS:
        sig = signal_frames(sym)
        r = bm.etf_returns(sym).loc[:END]
        ready = sig['above'].notna() & sig['vol'].notna() & sig['spy_above'].notna()
        usable = r.index[(r.index >= pd.Timestamp(START)) & ready.reindex(r.index).fillna(False)]
        dates = pd.DatetimeIndex(usable)
        starts[sym] = str(dates[0].date())
        print(f'{sym}: {len(dates)} sessions, {dates[0].date()} .. {dates[-1].date()}', flush=True)

        causality[sym] = causality_test(sig, dates)

        for ov in OVERLAYS:
            e, dec = exposure_path(sig, ov, dates)
            exposures[f'{sym}|{ov}'] = e
            row = {'label': OVERLAY_LABEL[ov], 'start': starts[sym]}
            for cl, cost in COST.items():
                f = simulate(r, e, dec, dates, cost)
                row[cl] = window_stats(f, rf)
                if cl == 'base':
                    navs[f'{sym}|{ov}'] = f
            # one-session implementation lag, base cost only
            e2, dec2 = exposure_path(sig, ov, dates, lag=2)
            f2 = simulate(r, e2, dec2, dates, COST['base'])
            row['lag2'] = window_stats(f2, rf)
            results[f'{sym}|{ov}'] = row

    # ---- dilution controls: same average exposure, held statically, per window and cost
    dilution: dict = {}
    for sym in UNDERLYINGS:
        r = bm.etf_returns(sym).loc[:END]
        dates_full = navs[f'{sym}|O0'].index
        for ov in OVERLAYS:
            for cl in COST:
                for w, (a, b) in WINDOWS.items():
                    s = results[f'{sym}|{ov}'][cl][w]
                    if not s:
                        continue
                    wd = dates_full[(dates_full >= pd.Timestamp(a)) & (dates_full <= pd.Timestamp(b))]
                    ebar = s['avg_exposure']
                    month = pd.Series(wd.to_period('M'), index=wd)
                    dec = month.ne(month.shift())
                    dec.iloc[0] = True
                    ef = pd.Series(ebar, index=wd)
                    f = simulate(r, ef, dec, wd, COST[cl])
                    st = stats(f['return'], rf)
                    dilution[f'{sym}|{ov}|{cl}|{w}'] = {
                        'exposure': ebar, 'cagr': st['cagr'], 'sharpe': st['sharpe'],
                        'vol': st['vol'], 'max_dd': st['max_dd']}

    # ---- drawdown forensics for the gates
    forensics: dict = {}
    for name, ep in eps.items():
        for sym in UNDERLYINGS:
            bh = navs[f'{sym}|O0']
            if bh.index[0] > ep['peak']:
                continue
            for ov in ['O1', 'O2', 'O4']:
                f = navs[f'{sym}|{ov}']
                e = exposures[f'{sym}|{ov}']
                seg = e.loc[ep['peak']:ep['recovery']]
                month = pd.Series(seg.index.to_period('M'), index=seg.index)
                mstart = seg[month.ne(month.shift())]
                def cum(g, a, b):
                    x = g['return'].loc[a:b]
                    return float((1 + x).prod() - 1)
                forensics[f'{name}|{sym}|{ov}'] = {
                    'peak': str(ep['peak'].date()), 'trough': str(ep['trough'].date()),
                    'recovery': str(ep['recovery'].date()),
                    'exposure_at_month_starts': {str(d.date()): round(float(v), 3) for d, v in mstart.items()},
                    'exposure_on_trough_day': round(float(e.asof(ep['trough'])), 3),
                    'peak_to_trough_overlay': cum(f, ep['peak'], ep['trough']),
                    'peak_to_trough_bh': cum(bh, ep['peak'], ep['trough']),
                    'trough_to_recovery_overlay': cum(f, ep['trough'], ep['recovery']),
                    'trough_to_recovery_bh': cum(bh, ep['trough'], ep['recovery']),
                    'peak_to_recovery_overlay': cum(f, ep['peak'], ep['recovery']),
                    'peak_to_recovery_bh': cum(bh, ep['peak'], ep['recovery']),
                }

    payload = {'starts': starts, 'results': results, 'dilution': dilution,
               'causality': causality, 'forensics': forensics,
               'episodes': {k: {kk: (str(vv.date()) if isinstance(vv, pd.Timestamp) else vv)
                                for kk, vv in v.items()} for k, v in eps.items()}}
    (OUT / 'results.json').write_text(json.dumps(payload, indent=2, default=float))

    d = OUT / 'diagnostics'
    d.mkdir(exist_ok=True)
    for k, f in navs.items():
        f.to_csv(d / (k.replace('|', '__') + '_base.csv'))
    pd.DataFrame(exposures).to_csv(d / 'exposure_paths.csv')

    ok = all(c['prefix_unchanged'] for v in causality.values() for c in v)
    moved = all(c['suffix_moved'] for v in causality.values() for c in v)
    print(f'\ncausality: prefix unchanged in all {sum(len(v) for v in causality.values())} tests = {ok};'
          f' suffix actually moved = {moved}')

    print(f'\n{"variant":24s} ' + ' '.join(f'{w:>16s}' for w in WINDOWS))
    for k, row in results.items():
        cells = []
        for w in WINDOWS:
            s = row['base'][w]
            cells.append(f'{s["cagr"]*100:6.2f}%/{s["sharpe"]:5.2f}' if s else ' ' * 16)
        print(f'{k:24s} ' + ' '.join(f'{c:>16s}' for c in cells))
    print(f'\nwrote {OUT/"results.json"}')


if __name__ == '__main__':
    main()
