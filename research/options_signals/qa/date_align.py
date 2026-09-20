"""Options-signal QA (reports/options_signals/QA.md). Reads local files only; never calls the vault.
Run: PYTHONPATH=. .venv/bin/python research/options_signals/qa/date_align.py OUT.json TICKER [TICKER ...]
Date-alignment check: put-call-parity implied spot vs raw close on the same day and +-1 day.
Prices only; no signal or return statistic."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
from research.options_signals import signals as sg

UPTO = pd.Timestamp("2019-12-31")
out = {}
for t in sys.argv[2:]:
    spot = sg.load_spot(t, UPTO)
    opt = sg.drop_split_adjusted(sg.load_options(t, UPTO), sg.split_dates(spot))
    opt = opt.join(spot["raw_close"].rename("S"), on="date").dropna(subset=["S"])
    opt["dte"] = (opt["expiry"] - opt["date"]).dt.days
    opt = opt[(opt["dte"] >= 7) & (opt["dte"] <= 60) & (np.abs(np.log(opt["strike"] / opt["S"])) <= 0.05)]
    r = sg.rate_series(spot.index)
    c = opt[opt["opt_type"] == "C"].set_index(["date", "expiry", "strike"])["close"]
    p = opt[opt["opt_type"] == "P"].set_index(["date", "expiry", "strike"])["close"]
    pr = pd.concat([c.rename("C"), p.rename("P")], axis=1, join="inner").reset_index()
    pr["r"] = r.reindex(pr["date"]).to_numpy()
    T = (pr["expiry"] - pr["date"]).dt.days / 365.0
    pvd = sg.pv_dividends(pr["date"].to_numpy(), pr["expiry"].to_numpy(), pr["r"].to_numpy(), sg.load_dividends(t, UPTO))
    pr["S_impl"] = pr["C"] - pr["P"] + pr["strike"] * np.exp(-pr["r"] * T) + pvd
    daily = pr.groupby("date")["S_impl"].median()
    S = spot["raw_close"]
    res = {}
    for k in (-1, 0, 1):
        ref = S.shift(-k).reindex(daily.index)   # k=+1 compares with the next day's close
        res[k] = float(np.nanmedian(np.abs(np.log(daily / ref))))
    out[t] = {"median_abs_log_err_lag": res, "days": int(len(daily))}
    print(t, {k: f"{v*1e4:.1f}bp" for k, v in res.items()}, flush=True)
Path(sys.argv[1]).write_text(json.dumps(out, indent=1))
