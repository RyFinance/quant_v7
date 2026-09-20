"""Same-issuer relative value, explicit financing and short collateral."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.higher_sharpe import cash_rates
from research.etf_convergence_screen import metrics
from research.fx_session_screen import bootstrap

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'reports/share_class_20260918'
SPEC = ROOT/'research/share_class_spec_20260918.json'


def pair_targets(close, gross=2):
    ratio = np.log(close.iloc[:, 0] / close.iloc[:, 1])
    z = (ratio - ratio.rolling(126).mean()) / ratio.rolling(126).std()
    target = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    age, entry_sign, held = 0, 0, False
    for i in range(len(close)):
        if held:
            age += 1
            if not np.isfinite(z.iloc[i]) or abs(z.iloc[i]) <= .5 or np.sign(z.iloc[i]) != entry_sign or age >= 30:
                target.iloc[i] = 0
                held = False
        elif np.isfinite(z.iloc[i]) and abs(z.iloc[i]) >= 2:
            entry_sign = np.sign(z.iloc[i])
            target.iloc[i] = [-entry_sign * gross / 2, entry_sign * gross / 2]
            held, age = True, 0
        else:
            target.iloc[i] = 0
    return target


def simulate(opens, closes, targets, rf, groups, cost=10, borrow=.03, debit_spread=.01, start='2015-01-01'):
    cash = previous_nav = 1.
    shares = np.zeros(len(closes.columns))
    previous_short = 0.
    arr_o, arr_c, arr_w = (x.to_numpy() for x in [opens, closes, targets])
    rates = rf.reindex(closes.index).to_numpy()
    rows = []
    for i, date in enumerate(closes.index):
        if date < pd.Timestamp(start):
            continue
        free = cash - previous_short
        if not np.isfinite(rates[i]):
            raise ValueError('missing RF')
        interest = max(free, 0) * rates[i]
        funding = max(-free, 0) * (rates[i] + debit_spread / 252)
        cash += interest - funding
        op, cp = arr_o[i], arr_c[i]
        held = shares != 0
        if np.any(held & (~np.isfinite(op) | ~np.isfinite(cp) | (op <= 0) | (cp <= 0))):
            raise ValueError(f'missing held mark {date}')
        old = shares * np.nan_to_num(op)
        nav_open = cash + old.sum()
        if nav_open <= 0:
            raise ValueError(f'insolvent {date}')
        w = arr_w[i-1] if i else np.full(len(shares), np.nan)
        desired = old.copy()
        changed = np.zeros(len(shares), dtype=bool)
        # Each issuer is its own book; NaN means hold actual units, not target weights.
        for group in groups:
            if np.isfinite(w[group]).all():
                if not (np.isfinite(op[group]).all() and (op[group] > 0).all()):
                    if (shares[group] != 0).any():
                        raise ValueError('missing exit')
                    continue
                changed[group] = True
        # Reserve entry/exit costs before sizing active groups.
        post_nav = nav_open
        for _ in range(12):
            desired[changed] = w[changed] * post_nav
            fee = np.abs(desired - old).sum() * cost / 20000
            post_nav = nav_open - fee
        turnover = np.abs(desired - old).sum()
        cash -= (desired - old).sum() + fee
        shares[changed] = desired[changed] / op[changed]
        if np.any((shares != 0) & (~np.isfinite(cp) | (cp <= 0))):
            raise ValueError('missing new close')
        marked = shares * np.nan_to_num(cp)
        previous_short = np.abs(np.minimum(marked, 0)).sum()
        short_fee = previous_short * borrow / 252
        cash -= short_fee
        nav = cash + marked.sum()
        if nav <= 0:
            raise ValueError('insolvent')
        rows.append((date, nav/previous_nav-1, nav, np.abs(marked).sum()/nav,
                     turnover/nav_open, fee/nav_open, short_fee/nav_open, funding/nav_open, interest/nav_open))
        previous_nav = nav
    out = pd.DataFrame(rows, columns=['date','return','nav','gross','turnover','trading_cost','borrow','funding','interest']).set_index('date')
    if len(out):
        liquidation = np.abs(marked).sum()*cost/20000
        prior = out.nav.iloc[-2] if len(out)>1 else 1.
        out.iloc[-1,out.columns.get_loc('nav')] -= liquidation
        out.iloc[-1,out.columns.get_loc('return')] = out.nav.iloc[-1]/prior-1
        out.iloc[-1,out.columns.get_loc('trading_cost')] += liquidation/prior
        out.iloc[-1,out.columns.get_loc('turnover')] += np.abs(marked).sum()/prior
    return out


def describe(f,rf):
    out = metrics(f['return'],rf)
    if not np.isfinite(out['excess_sharpe']):
        out['excess_sharpe'] = None
        out['ratio_status'] = 'undefined: no excess-return variation'
    out.update({f'ann_{c}':float(f[c].mean()*252) for c in ['turnover','trading_cost','borrow','funding']})
    out['avg_gross'] = float(f.gross.mean())
    return out


def main():
    spec=json.loads(SPEC.read_text())
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest()==json.loads((OUT/'registration.json').read_text())['sha256']
    spy=pd.read_parquet(ROOT/'data/multiasset/etf/SPY.parquet')
    dates=pd.DatetimeIndex(pd.to_datetime(spy.date)).tz_localize(None)
    dates=dates[(dates>='2013-01-01')&(dates<='2025-06-27')]
    all_o,all_c,all_t,hashes={},{},{},{}
    for n,pair in spec['pairs'].items():
        frames={}
        for s in pair:
            p=ROOT/f'data/multiasset/stocks/{s}.parquet'
            hashes[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
            d=pd.read_parquet(p).set_index('date').sort_index()
            d.index=pd.to_datetime(d.index).tz_localize(None)
            frames[s]=d.loc[spec['true_inception'][n]:].reindex(dates)
        all_o[n]=pd.DataFrame({s:d.open for s,d in frames.items()})
        all_c[n]=pd.DataFrame({s:d.close for s,d in frames.items()})
        all_t[n]=pair_targets(all_c[n])
    (OUT/'input_hashes.json').write_text(json.dumps(hashes,indent=2))
    rf=cash_rates().reindex(dates)
    names=list(all_t)
    all_o['primary_book']=pd.concat(list(all_o.values()),axis=1)
    all_c['primary_book']=pd.concat(list(all_c.values()),axis=1)
    all_t['primary_book']=pd.concat([x/3 for x in all_t.values()],axis=1)
    res,paths={},{}
    for name in names+['primary_book']:
        o,c,t=all_o[name],all_c[name],all_t[name]
        groups=[list(range(i,i+2)) for i in range(0,len(c.columns),2)]
        res[name]={}
        for label,cost,borrow in [('base',10,.03),('stress',25,.10)]:
            f=simulate(o,c,t,rf,groups,cost=cost,borrow=borrow)
            paths[name,label]=f
            f.to_csv(OUT/f'{name}_{label}.csv')
            res[name][label]={'development':describe(f.loc['2015':'2020'],rf),'evaluation':describe(f.loc['2021':],rf)}
        res[name]['yearly']={str(y):describe(f,rf) for y,f in paths[name,'base'].groupby(paths[name,'base'].index.year)}
        print(name,json.dumps(res[name]['base']),flush=True)
    primary=res['primary_book']
    ex=paths['primary_book','base']['return'].loc['2021':]-rf
    ci=bootstrap(ex.dropna(),20);ci.pop('three_candidate_bonferroni_p')
    p=primary['base']['evaluation']
    meets=p['excess_sharpe']>=2 and p['cagr']>.1
    gate=meets and primary['stress']['evaluation']['ann_excess_mean']>0 and ci['one_sided_null_p']<.05 and all(primary['yearly'][str(y)]['ann_excess_mean']>0 for y in range(2021,2025))
    res['decision']={'numerical_target_met':bool(meets),'research_gate_met':bool(gate),'primary_uncertainty':ci,'live_changed':False}
    res['code_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (OUT/'results.json').write_text(json.dumps(res,indent=2,allow_nan=False))
    print(res['decision'],flush=True)


if __name__=='__main__':
    main()
