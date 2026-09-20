import io,json,hashlib,urllib.request
from pathlib import Path
import pandas as pd
import yfinance as yf
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/momentum_verification_20260919/inputs'

def get(url,path):
 if path.exists():return path.read_bytes()
 request=urllib.request.Request(url,headers={'User-Agent':'quant-v7-research/1.0'})
 with urllib.request.urlopen(request,timeout=45) as response:body=response.read()
 path.write_bytes(body);return body

def main():
 manifest=[]
 for label,url in [('constituents','https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'),('changes','https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500')]:
  try:
   raw=get(url,OUT/f'{label}.html');tables=pd.read_html(io.BytesIO(raw))
   for i,t in enumerate(tables):
    if (label=='constituents' and 'Symbol' in t.columns) or (label=='changes' and any('Added' in str(c) for c in t.columns)):
     t.to_pickle(OUT/f'{label}.pkl');print(label,t.shape,str(t.columns),t.head(2).to_string(),flush=True);break
   manifest.append({'source':url,'sha256':hashlib.sha256(raw).hexdigest(),'saved':label+'.html'})
  except Exception as exc:print('SOURCE ERROR',label,type(exc).__name__,str(exc),flush=True)
 for name in ['F-F_Research_Data_5_Factors_2x3_daily_CSV.zip','F-F_Momentum_Factor_daily_CSV.zip']:
  url='https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/'+name
  try:
   raw=get(url,OUT/name);manifest.append({'source':url,'sha256':hashlib.sha256(raw).hexdigest(),'saved':name});print(name,len(raw),flush=True)
  except Exception as exc:print('SOURCE ERROR',name,str(exc),flush=True)
 for symbol in ['SPMO','MTUM']:
  try:
   p=OUT/(symbol+'.parquet')
   if p.exists():d=pd.read_parquet(p)
   else:
    d=yf.Ticker(symbol).history(start='2007-01-01',end='2026-09-18',auto_adjust=True);d.to_parquet(p)
   print(symbol,len(d),str(d.index.min()),str(d.index.max()),flush=True)
   manifest.append({'source':'Yahoo adjusted official-session history','symbol':symbol,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
  except Exception as exc:print('SOURCE ERROR',symbol,str(exc),flush=True)
 (OUT/'source_manifest.json').write_text(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
