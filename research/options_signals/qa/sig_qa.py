"""Options-signal QA (reports/options_signals/QA.md). Reads local files only; never calls the vault.
Run per name: PYTHONPATH=. .venv/bin/python research/options_signals/qa/sig_qa.py TICKER OUTDIR
Signal QA for one name, development window only (upto 2019-12-31).
Signal LEVELS, coverage and solver diagnostics only; no returns are loaded or computed."""
import json, resource, sys, time
from pathlib import Path
import numpy as np, pandas as pd
from research.options_signals import signals as sg

t, outdir = sys.argv[1], Path(sys.argv[2])
UPTO = pd.Timestamp("2019-12-31")
DEV0 = pd.Timestamp("2014-07-01")

# 1) official code path, timed exactly as evaluate._one runs it
t0 = time.perf_counter()
daily = sg.daily_signals(t, upto=UPTO)
t1 = time.perf_counter()
roll = sg.rolling_signals(daily)
t2 = time.perf_counter()
peak_rss_official = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20  # MiB (macOS reports bytes)

# 2) instrumented replica of daily_signals, stage-timed
st = {}
s0 = time.perf_counter()
spot = sg.load_spot(t, UPTO)
all_opt = sg.load_options(t, UPTO)
st["load"] = time.perf_counter() - s0
n_file = len(pd.read_parquet(sg.OPT_DIR / f"{t}.parquet", columns=["close"]))
splits = sg.split_dates(spot)
s0 = time.perf_counter()
opt = sg.drop_split_adjusted(all_opt, splits)
st["split_rule"] = time.perf_counter() - s0
split_info = {}
for D in splits:
    pre = set(all_opt.loc[all_opt["date"] < D, "expiry"].unique())
    mask = (all_opt["date"] >= D) & all_opt["expiry"].isin(pre)
    dd = all_opt[mask]
    dte = (dd["expiry"] - dd["date"]).dt.days
    iv_window = int(((dte >= 7) & (dte <= 60)).sum())
    split_info[str(D.date())] = {"ratio": float(spot.loc[D, "Stock Splits"]), "rows_dropped": int(mask.sum()),
                                 "rows_dropped_dte7_60": iv_window,
                                 "share_of_rows_next_60d": float(mask[(all_opt["date"] >= D) & (all_opt["date"] < D + pd.Timedelta(days=60))].mean()) if ((all_opt["date"] >= D) & (all_opt["date"] < D + pd.Timedelta(days=60))).any() else None,
                                 "last_date_dropped": str(dd["date"].max().date()) if len(dd) else None}
