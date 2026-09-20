"""Shared harness for momentum variation tests.

Every variant runs through the same point-in-time universe, the same frozen execution engine
(research.return_search.run.execute) and the same statistics, so results across experiments are
directly comparable. Signals plug in as a score DataFrame; nothing else is reimplemented.

    from research.momentum_lab.core import Lab
    lab = Lab()
    score = lab.close.shift(21) / lab.close.shift(252) - 1          # the frozen 12-1 rule
    res = lab.run('baseline', score)
    lab.show({'baseline': res})
"""
from __future__ import annotations
import json
from functools import cached_property
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'reports/momentum_lab'
INPUTS = ROOT / 'reports/momentum_verification_20260919/inputs'
END = '2026-09-17'

# Point-in-time membership is only trustworthy from 2011: the public changes ledger records
# 2 changes in 2005, 1 in 2006, 6 in 2008, against 12-26 a year from 2011 onward.
WINDOWS = {'2011..2018': ('2011-01-01', '2018-12-31'),
           '2019..2026': ('2019-01-01', END),
           '2011..2026': ('2011-01-01', END)}
COMPARATORS = ('SPMO', 'MTUM', 'SPY', 'RSP')


def _panel() -> tuple[dict[str, pd.DataFrame], pd.DatetimeIndex]:
    cached = CACHE / 'panel.parquet'
    if cached.exists():
        wide = pd.read_parquet(cached)
    else:
        frames = {}
        for p in sorted((ROOT / 'data/multiasset/stocks').glob('*.parquet')):
            d = pd.read_parquet(p)
            d.index = pd.to_datetime(d['date']).dt.tz_localize(None).dt.normalize()
            frames[p.stem] = d.sort_index().loc[:END]
        spy = pd.read_parquet(ROOT / 'data/multiasset/etf/SPY.parquet')
        spy.index = pd.to_datetime(spy['date']).dt.tz_localize(None).dt.normalize()
        dates = spy.sort_index().loc['2007':END].index
        wide = pd.concat({k: pd.DataFrame({s: d[k] for s, d in frames.items()}).reindex(dates).astype(float)
                          for k in ['open', 'close', 'volume']}, axis=1)
        CACHE.mkdir(parents=True, exist_ok=True)
        wide.to_parquet(cached)
    dates = pd.DatetimeIndex(wide.index)
    return {k: wide[k] for k in ['open', 'close', 'volume']}, dates


