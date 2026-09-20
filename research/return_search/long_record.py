"""Descriptive full-record extension; never used to tune the selected rules."""
import json
import pandas as pd
from research.return_search.run import OUT,END_TEST,panel,cash_rates,execute,stats

folder=OUT/'diagnostics';result={}
for family in ['stocks','etf']:
 p=panel(family,END_TEST);rf=cash_rates(p['close'].index,END_TEST)
 key=family+'__momentum';t=pd.read_parquet(OUT/f'evaluation/{key}_targets.parquet')
 result[key]={}
 for label,stress in [('base',False),('stress',True)]:
  f=execute(p,t,rf,family,stress=stress,start='2008-01-01')
  f.to_csv(folder/f'{key}_2008_{label}.csv');result[key][label]=stats(f,rf,252)
  if label=='base':result[key]['yearly']={str(y):stats(g,rf,252) for y,g in f.groupby(f.index.year)}
for symbol in ['SPY','QQQ']:
 p0=panel('etf',END_TEST);p={k:v[[symbol]] for k,v in p0.items()};rf=cash_rates(p['close'].index,END_TEST)
 t=p['close']*0+1;t.iloc[1:]=float('nan');f=execute(p,t,rf,'etf',start='2008-01-01')
 f.to_csv(folder/f'{symbol}_2008.csv');result[symbol]=stats(f,rf,252)
(folder/'long_record.json').write_text(json.dumps(result,indent=2,allow_nan=False))
for k,v in result.items():print(k,v.get('base',v),flush=True)