cal = spot.index
rates = sg.rate_series(cal)
opt = opt.join(spot["raw_close"].rename("S"), on="date")
n_nospot = int(opt["S"].isna().sum())
opt = opt[opt["S"].notna()]
opt["dte"] = (opt["expiry"] - opt["date"]).dt.days
opt["m"] = opt["strike"] / opt["S"]
need = opt[(opt["dte"] >= 7) & (opt["dte"] <= 60) & (opt["m"] >= 0.80) & (opt["m"] <= np.exp(0.10))].copy()
need["r"] = rates.reindex(need["date"]).to_numpy()
need["T"] = need["dte"] / 365.0
divs = sg.load_dividends(t, UPTO)
need["pvd"] = sg.pv_dividends(need["date"].to_numpy(), need["expiry"].to_numpy(), need["r"].to_numpy(), divs)
need["Sx"] = need["S"] - need["pvd"]
n_need0 = len(need)
n_sx_nonpos = int((need["Sx"] <= 0).sum())
need = need[need["Sx"] > 0]
need["is_call"] = need["opt_type"].str.upper().str.startswith("C")
s0 = time.perf_counter()
need["iv"] = sg.implied_vol(need["close"], need["Sx"], need["strike"], need["T"], need["r"], need["is_call"])
st["iv_solve"] = time.perf_counter() - s0
p_lo = sg.bs_price(need["Sx"].to_numpy(), need["strike"].to_numpy(), need["T"].to_numpy(), need["r"].to_numpy(), np.full(len(need), sg.IV_LO), need["is_call"].to_numpy())
p_hi = sg.bs_price(need["Sx"].to_numpy(), need["strike"].to_numpy(), need["T"].to_numpy(), need["r"].to_numpy(), np.full(len(need), sg.IV_HI), need["is_call"].to_numpy())
px = need["close"].to_numpy()
fail = need["iv"].isna().to_numpy()
iv = need["iv"].to_numpy()
ivq = {
    "n_need": int(n_need0), "n_sx_nonpos": n_sx_nonpos, "n_solved_input": int(len(need)),
    "fail_total": int(fail.sum()), "fail_share": float(fail.mean()) if len(need) else None,
    "fail_below_lo": int((fail & (px <= p_lo)).sum()), "fail_above_hi": int((fail & (px >= p_hi)).sum()),
    "fail_share_calls": float(fail[need["is_call"].to_numpy()].mean()), "fail_share_puts": float(fail[~need["is_call"].to_numpy()].mean()),
    "near_lo_(<0.02)": int((iv < 0.02).sum()), "near_hi_(>2.9)": int((iv > 2.9).sum()),
    "iv_pctl_1_50_99": [float(x) for x in np.nanpercentile(iv, [1, 50, 99])] if (~fail).any() else None,
}
# ATM IV per day: volume-weighted, |ln m| <= 0.05, 10 <= DTE <= 60, calls and puts
atm = need[(need["dte"] >= 10) & (np.abs(np.log(need["m"])) <= 0.05) & need["iv"].notna()]
atm_daily = (atm["iv"] * atm["volume"]).groupby(atm["date"]).sum() / atm["volume"].groupby(atm["date"]).sum()
atm_daily = atm_daily.loc[DEV0:]
# H2 replica with drop accounting
s0 = time.perf_counter()
h2 = need[(need["dte"] >= 7) & (np.abs(np.log(need["m"])) <= 0.10)]
calls = h2[h2["is_call"]].set_index(["date", "expiry", "strike"])
puts = h2[~h2["is_call"]].set_index(["date", "expiry", "strike"])
pairs = calls[["close", "volume", "iv", "Sx", "T", "r"]].join(puts[["close", "volume", "iv"]], lsuffix="_c", rsuffix="_p", how="inner").reset_index()
gap = pairs["close_c"] - pairs["close_p"] - (pairs["Sx"] - pairs["strike"] * np.exp(-pairs["r"] * pairs["T"]))
spot_at = spot["raw_close"].reindex(pairs["date"]).to_numpy()
par_ok = np.abs(gap.to_numpy()) <= 0.10 * spot_at
iv_ok = (pairs["iv_c"].notna() & pairs["iv_p"].notna()).to_numpy()
h2q = {"pairs": int(len(pairs)), "parity_fail": int((~par_ok).sum()), "parity_fail_share": float((~par_ok).mean()) if len(pairs) else None,
       "iv_missing_either_leg": int((~iv_ok).sum()), "parity_fail_but_iv_ok": int((~par_ok & iv_ok).sum()), "kept": int((par_ok & iv_ok).sum()),
       "parity_gap_over_S_pctl_50_99": [float(x) for x in np.nanpercentile(np.abs(gap.to_numpy()) / spot_at, [50, 99])] if len(pairs) else None}
kp = pairs[par_ok & iv_ok].copy()
kp["w"] = 0.5 * (kp["volume_c"] + kp["volume_p"])
kp["wd"] = kp["w"] * (kp["iv_c"] - kp["iv_p"])
g = kp.groupby("date")[["wd", "w"]].sum()
rep_iv = (g["wd"] / g["w"]).reindex(cal)
h2q["pairs_per_day_median"] = float(kp.groupby("date").size().median()) if len(kp) else 0
st["h2"] = time.perf_counter() - s0
s0 = time.perf_counter()
h3 = need[(need["dte"] >= 10) & need["iv"].notna()]
put_c = h3[(~h3["is_call"]) & (h3["m"] >= 0.80) & (h3["m"] <= 0.95)].copy()
call_c = h3[h3["is_call"] & (h3["m"] >= 0.95) & (h3["m"] <= 1.05)].copy()
put_c["dist"] = (put_c["m"] - 0.95).abs(); call_c["dist"] = (call_c["m"] - 1.00).abs()
bp = put_c.sort_values(["date", "expiry", "dist", "strike"]).groupby(["date", "expiry"]).first()[["iv", "m", "dte"]]
bc = call_c.sort_values(["date", "expiry", "dist", "strike"]).groupby(["date", "expiry"]).first()[["iv", "m", "dte"]]
both = bp.join(bc, lsuffix="_put", rsuffix="_call", how="inner").reset_index()
nearest = both.sort_values(["date", "expiry"]).groupby("date").first()
rep_skew = (nearest["iv_put"] - nearest["iv_call"]).reindex(cal)
st["h3"] = time.perf_counter() - s0
# replica must reproduce the official output exactly
assert np.array_equal(rep_iv.to_numpy(), daily["ivspread"].to_numpy(), equal_nan=True), "ivspread replica mismatch"
assert np.array_equal(rep_skew.to_numpy(), daily["skew"].to_numpy(), equal_nan=True), "skew replica mismatch"

