"""Small independent regular-session return check from LSE intraday bars."""
import json
from pathlib import Path
import pandas as pd
from data.lse_vault import Vault
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'reports/momentum_verification_20260919/codex_v1';cache=OUT/'quotes';cache.mkdir(exist_ok=True)
v=Vault();rows=[]
for symbol in ['STX','GEV','GLW']:
    p=pd.read_parquet(ROOT/f'data/multiasset/stocks/{symbol}.parquet').set_index('date')
    for date in ['2025-07-02','2025-10-02','2026-01-05','2026-04-02','2026-07-02','2026-09-02']:
        start=pd.Timestamp(date+' 09:30',tz='America/New_York').tz_convert('UTC');end=pd.Timestamp(date+' 16:00',tz='America/New_York').tz_convert('UTC')
        path=cache/f'{symbol}_{date}.parquet'
        try:
            if path.exists():d=pd.read_parquet(path)
            else:
                d=v.candles(symbol,'30m',start=start.strftime('%Y-%m-%dT%H:%M:%S'),end=end.strftime('%Y-%m-%dT%H:%M:%S'),dataset='stocks');d.to_parquet(path)
            d['utc']=pd.to_datetime(d.ts,utc=True);d=d[(d.utc>=start)&(d.utc<end)].sort_values('utc')
            if len(d)!=13:raise ValueError(f'expected 13 regular-session bars, found {len(d)}')
            vr=float(d.close.iloc[-1]/d.open.iloc[0]-1);yr=float(p.loc[date,'close']/p.loc[date,'open']-1)
            row={'symbol':symbol,'date':date,'vault_intraday_return':vr,'cached_intraday_return':yr,'difference_bps':(vr-yr)*10000,'bars':len(d)}
        except Exception as e:row={'symbol':symbol,'date':date,'error':str(e)}
        rows.append(row);print(row,flush=True)
(OUT/'independent_quote_checks.json').write_text(json.dumps(rows,indent=2))
