from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/return_search_20260919'
END_DEV='2025-06-30'
END_TEST='2026-09-17'
START='2019-01-01'
RULES=['momentum','trend','breakout']
ML=['ridge_price','boost_price','ridge_enriched','boost_enriched']
CANDIDATES={'stocks':RULES+ML,'etf':RULES+ML,'crypto':['trend','breakout','ridge_price','boost_price'],'vol':['contango','contango_trend']}
HASHES={}


def read(path,end):
    HASHES[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    d=pd.read_parquet(path)
    d.index=pd.to_datetime(d['date'] if 'date' in d else d['ts']).dt.tz_localize(None).dt.normalize()
    d=d.sort_index().loc[:end]
    if d.index.has_duplicates:raise ValueError(f'duplicate dates: {path}')
    return d


def panel(family,end):
    base=ROOT/'data/multiasset'
    if family=='crypto':paths=[base/'crypto/yf_BTC-USD.parquet',base/'crypto/yf_ETH-USD.parquet']
    elif family=='vol':paths=[base/'vol/SVXY.parquet']
    else:paths=sorted((base/family).glob('*.parquet'))
    frames={p.stem:read(p,end) for p in paths}
    if family=='crypto':dates=pd.date_range('2014-09-17',end)
    else:dates=read(base/'etf/SPY.parquet',end).loc['2007':].index
    return {k:pd.DataFrame({s:d[k] for s,d in frames.items()}).reindex(dates).astype(float) for k in ['open','high','low','close','volume']}


def macro(dates,end):
    base=ROOT/'data/multiasset'
    def series(folder,name,col='close'):
        s=read(base/folder/(name+'.parquet'),end)[col]
        return s.reindex(s.index.union(dates)).ffill().reindex(dates).shift(1)
    vix=series('vol','VIX');vix3=series('vol','VIX3M')
    irx=series('rates','IRX');long=series('yields','US10Y','value')
    spy=series('etf','SPY');lqd=series('etf','LQD');ief=series('etf','IEF')
    return pd.DataFrame({'vix':vix/100,'vix_basis':vix/vix3-1,'yield_slope':(long-irx)/100,
                         'credit_trend':(lqd/ief).pct_change(63,fill_method=None),'market_trend':spy/spy.shift(200)-1},index=dates)


def cash_rates(dates,end):
    s=read(ROOT/'data/multiasset/rates/IRX.parquet',end)['close']/100
    previous=pd.Series(dates,index=dates).shift()
    elapsed=(pd.Series(dates,index=dates)-previous).dt.days.fillna(1)
    rate=s.reindex(s.index.union(dates)).ffill().reindex(dates).shift().fillna(0)
    return rate*elapsed/365.25


def decision_mask(dates,family):
    if family=='vol':return np.ones(len(dates),bool)
    period='W' if family=='crypto' else 'M'
    p=pd.Series(dates.to_period(period),index=dates)
    return p.ne(p.shift()).to_numpy()


def option_fields(dates,columns,end):
    fields={k:pd.DataFrame(np.nan,index=dates,columns=columns) for k in ['call_share','activity']}
    paths=sorted((ROOT/'data/lse/options_1d').glob('*.parquet'))
    cache=OUT/'option_aggregates';cache.mkdir(exist_ok=True)
    used=0
    for path in paths:
        if path.stem not in columns:continue
        sig=hashlib.sha256(path.read_bytes()).hexdigest();HASHES[str(path.relative_to(ROOT))]=sig
        saved=cache/(path.stem+'_'+sig[:12]+'_'+end+'.parquet')
        if saved.exists():agg=pd.read_parquet(saved)
        else:
            d=pd.read_parquet(path,columns=['ts','opt_type','volume','close'])
            d['date']=pd.to_datetime(d.ts).dt.tz_localize(None).dt.normalize()
            d=d[(d.date<=pd.Timestamp(end))&(d.volume>=1)&(d.close>=.1)]
            d['is_call']=d.opt_type.str.upper().str.startswith('C')
            a=d.groupby(['date','is_call']).volume.sum().unstack(fill_value=0)
            total=a.sum(axis=1)
            agg=pd.DataFrame({'call_share':a.get(True,0)/total,'activity':np.log1p(total)-np.log1p(total.rolling(63,min_periods=40).mean())})
            agg=agg.rolling(5,min_periods=3).mean().shift(1)
            agg.to_parquet(saved)
        for k in fields:fields[k][path.stem]=agg[k].reindex(dates)
        used+=1
        if used%20==0:print('Options underlying aggregates',used,flush=True)
    print('Options fields loaded',used,'underlyings',flush=True)
    return fields


def features(p,family,end,with_options=True):
    c,o,v=p['close'],p['open'],p['volume'];r=c.pct_change(fill_method=None)
    vol21=r.rolling(21).std();vol63=r.rolling(63).std()
    f={f'return_{k}':c/c.shift(k)-1 for k in [5,21,63,126,252]}
    f.update(momentum=c.shift(21)/c.shift(252)-1,vol21=vol21,vol63=vol63,
             downside=np.minimum(r,0).pow(2).rolling(63).mean().pow(.5),
             high_distance=c/c.rolling(252).max()-1,ma_distance=c/c.rolling(200).mean()-1,
             intraday=c/o-1,overnight=o/c.shift()-1,volume=v/v.rolling(63).mean())
    price_names=list(f)
    for k,s in macro(c.index,end).items():f[k]=pd.DataFrame(np.broadcast_to(s.to_numpy()[:,None],c.shape),index=c.index,columns=c.columns)
    if family=='stocks' and with_options:f.update(option_fields(c.index,c.columns,end))
    names=list(f)
    x=np.stack([f[k].to_numpy(dtype=np.float32) for k in names],axis=2)
    eligible=c.shift(252).notna() & np.isfinite(x[:,:,:len(price_names)]).all(axis=2) & c.gt(0)
    if family=='stocks':
        adv=(c*v).rolling(63).mean()
        eligible &= adv.gt(20e6)&adv.rank(axis=1,ascending=False,method='first').le(200)
    lag=2 if family=='crypto' else 1
    horizon=30 if family=='crypto' else 21
    y=o.shift(-(lag+horizon))/o.shift(-lag)-1
    return x,y,eligible,f,len(price_names),lag+horizon


def predict(x,y,eligible,dates,family,models,price_count,label_lag,end):
    y=y.to_numpy(dtype=np.float32);e=eligible.to_numpy();idx=np.arange(len(dates))
    week=pd.Series(dates.to_period('W')).ne(pd.Series(dates.to_period('W')).shift()).to_numpy()
    decisions=decision_mask(dates,family)
    outputs={name:np.full(y.shape,np.nan,dtype=np.float32) for name in models};audit=[]
    for year in range(2019,pd.Timestamp(end).year+1):
        cutoff=dates.searchsorted(pd.Timestamp(f'{year}-01-01'))
        train_date=(dates>='2008-01-01')&week&(idx+label_lag<cutoff)
        pred_date=(dates.year==year)&decisions
        train=train_date[:,None]&e&np.isfinite(y)
        test=pred_date[:,None]&e
        if train.sum()<100 or not test.any():continue
        last=int(np.where(train.any(axis=1))[0][-1]);first=int(np.where(test.any(axis=1))[0][0])
        assert dates[last+label_lag]<dates[first]
        for name in models:
            count=price_count if name.endswith('_price') else x.shape[2]
            tx=x[:,:,:count][train];vx=x[:,:,:count][test]
            tx=np.concatenate([np.nan_to_num(tx,nan=0,posinf=0,neginf=0),~np.isfinite(tx)],axis=1)
            vx=np.concatenate([np.nan_to_num(vx,nan=0,posinf=0,neginf=0),~np.isfinite(vx)],axis=1)
            model=make_pipeline(StandardScaler(),Ridge(alpha=100)) if name.startswith('ridge') else HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=7,learning_rate=.05,min_samples_leaf=100,l2_regularization=10,early_stopping=False,random_state=20260919)
            model.fit(tx,np.clip(y[train],-.5,.5));outputs[name][test]=model.predict(vx)
            print(f'{family} {name} {year}: {train.sum():,} train / {test.sum():,} predicted',flush=True)
        audit.append({'year':year,'train_rows':int(train.sum()),'last_label':str(dates[last+label_lag].date()),'first_prediction':str(dates[first].date())})
    return {name:pd.DataFrame(a,index=dates,columns=eligible.columns) for name,a in outputs.items()},audit


