import json
from pathlib import Path
from data.lse_vault import Vault
from research.lse_mcp_client import Terminal,content_text
OUT=Path('reports/momentum_verification_20260919');records=[]
with Terminal() as t:
 r=t.call('terminal_status');(OUT/'terminal_status.json').write_text(json.dumps(r,indent=2));print('LSE terminal connection checked',flush=True)
v=Vault()
for symbol in ['SIVB','ATVI','ANSS','TWTR']:
 try:
  d=v.candles(symbol,'1d',start='2019-01-01',end='2026-09-17',dataset='stocks')
  r={'symbol':symbol,'rows':len(d)}
  if len(d):
   d.to_parquet(OUT/'inputs'/f'{symbol}_vault.parquet');r.update(first=str(d.ts.min()),last=str(d.ts.max()))
 except Exception as exc:r={'symbol':symbol,'error':str(exc)}
 records.append(r);print(r,flush=True)
(OUT/'removed_data_probes.json').write_text(json.dumps(records,indent=2))
