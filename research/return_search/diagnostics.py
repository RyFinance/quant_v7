import json
from pathlib import Path
import numpy as np
import pandas as pd
from research.return_search.run import OUT,END_TEST,panel,signals,execute,stats,cash_rates


def uncertainty(a,b,rf,draws=4000):
    a,b,rf=a.align(b,join='inner')[0],b.reindex(a.index),rf.reindex(a.index)
    e=(a-rf).to_numpy();diff=(a-b).to_numpy();beta=np.cov(e,(b-rf).to_numpy())[0,1]/np.var((b-rf).to_numpy(),ddof=1)
    residual=e-beta*(b-rf).to_numpy();n=len(e);rng=np.random.default_rng(20260919);sharpes=[];means=[];alphas=[];null=[]
    for _ in range(draws):
        ix=((rng.integers(n,size=int(np.ceil(n/20)))[:,None]+np.arange(20))%n).ravel()[:n]
        sharpes.append(e[ix].mean()/e[ix].std(ddof=1)*np.sqrt(252));means.append(diff[ix].mean()*252);alphas.append(residual[ix].mean()*252);null.append((diff[ix]-diff.mean()).mean()>=diff.mean())
    return {'excess_sharpe_ci95':np.quantile(sharpes,[.025,.975]).tolist(),'annual_active_mean':float(diff.mean()*252),'annual_active_mean_ci95':np.quantile(means,[.025,.975]).tolist(),'one_sided_active_mean_p':float((1+sum(null))/(draws+1)), 'beta':float(beta),'annual_alpha':float(residual.mean()*252),'annual_alpha_ci95':np.quantile(alphas,[.025,.975]).tolist(),'caveat':'20-session circular bootstrap; no correction for project-wide repeated strategy research; beta held fixed within bootstrap'}


def main():
    folder=OUT/'diagnostics';folder.mkdir(exist_ok=True);result={}
    ep=panel('etf',END_TEST);rf=cash_rates(ep['close'].index,END_TEST)
    benchmarks={}
    for name in ['SPY','QQQ']:
        p={field:frame[[name]] for field,frame in ep.items()}
        t=p['close']*0+1
        # Passive buy once, not daily rebalanced.
        t.iloc[1:]=np.nan
        f=execute(p,t,rf,'etf',start='2025-07-01');f.to_csv(folder/f'{name}_passive.csv')
        benchmarks[name]=f;result[name]=stats(f,rf,252)
    for family in ['stocks','etf']:
        p=panel(family,END_TEST);rf=cash_rates(p['close'].index,END_TEST)
        t=signals(p,family,END_TEST,['momentum'])[0]['momentum'];key=family+'__momentum';row={}
        for scenario,stress in [('base',False),('stress',True)]:
            f=execute(p,t,rf,family,stress=stress,start='2019-01-01')
            f.to_csv(folder/f'{key}_continuous_{scenario}.csv');row['continuous_'+scenario]=stats(f,rf,252)
            if not stress:row['continuous_yearly']={str(y):stats(g,rf,252) for y,g in f.groupby(f.index.year)}
            d=execute(p,t.shift(1),rf,family,stress=stress,start='2025-07-01')
            d.to_csv(folder/f'{key}_delay_{scenario}.csv');row['extra_day_delay_'+scenario]=stats(d,rf,252)
        old={k:v.loc[:'2018-12-31'] for k,v in p.items()}
        f=execute(old,t.loc[:'2018-12-31'],rf,family,start='2008-01-01');row['earlier_history']=stats(f,rf,252)
        f.to_csv(folder/f'{key}_earlier_history.csv')
        recent=t.ffill().loc['2025-07-01':];top=recent.mean().nlargest(3)
        row['largest_average_targets']={k:float(v) for k,v in top.items()};row['omit_asset_leave_cash']={}
        for symbol in top.index:
            modified=t.copy();modified.loc[modified[symbol].notna(),symbol]=0
            f=execute(p,modified,rf,family,start='2025-07-01')
            row['omit_asset_leave_cash'][symbol]=stats(f,rf,252)
        base=pd.read_csv(OUT/f'evaluation/{key}_base.csv',index_col=0,parse_dates=True)
        row['benchmarks']={name:uncertainty(base['return'],f['return'],rf) for name,f in benchmarks.items()}
        latest=t.dropna().iloc[-1];row['latest_target_date']=str(t.dropna().index[-1].date());row['latest_research_targets']={k:float(v) for k,v in latest.items() if v>0}
        result[key]=row
        print(key,json.dumps({k:v for k,v in row.items() if k not in ['continuous_yearly','benchmarks']}),flush=True)
    (folder/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    # Reconstruct original stock statistics using the full-calendar lagged RF.
    path=OUT/'evaluation/results.json';full=json.loads(path.read_text())
    for scenario in ['base','stress']:
        f=pd.read_csv(OUT/f'evaluation/stocks__momentum_{scenario}.csv',index_col=0,parse_dates=True)
        full['stocks__momentum'][scenario]=stats(f,rf,252)
        if scenario=='base':full['stocks__momentum']['yearly']={str(y):stats(g,rf,252) for y,g in f.groupby(f.index.year)}
    path.write_text(json.dumps(full,indent=2,allow_nan=False))

if __name__=='__main__':main()