# coverage and distributions, development window
dv = daily.loc[DEV0:]; rv = roll.loc[DEV0:]
iso = rv.index.isocalendar()
sig_days = pd.DatetimeIndex(pd.Series(rv.index, index=rv.index).groupby([iso["year"].to_numpy(), iso["week"].to_numpy()]).max().to_numpy())
os_daily = (dv["opt_shares"] / dv["stock_shares"]).where(dv["stock_shares"] > 0)
def pct(s):
    s = s.dropna()
    return [float(x) for x in np.percentile(s, [1, 5, 25, 50, 75, 95, 99])] if len(s) else None
def longest_gap(s):
    na = s.isna().to_numpy(); best = cur = 0; end = None
    for i, v in enumerate(na):
        cur = cur + 1 if v else 0
        if cur > best: best, end = cur, s.index[i]
    return best, (str(s.index[max(0, s.index.get_loc(end) - best + 1)].date()) + ".." + str(end.date())) if end is not None else None
res = {
    "name": t, "secs_daily_signals": t1 - t0, "secs_rolling": t2 - t1, "peak_rss_mib": peak_rss_official,
    "stage_secs": st, "rows_file": n_file, "rows_upto_after_general_filter": int(len(all_opt)),
    "rows_after_split_rule": int(len(opt) + n_nospot), "rows_no_spot": n_nospot,
    "dev_days": int(len(dv)),
    "coverage_daily": {"os": float(os_daily.notna().mean()), "ivspread": float(dv["ivspread"].notna().mean()), "skew": float(dv["skew"].notna().mean())},
    "coverage_rolling": {c: float(rv[c].notna().mean()) for c in ("os", "ivspread", "skew")},
    "coverage_signal_dates": {c: float(rv.loc[sig_days, c].notna().mean()) for c in ("os", "ivspread", "skew")},
    "longest_gap_rolling": {c: longest_gap(rv[c]) for c in ("ivspread", "skew")},
    "pctl_rolling_1_5_25_50_75_95_99": {c: pct(rv[c]) for c in ("os", "ivspread", "skew")},
    "median_by_year": {c: {int(k): float(v) for k, v in rv[c].groupby(rv.index.year).median().items()} for c in ("os", "ivspread", "skew")},
    "skew_negative_share_daily": float((dv["skew"].dropna() < 0).mean()) if dv["skew"].notna().any() else None,
    "ivspread_abs_gt_5pct_share_rolling": float((rv["ivspread"].dropna().abs() > 0.05).mean()) if rv["ivspread"].notna().any() else None,
    "atm_iv_median": float(atm_daily.median()) if len(atm_daily) else None,
    "atm_iv_by_year": {int(k): float(v) for k, v in atm_daily.groupby(atm_daily.index.year).median().items()},
    "atm_iv_pctl_1_99": [float(x) for x in np.percentile(atm_daily.dropna(), [1, 99])] if len(atm_daily) else None,
    "h3_leg_m_median": {"put": float(nearest["m_put"].median()), "call": float(nearest["m_call"].median()), "dte": float(nearest["dte_put"].median())} if len(nearest) else None,
    "iv": ivq, "h2": h2q, "splits": split_info,
}
(outdir / f"sig_{t}.json").write_text(json.dumps(res, indent=1, default=str))
# save signal levels (no returns) for cross-sectional level checks
roll.loc[DEV0:].to_parquet(outdir / f"roll_{t}.parquet")
print(f"{t}: daily_signals {t1-t0:.1f}s peak {peak_rss_official:.0f} MiB  cov_sig {res['coverage_signal_dates']}  atmIV {res['atm_iv_median']}")
