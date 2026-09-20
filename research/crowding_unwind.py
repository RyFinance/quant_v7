"""Custom positioning-unwind signal, causal publication lag, explicit funding."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.share_class import simulate, describe
from research.higher_sharpe import cash_rates
from research.fx_session_screen import bootstrap
from backtest.research import block_sharpe_difference

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/crowding_unwind_20260919/availability_corrected'
SPEC=ROOT/'research/crowding_unwind_spec_20260919.json'


def available_dates(report,release):
    known=pd.concat([report+pd.Timedelta(days=7),release+pd.Timedelta(days=1)],axis=1).max(axis=1)
    interrupted=report.between('2018-12-18','2019-03-05')|report.between('2023-01-24','2023-03-14')
    known.loc[interrupted]=pd.concat([known.loc[interrupted],report.loc[interrupted]+pd.Timedelta(days=60)],axis=1).max(axis=1)
    # Features use earlier reports: wait for all of those reports as well.
    # Input is sorted by report date within one contract.
    return known.cummax()


def build_position_signals(cot,mapping,dates):
    strength=pd.DataFrame(0.,index=dates,columns=mapping)
    known_rows=[]
    for etf,symbol in mapping.items():
        d=cot[cot.symbol==symbol].copy().sort_values('date')
        if d.date.duplicated().any():
            raise ValueError(f'duplicate COT report date {symbol}')
        ratio=(pd.to_numeric(d.noncomm_long)-pd.to_numeric(d.noncomm_short))/pd.to_numeric(d.open_interest).replace(0,np.nan)
        z=(ratio-ratio.rolling(52,min_periods=40).mean().shift())/ratio.rolling(52,min_periods=40).std().shift()
        change=ratio.diff(4)
        value=pd.Series(0.,index=d.index)
        long=(z < -1)&(change>0)
        short=(z > 1)&(change<0)
        value.loc[long]=z.loc[long].abs().clip(1,3)
        value.loc[short]=-z.loc[short].abs().clip(1,3)
        report=pd.to_datetime(d.date)
        known=available_dates(report,pd.to_datetime(d.release_date))
        records=pd.DataFrame({'known':known,'report':report,'value':value}).sort_values(['known','report'])
        # At each date only reports already available can win. A late stale report
        # must not overwrite a more recent report which was already published.
        by_date=[]
        for date in dates:
            eligible=records[records.known<=date]
            if eligible.empty:
                by_date.append(0.)
            else:
                newest=eligible.sort_values('report').iloc[-1]
                by_date.append(float(newest.value) if (date-newest.report).days<=100 else 0.)
        strength[etf]=by_date
        known_rows.extend({'symbol':symbol,'report':str(r.report.date()),'known':str(r.known.date())} for r in records.itertuples())
    return strength,known_rows


def size_targets(signal,close):
    returns=close.pct_change(fill_method=None)
    vol=returns.rolling(63).std()*np.sqrt(252)
    targets=pd.DataFrame(np.nan,index=close.index,columns=close.columns)
    periods=pd.Series(close.index.to_period('W'),index=close.index)
    decisions=periods.ne(periods.shift())
    for date in close.index[decisions]:
        s=signal.loc[date].where(vol.loc[date]>0).fillna(0)
        w=(s/vol.loc[date]).replace([np.inf,-np.inf],np.nan).fillna(0)
        if w.abs().sum():w*=2/w.abs().sum()
        w=w.clip(-.5,.5)
        active=w!=0
        if active.any():
            hist=returns.loc[:date].iloc[-63:,active.to_numpy()].dropna()
            if len(hist)<40:
                w*=0
            else:
                portfolio=(hist*w[active]).sum(axis=1)
                forecast=portfolio.std()*np.sqrt(252)
                if forecast>0:w*=min(1,.1/forecast)
                else:w*=0
        targets.loc[date]=w
    return targets


def main():
    spec=json.loads(SPEC.read_text())
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest()==json.loads((OUT/'registration.json').read_text())['sha256']
    cotpath=ROOT/'data/cot_edge_20260918/cot.parquet'
    cot=pd.read_parquet(cotpath)
    hashes={str(cotpath.relative_to(ROOT)):hashlib.sha256(cotpath.read_bytes()).hexdigest()}
    frames={}
    for symbol in spec['map']:
        p=ROOT/f'data/multiasset/etf/{symbol}.parquet'
        hashes[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
        d=pd.read_parquet(p).set_index('date').sort_index()
        d.index=pd.to_datetime(d.index).tz_localize(None)
        frames[symbol]=d.loc['2014':'2025-06-27']
    dates=frames['SPY'].index
    c=pd.DataFrame({s:d.close for s,d in frames.items()}).reindex(dates)
    o=pd.DataFrame({s:d.open for s,d in frames.items()}).reindex(dates)
    position,audit=build_position_signals(cot,spec['map'],dates)
    (OUT/'availability_audit.json').write_text(json.dumps(audit,indent=2))
    (OUT/'input_hashes.json').write_text(json.dumps(hashes,indent=2))
    momentum=c/c.shift(20)-1
    signals={'crowding_unwind':position.where(np.sign(position)==np.sign(momentum),0),
             'positioning_only':position,'price_only':np.sign(momentum)}
    rf=cash_rates().reindex(dates)
    results,paths={},{}
    for name,signal in signals.items():
        t=size_targets(signal,c)
        t.to_csv(OUT/f'{name}_targets.csv')
        results[name]={}
        for label,cost,borrow in [('base',10,.03),('stress',25,.10)]:
            f=simulate(o,c,t,rf,[[i] for i in range(len(c.columns))],cost=cost,borrow=borrow,start='2016-01-01')
            f.to_csv(OUT/f'{name}_{label}.csv')
            paths[name,label]=f
            results[name][label]={period:describe(f.loc[a:b],rf) for period,(a,b) in spec['periods'].items()}
        results[name]['yearly']={str(y):describe(f,rf) for y,f in paths[name,'base'].groupby(paths[name,'base'].index.year)}
        print(name,json.dumps(results[name]['base']),flush=True)
    primary=results['crowding_unwind']
    ex=paths['crowding_unwind','base']['return'].loc['2021':]-rf
    ci=bootstrap(ex.dropna(),20);ci.pop('three_candidate_bonferroni_p')
    p=primary['base']['evaluation']
    meets=p['excess_sharpe']>=2 and p['cagr']>.1
    gate=meets and primary['stress']['evaluation']['ann_excess_mean']>0 and ci['one_sided_null_p']<.05 and all(primary['yearly'][str(y)]['ann_excess_mean']>0 for y in range(2021,2025))
    paired=block_sharpe_difference(ex,paths['price_only','base']['return'].loc['2021':]-rf,block=20)
    results['decision']={'numerical_target_met':bool(meets),'research_gate_met':bool(gate),'uncertainty':ci,'paired_sharpe_difference_vs_price_only':paired,'live_changed':False}
    results['code_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (OUT/'results.json').write_text(json.dumps(results,indent=2,allow_nan=False))
    print(results['decision'],flush=True)


if __name__=='__main__':main()