def targets(p,family,scores):
    c=p['close'];dates=c.index;mask=decision_mask(dates,family)
    slots=20 if family=='stocks' else 4 if family=='etf' else len(c.columns)
    out={}
    for name,score in scores.items():
        t=pd.DataFrame(np.nan,index=dates,columns=c.columns)
        for date in dates[mask]:
            s=score.loc[date].replace([np.inf,-np.inf],np.nan).dropna();s=s[s>0].nlargest(slots)
            t.loc[date]=0
            if len(s):t.loc[date,s.index]=1/slots
        out[name]=t
    return out


def signals(p,family,end,names):
    c=p['close']
    if family=='vol':
        m=macro(c.index,end)
        gate=m.vix_basis.lt(0)&m.vix.notna()
        return {n:pd.DataFrame((gate & (m.market_trend.gt(0) if n=='contango_trend' else True)).astype(float).to_numpy(),index=c.index,columns=c.columns) for n in names},[]
    x,y,e,f,count,lag=features(p,family,end,with_options=any(n.endswith('enriched') for n in names))
    model_names=[n for n in names if n in ML]
    pred,audit=predict(x,y,e,c.index,family,model_names,count,lag,end) if model_names else ({},[])
    mom=(f['return_63']+f['return_126']+f['return_252'])/3
    rules={'momentum':f['momentum'],'trend':mom/f['vol63'],
           'breakout':(1+f['high_distance']).where(f['high_distance']>-.1).where(f['ma_distance']>0)}
    scores={name:(pred[name] if name in pred else rules[name]).where(e) for name in names}
    return targets(p,family,scores),audit


