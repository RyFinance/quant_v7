"""Fixed-rule downside-aware ETF rotation; exploratory, no parameter search."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research.share_class import simulate, describe
from research.higher_sharpe import cash_rates

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/downside_rotation_20260919'
UNIVERSE=['SPY','QQQ','IWM','EFA','EEM','VNQ','GLD','IEF','TLT','TIP','LQD','DBC']
SPEC={'universe':UNIVERSE,'score':'mean 63,126,252 session returns / 63 session downside deviation', 'selection':'positive score; greedy score discounted by maximum positive correlation to selected assets; top four', 'rebalance':'first trading session monthly close, next open execution', 'weighting':'inverse 63-day volatility; scale to 12% trailing 126-day portfolio volatility, maximum 150% gross, 50% per asset', 'base_roundtrip_bps':10,'stress_roundtrip_bps':25,'debit_financing':'daily risk-free plus 1% annual spread','development':['2008','2016'],'evaluation':['2017','2025-06-27'],'warning':'exploratory reused historical period, no untouched holdout claim','controls':['momentum_only','equal_weight']}

def targets(close,mode='primary'):
    r=close.pct_change(fill_method=None)
    momentum=sum(close/close.shift(k)-1 for k in [63,126,252])/3
    downside=np.minimum(r,0).pow(2).rolling(63).mean().pow(.5)*np.sqrt(252)
    vol=r.rolling(63).std()*np.sqrt(252)
    score=momentum/downside
    out=pd.DataFrame(np.nan,index=close.index,columns=close.columns)
    month=pd.Series(close.index.to_period('M'),index=close.index)
    for date in close.index[month.ne(month.shift())]:
        w=pd.Series(0.,index=close.columns)
        history=r.loc[:date].iloc[-126:]
        good=(momentum.loc[date]>0)&vol.loc[date].gt(0)&score.loc[date].notna()
        eligible=list(close.columns[good])
        if mode=='equal_weight':
            eligible=list(close.columns[close.loc[date].notna() & vol.loc[date].gt(0)])
            if eligible:w.loc[eligible]=1/len(eligible)
        elif eligible:
            ranked=(momentum if mode=='momentum_only' else score).loc[date,eligible]
            selected=[]
            corr=history.corr()
            while len(selected)<min(4,len(eligible)):
                candidates=ranked.drop(selected)
                if selected and mode=='primary':
                    penalty=1-corr.loc[candidates.index,selected].clip(0,1).max(axis=1).fillna(1)
                    candidates=candidates*penalty
                selected.append(candidates.idxmax())
            w.loc[selected]=1/vol.loc[date,selected]
            w/=w.sum()
        active=w>0
        if active.any():
            h=history.loc[:,active].dropna()
            if len(h)<100:w*=0
            else:
                estimate=(h*w[active]).sum(axis=1).std()*np.sqrt(252)
                w*=min(1.5,.12/estimate) if estimate>0 else 0
                w=w.clip(upper=.5)
        out.loc[date]=w
    return out

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    spec=json.dumps(SPEC,sort_keys=True,indent=2)
    p=OUT/'registration.json'
    if p.exists():assert p.read_text()==spec
    else:p.write_text(spec)
    frames={}; hashes={}
    for symbol in UNIVERSE:
        p=ROOT/f'data/multiasset/etf/{symbol}.parquet'
        hashes[symbol]=hashlib.sha256(p.read_bytes()).hexdigest()
        d=pd.read_parquet(p).set_index('date').sort_index();d.index=pd.to_datetime(d.index).tz_localize(None)
        frames[symbol]=d.loc['2006':'2025-06-27']
    dates=frames['SPY'].index
    close=pd.DataFrame({s:d.close for s,d in frames.items()}).reindex(dates)
    opens=pd.DataFrame({s:d.open for s,d in frames.items()}).reindex(dates)
    rf=cash_rates().reindex(dates)
    (OUT/'input_hashes.json').write_text(json.dumps(hashes,indent=2))
    result={}
    for mode in ['primary','momentum_only','equal_weight']:
        t=targets(close,mode);t.to_csv(OUT/f'{mode}_targets.csv'); result[mode]={}
        for label,cost in [('base',10),('stress',25)]:
            f=simulate(opens,close,t,rf,[list(range(len(close.columns)))],cost=cost,start='2008-01-01')
            f.to_csv(OUT/f'{mode}_{label}.csv')
            result[mode][label]={'development':describe(f.loc['2008':'2016'],rf),'evaluation':describe(f.loc['2017':],rf),'recent':describe(f.loc['2021':],rf)}
            if label=='base':result[mode]['yearly']={str(y):describe(x,rf) for y,x in f.groupby(f.index.year)}
        print(mode,json.dumps(result[mode]['base']),flush=True)
    result['target_met']=bool(result['primary']['base']['evaluation']['excess_sharpe']>=2 and result['primary']['base']['evaluation']['cagr']>.1)
    result['code_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (OUT/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
if __name__=='__main__':main()
