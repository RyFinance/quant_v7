"""Resume frozen evaluation per candidate, preserving completed output and explicit data failures."""
import hashlib,json
import pandas as pd
from research.return_search.run import OUT,ROOT,END_TEST,run_family,HASHES,panel,cash_rates,stats,blend

s=json.loads((OUT/'selection.json').read_text())
assert hashlib.sha256((ROOT/'research/return_search/run.py').read_bytes()).hexdigest()==s['code_sha256']
f=OUT/'evaluation'
if (f/'results.json').exists():raise RuntimeError('evaluation completed already')
result={};errors={}
for family,key in s['family_winners'].items():
 for name in ([key.split('__',1)[1]] if key else [])+['passive']:
  k=family+'__'+name
  if all((f/f'{k}_{scenario}.csv').exists() for scenario in ['base','stress']):
   result[k]={}
   for scenario in ['base','stress']:
    daily=pd.read_csv(f/f'{k}_{scenario}.csv',index_col=0,parse_dates=True)
    rf=cash_rates(daily.index,END_TEST);ann=365 if family=='crypto' else 252
    result[k][scenario]=stats(daily,rf,ann)
    if scenario=='base':result[k]['yearly']={str(y):stats(g,rf,ann) for y,g in daily.groupby(daily.index.year)}
  else:
   try:result.update(run_family(family,END_TEST,[name],'2025-07-01',f))
   except ValueError as exc:
    errors[k]=str(exc);print('DATA FAILURE',k,str(exc),flush=True)
  (f/'partial_results.json').write_text(json.dumps(result,indent=2))
result['fixed_blend']=blend(s,f,END_TEST)
result['data_errors']=errors
(f/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
(f/'input_hashes_resume.json').write_text(json.dumps(HASHES,indent=2))
print('COMPLETED',json.dumps(result),flush=True)