def execute(p,t,rf,family,stress=False,start=START):
    c,o=p['close'],p['open'];dates=c.index
    arr_o,arr_c,arr_t=o.to_numpy(),c.to_numpy(),t.to_numpy()
    lag=2 if family=='crypto' else 1
    cost=({'stocks':15,'etf':15,'crypto':50,'vol':30} if stress else {'stocks':5,'etf':5,'crypto':20,'vol':10})[family]/10000
    cash=prior=1.;shares=np.zeros(c.shape[1]);rows=[];begun=False
    for i,date in enumerate(dates):
        if date<pd.Timestamp(start):continue
        cash*=1+rf.iloc[i]
        op,cp=arr_o[i],arr_c[i];held=shares!=0
        if np.any(held&(~np.isfinite(op)|~np.isfinite(cp)|(op<=0)|(cp<=0))):raise ValueError(f'missing held mark {family} {date}')
        old=shares*np.nan_to_num(op);nav_open=cash+old.sum();w=arr_t[i-lag] if i>=lag else np.full(c.shape[1],np.nan)
        # Starting a new independently funded test: use the latest executable target.
        if not begun:
            for j in range(i-lag,-1,-1):
                if np.isfinite(arr_t[j]).all():w=arr_t[j];break
            begun=True
        fee=turnover=0.
        if np.isfinite(w).all():
            if (w<0).any() or w.sum()>1+1e-8:raise ValueError('long-only allocation exceeded')
            if np.any((w>0)&(~np.isfinite(op)|(op<=0))):raise ValueError('missing entry quote')
            new_nav=nav_open
            for _ in range(15):
                desired=w*new_nav;fee=np.abs(desired-old).sum()*cost;new_nav=nav_open-fee
            turnover=np.abs(desired-old).sum()/nav_open
            cash-=(desired-old).sum()+fee
            shares=np.divide(desired,op,out=np.zeros_like(desired),where=np.isfinite(op)&(op>0))
        marked=shares*np.nan_to_num(cp);nav=cash+marked.sum()
        if nav<=0 or cash < -1e-8:raise ValueError('insolvency or unintended leverage')
        rows.append((date,nav/prior-1,nav,fee/nav_open,turnover,marked.sum()/nav));prior=nav
    result=pd.DataFrame(rows,columns=['date','return','nav','cost','turnover','gross']).set_index('date')
    liquidation=np.abs(marked).sum()*cost
    prev=result.nav.iloc[-2] if len(result)>1 else 1
    result.iloc[-1,result.columns.get_loc('nav')]-=liquidation
    result.iloc[-1,result.columns.get_loc('return')]=result.nav.iloc[-1]/prev-1
    result.iloc[-1,result.columns.get_loc('cost')]+=liquidation/prev
    result.iloc[-1,result.columns.get_loc('turnover')]+=np.abs(marked).sum()/prev
    return result


def stats(f,rf,ann):
    r=f['return'];ex=r-rf.reindex(r.index);wealth=(1+r).cumprod();years=len(r)/ann
    peak=np.maximum.accumulate(np.r_[1.,wealth.to_numpy()])[1:]
    return {'cagr':float(wealth.iloc[-1]**(1/years)-1),'total_return':float(wealth.iloc[-1]-1),
            'excess_sharpe':float(ex.mean()/ex.std()*np.sqrt(ann)) if ex.std()>1e-12 else None,
            'ann_excess_mean':float(ex.mean()*ann),'vol':float(r.std()*np.sqrt(ann)),
            'max_dd':float(np.min(wealth.to_numpy()/peak-1)),
            'annual_cost':float(f.cost.mean()*ann),'annual_turnover':float(f.turnover.mean()*ann),
            'average_exposure':float(f.gross.mean()),'days':len(f),'years':years}