class Lab:
    def __init__(self, end: str = END):
        self.p, self.dates = _panel()
        self.open, self.close, self.volume = self.p['open'], self.p['close'], self.p['volume']
        self.tickers = list(self.close.columns)
        month = pd.Series(self.dates.to_period('M'), index=self.dates)
        week = pd.Series(self.dates.to_period('W'), index=self.dates)
        self.decision = {'M': month.ne(month.shift()), 'W': week.ne(week.shift())}

    # ---------- universe ----------
    @cached_property
    def adv(self) -> pd.DataFrame:
        return (self.close * self.volume).rolling(63).mean()

    @cached_property
    def member(self) -> pd.DataFrame:
        """Point-in-time S&P 500 membership, reconstructed from the dated changes ledger."""
        path = CACHE / 'member_mask.parquet'
        if path.exists():
            return pd.read_parquet(path).reindex(self.dates).fillna(False).astype(bool)
        from research.momentum_verification.membership import membership, members_on
        snap = membership()
        mask = pd.DataFrame(False, index=self.dates, columns=self.tickers)
        for d in self.dates:
            m = members_on(snap, d)
            mask.loc[d] = [t in m for t in self.tickers]
        mask.to_parquet(path)
        return mask

    def eligible(self, universe: str = 'pit') -> pd.DataFrame:
        """Frozen filter: 252 sessions of history, ADV > $20m, top 200 by ADV within the universe."""
        ok = self.close.shift(252).notna() & self.close.gt(0) & self.adv.notna()
        if universe == 'pit':
            ok &= self.member
        elif universe != 'cache':
            raise ValueError(universe)
        a = self.adv.where(ok)
        return ok & a.gt(20e6) & a.rank(axis=1, ascending=False, method='first').le(200)

    @cached_property
    def sector(self) -> pd.Series:
        c = pd.read_pickle(INPUTS / 'constituents.pkl')
        return pd.Series(c['GICS Sector'].values,
                         index=c['Symbol'].str.replace('.', '-', regex=False)).reindex(self.tickers)

    # ---------- reference data ----------
    @cached_property
    def rf(self) -> pd.Series:
        d = pd.read_parquet(ROOT / 'data/multiasset/rates/IRX.parquet')
        d.index = pd.to_datetime(d['date']).dt.tz_localize(None).dt.normalize()
        return d['close'].sort_index() / 100

    @cached_property
    def rf_daily(self) -> pd.Series:
        import research.return_search.run as rs
        return rs.cash_rates(self.dates, END)

    @cached_property
    def factors(self) -> pd.DataFrame:
        import research.momentum_verification.benchmarks as bm
        return bm.ff_factors()

    @cached_property
    def spy(self) -> pd.Series:
        d = pd.read_parquet(ROOT / 'data/multiasset/etf/SPY.parquet')
        d.index = pd.to_datetime(d['date']).dt.tz_localize(None).dt.normalize()
        return d['close'].sort_index().reindex(self.dates)

    # ---------- construction ----------
    def targets(self, score: pd.DataFrame, *, slots: int = 20, weight: str = 'equal',
                exposure: pd.Series | None = None, rebalance: str = 'M',
                sector_cap: int | None = None, universe: str = 'pit',
                min_score: float | None = 0.0) -> pd.DataFrame:
        ok = self.eligible(universe)
        dec = self.decision[rebalance]
        inv = 1.0 / self.close.pct_change(fill_method=None).rolling(21).std() if weight == 'inv_vol' else None
        t = pd.DataFrame(np.nan, index=self.dates, columns=self.tickers)
        for date in self.dates[dec]:
            s = score.loc[date].where(ok.loc[date]).replace([np.inf, -np.inf], np.nan).dropna()
            if min_score is not None:
                s = s[s > min_score]
            s = s.sort_values(ascending=False)
            if sector_cap is not None:
                keep, used = [], {}
                for tk in s.index:
                    sec = self.sector.get(tk, 'Unknown')
                    if used.get(sec, 0) < sector_cap:
                        keep.append(tk); used[sec] = used.get(sec, 0) + 1
                    if len(keep) == slots:
                        break
                chosen = keep
            else:
                chosen = list(s.index[:slots])
            t.loc[date] = 0.0
            if chosen:
                if weight == 'inv_vol':
                    w = inv.loc[date, chosen].replace([np.inf, -np.inf], np.nan).fillna(0.0)
                    w = w / w.sum() if w.sum() > 0 else pd.Series(1 / len(chosen), index=chosen)
                else:
                    w = pd.Series(1 / slots, index=chosen)
                if exposure is not None:
                    w = w * float(np.clip(exposure.get(date, 1.0), 0.0, 1.0))
                if w.sum() > 1:
                    w = w / w.sum()
                t.loc[date, chosen] = w.to_numpy()
        return t

    # ---------- evaluation ----------
    def execute(self, t: pd.DataFrame, *, stress: bool = False, start: str = '2011-01-01') -> pd.DataFrame:
        import research.return_search.run as rs
        return rs.execute(self.p, t, self.rf_daily, 'stocks', stress=stress, start=start)

    def run(self, name: str, score: pd.DataFrame, *, out: Path | None = None,
            start: str = '2011-01-01', **kw) -> dict:
        t = self.targets(score, **kw)
        res = {'name': name, 'params': {k: (v if not isinstance(v, pd.Series) else 'series') for k, v in kw.items()}}
        base_returns = None
        for label, stress in [('base', False), ('stress', True)]:
            f = self.execute(t, stress=stress, start=start)
            if label == 'base':
                base_returns = f['return']
                self.nav = f
                if out is not None:
                    out.mkdir(parents=True, exist_ok=True)
                    f.to_csv(out / f'{name}_nav.csv')
            res[label] = {w: stats(f['return'].loc[a:b], self.rf) for w, (a, b) in WINDOWS.items()}
            res[label]['turnover'] = float(f.turnover.mean() * 252)
        # fitted on the base-cost series; fitting on `f` after the loop would use the stress series
        res['attribution'] = self.attribution(base_returns.loc['2011-01-01':])
        return res

    def attribution(self, r: pd.Series, lags: int = 10) -> dict:
        import research.momentum_verification.benchmarks as bm
        j = self.factors.reindex(r.index).dropna()
        if len(j) < 250:
            return {}
        y = (r.reindex(j.index) - j['RF']).to_numpy()
        cols = ['MktRF', 'SMB', 'HML', 'RMW', 'CMA', 'UMD']
        X = np.column_stack([np.ones(len(j))] + [j[c].to_numpy() for c in cols])
        beta, se, tstat = bm.ols_hac(y, X, lags=lags)
        return {'alpha_annual': float(beta[0] * 252), 'alpha_t': float(tstat[0]),
                **{c: float(b) for c, b in zip(cols, beta[1:])}, 'n': len(j)}

    @cached_property
    def comparators(self) -> dict:
        import research.momentum_verification.benchmarks as bm
        out = {}
        for sym in COMPARATORS:
            r = bm.etf_returns(sym)
            out[sym] = {w: stats(r.loc[a:b], self.rf) for w, (a, b) in WINDOWS.items()}
        return out

    def show(self, results: dict, key: str = 'base') -> None:
        print(f'{"variant":34s} ' + ' '.join(f'{w:>17s}' for w in WINDOWS) + f' {"alpha t":>9s}')
        for n, r in results.items():
            cells = []
            for w in WINDOWS:
                s = r[key][w]
                cells.append(f'{s["cagr"]*100:7.2f}%/{s["sharpe"]:5.2f}' if s else ' ' * 17)
            a = r.get('attribution', {})
            at = f'{a.get("alpha_t", float("nan")):9.2f}' if a else ' ' * 9
            print(f'{n:34s} ' + ' '.join(f'{c:>17s}' for c in cells) + at)
        print('-' * 34)
        for n, r in self.comparators.items():
            cells = [f'{r[w]["cagr"]*100:7.2f}%/{r[w]["sharpe"]:5.2f}' if r[w] else ' ' * 17 for w in WINDOWS]
            print(f'{n:34s} ' + ' '.join(f'{c:>17s}' for c in cells))


