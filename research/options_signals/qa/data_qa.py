"""Options-signal QA (reports/options_signals/QA.md). Reads local files only; never calls the vault.
Run: PYTHONPATH=. .venv/bin/python research/options_signals/qa/data_qa.py OUTDIR
Data QA on option files on disk. Levels/counts only; no returns."""
import json, sys, time
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path("/Users/rytty/CCP/quant_v7")
OPT = ROOT / "data/lse/options_1d"
RAW = ROOT / "data/stocks_raw_2014"
OUT = Path(sys.argv[1])
names = json.loads((OPT / "universe.json").read_text())["names"]
on_disk = [t for t in names if (OPT / f"{t}.parquet").exists()]

rows = {}
for t in on_disk:
    t0 = time.time()
    o = pd.read_parquet(OPT / f"{t}.parquet", columns=["ts", "expiry", "opt_type", "strike", "osi", "close", "volume"])
    o["date"] = o["ts"].dt.tz_convert(None).dt.normalize()
    o["year"] = o["date"].dt.year
    root = o["osi"].str.slice(2, -15)
    n_badroot = int((root != t.replace("-", ".")).sum())
    n_dup = int(o.duplicated(["date", "expiry", "opt_type", "strike"]).sum())
    o = o.drop(columns=["osi", "ts"])
    sp = pd.read_parquet(RAW / f"{t}.parquet")
    sp["date"] = pd.to_datetime(sp["date"]).dt.normalize()
    sp = sp.set_index("date")
    splits = sp.index[(sp["Stock Splits"].fillna(0) != 0) & (sp["Stock Splits"].fillna(0) != 1)]
    split_list = [(str(d.date()), float(sp.loc[d, "Stock Splits"])) for d in splits]
    o = o.join(sp["raw_close"].rename("S"), on="date")
    o["m"] = o["strike"] / o["S"]
    o["near"] = (o["m"] >= 0.8) & (o["m"] <= 1.2)
    o["offgrid"] = (np.round(o["strike"] * 100) % 50) != 0
    g = o.groupby("year")
    per_year = pd.DataFrame({
        "rows": g.size(),
        "rows_filt": g.apply(lambda d: int(((d["close"] >= 0.10) & (d["volume"] >= 1)).sum()), include_groups=False),
        "days": g["date"].nunique(),
        "exp_per_day_med": o.groupby(["year", "date"])["expiry"].nunique().groupby(level=0).median(),
        "vol_share_pm20": g.apply(lambda d: d.loc[d["near"], "volume"].sum() / max(d["volume"].sum(), 1), include_groups=False),
        "offgrid_row_share": g["offgrid"].mean(),
        "no_spot_rows": g["S"].apply(lambda s: int(s.isna().sum())),
    })
    # daily alignment: volume-weighted median moneyness and near-spot share
    def vw_median(d):
        d = d.dropna(subset=["m"]).sort_values("m")
        if d.empty: return np.nan
        c = d["volume"].cumsum().to_numpy(); return float(d["m"].to_numpy()[np.searchsorted(c, c[-1] / 2)])
    daily = o.groupby("date").apply(lambda d: pd.Series({
        "vw_med_m": vw_median(d),
        "near_share": d.loc[d["near"], "volume"].sum() / max(d["volume"].sum(), 1),
        "offgrid_vol_share": d.loc[d["offgrid"], "volume"].sum() / max(d["volume"].sum(), 1)}), include_groups=False)
    bad_days = daily[(daily["vw_med_m"] < 0.8) | (daily["vw_med_m"] > 1.25) | (daily["near_share"] < 0.4)]
    # trading days with spot but no option rows (2014-06-02 onward, spot calendar)
    cal = sp.loc["2014-06-02":].index
    opt_days = set(o["date"].unique())
    missing_days = [d for d in cal if d not in opt_days]
    # off-grid bursts: days where >20% of volume is off the 0.50 grid
    og = daily[daily["offgrid_vol_share"] > 0.2]
    rows[t] = {"per_year": per_year.reset_index().to_dict("records"), "n_badroot": n_badroot, "n_dup": n_dup,
               "splits": split_list, "n_bad_align_days": int(len(bad_days)),
               "bad_align_days": [(str(d.date()), round(r.vw_med_m, 3), round(r.near_share, 3)) for d, r in bad_days.head(40).iterrows()],
               "n_missing_days": len(missing_days), "missing_days": [str(d.date()) for d in missing_days[:30]],
               "offgrid_burst_days": int(len(og)), "offgrid_first_last": [str(og.index.min().date()), str(og.index.max().date())] if len(og) else None,
               "offgrid_months": og.groupby(og.index.to_period("M")).size().astype(int).rename(lambda p: str(p)).to_dict(),
               "near_share_daily_pctl": daily["near_share"].quantile([0.01, 0.05, 0.5]).round(3).tolist(),
               "secs": round(time.time() - t0, 1)}
    print(t, rows[t]["n_badroot"], rows[t]["n_dup"], rows[t]["splits"], rows[t]["n_bad_align_days"], rows[t]["n_missing_days"], rows[t]["offgrid_burst_days"], rows[t]["secs"], flush=True)
    del o, daily
(OUT / "data_qa.json").write_text(json.dumps(rows, indent=1, default=str))