def run_family(family,end,names,start,folder):
    p=panel(family,end);rf=cash_rates(p['close'].index,end);ann=365 if family=='crypto' else 252
    all_t,audit=signals(p,family,end,[n for n in names if n!='passive'])
    if 'passive' in names:
        t=pd.DataFrame(np.nan,index=p['close'].index,columns=p['close'].columns)
        for d in t.index[decision_mask(t.index,family)]:
            valid=p['close'].loc[d].notna()&p['close'].shift(252).loc[d].notna()
            t.loc[d]=valid.astype(float)/max(1,valid.sum())
        all_t['passive']=t
    (folder/f'{family}_training.json').write_text(json.dumps(audit,indent=2))
    result={}
    for name,t in all_t.items():
        key=family+'__'+name;result[key]={};t.to_parquet(folder/f'{key}_targets.parquet')
        for label,stress in [('base',False),('stress',True)]:
            f=execute(p,t,rf,family,stress=stress,start=start)
            f.to_csv(folder/f'{key}_{label}.csv');result[key][label]=stats(f,rf,ann)
            if label=='base':result[key]['yearly']={str(y):stats(g,rf,ann) for y,g in f.groupby(f.index.year)}
        print('RESULT',key,json.dumps(result[key]['base']),flush=True)
    return result


def eligible(row):
    b=row['base'];s=row['stress']
    positives=sum(row['yearly'].get(str(y),{}).get('total_return',-1)>0 for y in range(2019,2025))
    return b['vol']<=.4 and b['max_dd']>=-.5 and s['ann_excess_mean']>0 and positives>=4


def sign_selection(result):
    winners={}
    for family in CANDIDATES:
        candidates=[k for k,v in result.items() if k.startswith(family+'__') and not k.endswith('__passive') and eligible(v)]
        winners[family]=max(candidates,key=lambda k:result[k]['base']['cagr']) if candidates else None
    qualified=[k for family,k in winners.items() if family!='stocks' and k]
    primary=max(qualified,key=lambda k:result[k]['base']['cagr']) if qualified else None
    selection={'family_winners':winners,'primary':primary,'fixed_equal_weight_blend':qualified,
               'stock_survivorship_exclusion':True,'plan_sha256':hashlib.sha256((ROOT/'research/return_search/PLAN.md').read_bytes()).hexdigest(),
               'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'results_sha256':hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()}
    return selection


def blend(selection,folder,end):
    keys=selection['fixed_equal_weight_blend']
    if not keys:return {}
    dates=pd.date_range('2025-07-01',end);rf=cash_rates(dates,end);result={}
    for scenario in ['base','stress']:
        nav=[];cost=[];turn=[];gross=[]
        for k in keys:
            d=pd.read_csv(folder/f'{k}_{scenario}.csv',index_col=0,parse_dates=True)
            nav.append((1+d['return']).cumprod().reindex(dates).ffill().fillna(1))
            cost.append(d.cost.reindex(dates).fillna(0));turn.append(d.turnover.reindex(dates).fillna(0));gross.append(d.gross.reindex(dates).ffill().fillna(0))
        # Fixed initial allocations with no rebalancing among independent sleeves.
        wealth=pd.concat(nav,axis=1).mean(axis=1);r=wealth/wealth.shift(fill_value=1)-1
        f=pd.DataFrame({'return':r,'nav':wealth,'cost':pd.concat(cost,axis=1).mean(axis=1),'turnover':pd.concat(turn,axis=1).mean(axis=1),'gross':pd.concat(gross,axis=1).mean(axis=1)})
        f.to_csv(folder/f'fixed_blend_{scenario}.csv');result[scenario]=stats(f,rf,365)
    return result


def main():
    mode=argparse.ArgumentParser();mode.add_argument('phase',choices=['dev','evaluation']);phase=mode.parse_args().phase
    planhash=hashlib.sha256((ROOT/'research/return_search/PLAN.md').read_bytes()).hexdigest()
    assert (OUT/'registration.sha256').read_text().split()[0]==planhash
    folder=OUT/phase;folder.mkdir(exist_ok=True)
    if phase=='dev':
        result={}
        for family,names in CANDIDATES.items():
            result.update(run_family(family,END_DEV,names+['passive'],START,folder))
            (folder/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
        selection=sign_selection(result)
        (OUT/'selection.json').write_text(json.dumps(selection,indent=2))
        print('FROZEN SELECTION',json.dumps(selection),flush=True)
    else:
        if (folder/'results.json').exists():raise RuntimeError('evaluation already completed; refusing another look')
        selection=json.loads((OUT/'selection.json').read_text())
        assert selection['code_sha256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        assert selection['plan_sha256']==planhash
        result={}
        for family,key in selection['family_winners'].items():
            names=([key.split('__',1)[1]] if key else [])+['passive']
            result.update(run_family(family,END_TEST,names,'2025-07-01',folder))
        result['fixed_blend']=blend(selection,folder,END_TEST)
        (folder/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    (folder/'input_hashes.json').write_text(json.dumps(HASHES,indent=2))

if __name__=='__main__':main()
