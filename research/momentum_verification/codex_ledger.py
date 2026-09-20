"""Independent pandas-ledger reconciliation on adjusted units, plus fixed order fees."""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from research.return_search.run import panel,cash_rates,stats
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'reports/momentum_verification_20260919/codex_v1'


def ledger(opens,closes,targets,rates,start,capital=100000.,slip=.0005,order_fee=0.):
    units=pd.Series(0.,index=closes.columns);cash=capital;last_nav=capital;rows=[];fills=[];contributions=pd.Series(0.,index=closes.columns);previous_marks=closes.iloc[0]*0;initialized=False
    for i,date in enumerate(closes.index):
        if date<pd.Timestamp(start):continue
        interest=cash*rates.loc[date];cash+=interest
        op,cp=opens.loc[date],closes.loc[date];held=units.ne(0)
        if (op[held].isna()|cp[held].isna()).any():raise ValueError('missing held price')
        overnight=units*(op-previous_marks).fillna(0)
        nav_open=cash+units.mul(op).fillna(0).sum()
        candidate=targets.iloc[i-1] if i else units*float('nan')
        if not initialized:
            earlier=targets.iloc[:i].dropna()
            if len(earlier):candidate=earlier.iloc[-1]
            initialized=True
        old=units.copy();cost=0.;turn=0.
        if candidate.notna().all():
            if (candidate<0).any() or candidate.sum()>1+1e-10:raise ValueError('invalid target')
            old_dollars=old.mul(op).fillna(0);low,high=0.,nav_open
            for _ in range(60):
                guess=(low+high)/2;dollar_change=candidate*guess-old_dollars
                cost=dollar_change.abs().sum()*slip+(dollar_change.abs()>1e-7).sum()*order_fee
                if guess+cost>nav_open:high=guess
                else:low=guess
            desired=candidate*((low+high)/2);delta=desired-old_dollars
            cost=delta.abs().sum()*slip+(delta.abs()>1e-7).sum()*order_fee
            cash-=delta.sum()+cost;units=desired.div(op).fillna(0);turn=delta.abs().sum()/nav_open
            for symbol in delta.index[delta.abs()>1e-7]:
                fills.append({'date':str(date.date()),'symbol':symbol,'adjusted_units_delta':float(units[symbol]-old[symbol]),'adjusted_open':float(op[symbol]),'notional':float(delta[symbol]),'cost':float(abs(delta[symbol])*slip+order_fee)})
        intraday=units.mul(cp-op).fillna(0);contributions+=overnight.fillna(0)+intraday
        nav=cash+units.mul(cp).fillna(0).sum()
        if cash < -1e-6:raise ValueError('negative cash')
        rows.append({'date':date,'return':nav/last_nav-1,'nav':nav/capital,'cost':cost/nav_open,'turnover':turn,'gross':units.mul(cp).fillna(0).sum()/nav,'cash_dollars':cash,'interest_dollars':interest,'cost_dollars':cost})
        last_nav=nav;previous_marks=cp
    f=pd.DataFrame(rows).set_index('date')
    liquidation=units.mul(previous_marks).abs().fillna(0).sum()*slip+units.ne(0).sum()*order_fee
    prior=f.nav.iloc[-2] if len(f)>1 else 1
    f.iloc[-1,f.columns.get_loc('nav')]-=liquidation/capital
    f.iloc[-1,f.columns.get_loc('return')]=f.nav.iloc[-1]/prior-1
    f.iloc[-1,f.columns.get_loc('cost')]+=liquidation/capital/prior
    f.iloc[-1,f.columns.get_loc('cost_dollars')]+=liquidation
    reconciliation=contributions.sum()+f.interest_dollars.sum()-f.cost_dollars.sum()-capital*(f.nav.iloc[-1]-1)
    return f,pd.DataFrame(fills),contributions,float(reconciliation)


def main():
    p=panel('stocks','2026-09-17');t=pd.read_parquet(ROOT/'reports/return_search_20260919/evaluation/stocks__momentum_targets.parquet');rf=cash_rates(p['close'].index,'2026-09-17');result={}
    for label,fee in [('matching_fractional',0.),('one_dollar_per_order',1.)]:
        f,fills,contrib,error=ledger(p['open'],p['close'],t,rf,'2025-07-01',order_fee=fee)
        f.to_csv(OUT/f'independent_{label}.csv');fills.to_csv(OUT/f'fills_{label}.csv',index=False);contrib.sort_values(ascending=False).to_csv(OUT/f'contributions_{label}.csv')
        result[label]={'metrics':stats(f,rf,252),'fills':len(fills),'total_dollar_cost':float(f.cost_dollars.sum()),'pnl_reconciliation_dollars':error,'top_contributions_dollars':contrib.nlargest(10).to_dict(),'bottom_contributions_dollars':contrib.nsmallest(5).to_dict()}
        if fee==0:
            original=pd.read_csv(ROOT/'reports/return_search_20260919/evaluation/stocks__momentum_base.csv',index_col=0,parse_dates=True)
            result[label]['max_nav_difference']=float((f.nav-original.nav).abs().max());assert result[label]['max_nav_difference']<1e-10
        assert abs(error)<1e-6
    latest=t.dropna().iloc[-1];latest=latest[latest>0];prices=p['close'].iloc[-1][latest.index]
    units=np.floor(100000*latest/prices);notional=units*prices
    preview=pd.DataFrame({'weight':latest,'reference_close':prices,'whole_shares':units.astype(int),'notional':notional});preview.to_csv(OUT/'latest_whole_share_feasibility.csv')
    result['whole_share_snapshot']={'reference_date':str(p['close'].index[-1].date()),'signal_date':str(t.dropna().index[-1].date()),'capital':100000,'uninvested_before_costs':float(100000-notional.sum()),'assumed_cost':float(notional.sum()*.0005+len(notional)), 'status':'feasibility only; historical adjusted units are not nominal shares; no orders'}
    (OUT/'independent_ledger_results.json').write_text(json.dumps(result,indent=2,allow_nan=False));print(json.dumps(result,indent=2),flush=True)
if __name__=='__main__':main()
