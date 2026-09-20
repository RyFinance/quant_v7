#!/bin/zsh
# Download Open Source Asset Pricing (release 2025-10) files into data/osap and extract LS series.
# Google Drive ids come from openassetpricing.OpenAP().name_id_map (release202510).
set -e
cd "$(dirname $0)/../../data" && mkdir -p osap && cd osap
dl() { curl -sL "https://drive.usercontent.google.com/download?id=$1&export=download&confirm=t" -o "$2"; }
dl 1rdi0jTPSA6xtn6TpQAMT5WyEczQ1gK59 SignalDoc.csv
dl 1g7w-yQ6Cg2qbMEkER9Q3vgns4JszXQo6 PredictorPortsFull.csv
dl 1Q4YatQ3soRU_V7VeACwUn2bnCnmhDUI2 LiqScreen_ME_gt_NYSE20pct.zip
dl 1menxh3LzP5Fh2e21201HDAOUUNz475MD LiqScreen_NYSEonly.zip
dl 1ef905SSlCDyh1KU9W1tJs5sfBFz0HPUt QuintilesVW.zip
dl 1n76lfnpblK4jH6SObZew_o7Qi1D3CXWz QuintilesEW.zip
cd ../.. && .venv/bin/python - <<'PY'
import pandas as pd, zipfile
D='data/osap/'
def ls(src, out, z=True):
    f = zipfile.ZipFile(D+src).open(zipfile.ZipFile(D+src).namelist()[0]) if z else D+src
    parts=[ch[ch.port=='LS'] for ch in pd.read_csv(f, chunksize=500000, dtype={'port':str},
           usecols=['signalname','port','date','ret','Nlong','Nshort'])]
    d=pd.concat(parts); d['date']=pd.to_datetime(d.date); d.to_parquet(D+out)
ls('PredictorPortsFull.csv','ls_op.parquet',False); ls('QuintilesVW.zip','ls_q5_vw.parquet')
ls('QuintilesEW.zip','ls_q5_ew.parquet'); ls('LiqScreen_ME_gt_NYSE20pct.zip','ls_me_gt_nyse20.parquet')
ls('LiqScreen_NYSEonly.zip','ls_nyse_only.parquet')
PY
