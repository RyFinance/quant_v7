"""Matched execution-cost benchmarks and attribution, isolated verification outputs."""
import io,json,zipfile
import numpy as np
import pandas as pd
import statsmodels.api as sm
from research.return_search.run import panel,cash_rates,execute,stats
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];BASE=ROOT/'reports/momentum_verification_20260919';OUT=BASE/'codex_v1';IN=BASE/'inputs'


def french(path,names):
 with zipfile.ZipFile(path) as z:text=z.read(z.namelist()[0]).decode('latin1')
 rows=[r for r in text.splitlines() if len(r.split(',')[0].strip())==8 and r.split(',')[0].strip().isdigit()]
 f=pd.read_csv(io.StringIO('\n'.join(rows)),header=None,names=['date']+names);f.index=pd.to_datetime(f.pop('date').astype(str),format='%Y%m%d');return f/100


def attribution(r,factors,columns):
 joined=pd.concat([r.rename('portfolio'),factors],axis=1).dropna();y=joined.portfolio-joined.RF;x=sm.add_constant(joined[columns]);fit=sm.OLS(y,x).fit(cov_type='HAC',cov_kwds={'maxlags':21})
 return {'start':str(joined.index.min().date()),'end':str(joined.index.max().date()),'observations':len(joined),'alpha_annual_arithmetic':float(fit.params['const']*252),'alpha_t_hac':float(fit.tvalues['const']),'alpha_ci95':(fit.conf_int().loc['const']*252).tolist(),'r_squared':float(fit.rsquared),'loadings':{k:float(v) for k,v in fit.params.items() if k!='const'},'note':'HAC with 21 lags; no correction for project-wide repeated research or survivorship'}


def main():
 factors=french(IN/'F-F_Research_Data_5_Factors_2x3_daily_CSV.zip',['Mkt-RF','SMB','HML','RMW','CMA','RF']).join(french(IN/'F-F_Momentum_Factor_daily_CSV.zip',['Mom']))
 stock=panel('stocks','2026-09-17');dates=stock['close'].index;rf=cash_rates(dates,'2026-09-17')
 original_t=pd.read_parquet(ROOT/'reports/return_search_20260919/evaluation/stocks__momentum_targets.parquet');filtered_t=pd.read_parquet(BASE/'membership_filtered_targets.parquet')
 result={};windows={'selection':('2019-01-01','2025-06-30'),'later':('2025-07-01','2026-09-17'),'continuous':('2019-01-01','2026-09-17')}
 for period,(start,end) in windows.items():
  rows={};paths={}
  for name,t in [('original',original_t),('membership_filtered',filtered_t)]:
   f=execute({k:v.loc[:end] for k,v in stock.items()},t.loc[:end],rf,'stocks',start=start);paths[name]=f
   rows[name]={'metrics':stats(f,rf,252),'six_factor':attribution(f['return'],factors,['Mkt-RF','SMB','HML','RMW','CMA','Mom'])}
  for symbol in ['SPMO','MTUM']:
   d=pd.read_parquet(IN/(symbol+'.parquet'));d.index=d.index.tz_localize(None).normalize()
   p={field:pd.DataFrame({symbol:d[field.capitalize()]}).reindex(dates).loc[d.index.min():end] for field in ['open','close']}
   t=p['close']*0+1;t.iloc[1:]=np.nan;f=execute(p,t,rf,'etf',start=start);f.to_csv(OUT/f'{symbol}_{period}.csv');rows[symbol]={'metrics':stats(f,rf,252)}
   for name,custom in paths.items():
    active=custom['return']-f['return'];fit=sm.OLS(active,np.ones((len(active),1))).fit(cov_type='HAC',cov_kwds={'maxlags':21})
    rows[name][f'vs_{symbol}']={'annual_active_arithmetic':float(active.mean()*252),'active_t_hac':float(fit.tvalues.iloc[0]),'active_ci95':(fit.conf_int().iloc[0]*252).tolist()}
  result[period]=rows
  print(period, {k:{'cagr':v['metrics']['cagr'],'sharpe':v['metrics']['excess_sharpe']} for k,v in rows.items()},flush=True)
 (OUT/'benchmark_results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
if __name__=='__main__':main()