def stats(r: pd.Series, rf: pd.Series) -> dict | None:
    r = r.dropna()
    if len(r) < 120:
        return None
    rate = rf.reindex(rf.index.union(r.index)).ffill().reindex(r.index)
    elapsed = pd.Series(r.index, index=r.index).diff().dt.days.fillna(1)
    ex = r - rate.shift().fillna(0) * elapsed / 365.25
    w = (1 + r).cumprod()
    peak = np.maximum.accumulate(np.r_[1.0, w.to_numpy()])[1:]
    years = len(r) / 252
    return {'cagr': float(w.iloc[-1] ** (1 / years) - 1), 'total': float(w.iloc[-1] - 1),
            'sharpe': float(ex.mean() / ex.std() * np.sqrt(252)), 'vol': float(r.std() * np.sqrt(252)),
            'max_dd': float(np.min(w.to_numpy() / peak - 1)), 'days': len(r)}


def sharpe_interval(r: pd.Series, rf: pd.Series, block: int = 20, draws: int = 5000):
    from research.common.inference import sharpe_ci
    rate = rf.reindex(rf.index.union(r.index)).ffill().reindex(r.index)
    elapsed = pd.Series(r.index, index=r.index).diff().dt.days.fillna(1)
    ex = (r - rate.shift().fillna(0) * elapsed / 365.25).dropna().to_numpy()
    return sharpe_ci(ex, 252, block=block, draws=draws)
