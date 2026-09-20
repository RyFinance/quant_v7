"""Daily options-implied signals per underlying, as registered in research/options_signals/PLAN.md
and PLAN_AMENDMENT_1.md.

Filters, in the order the registration states them:
  general  : close >= $0.10, volume >= 1 -- every signal
  H1 (O/S) : volumes only; no split rule (amendment 2), no parity or IV filter (amendment 1.2)
  H2, H3   : split rule (amendment 1.1)
  H2       : 7 <= DTE <= 60, |ln(K/S)| <= 0.10, both legs have an IV, parity gap <= 0.10*S
  H3       : nearest expiry with 10 <= DTE <= 60 holding both legs; put K/S in [0.80, 0.95] closest to
             0.95, call K/S in [0.95, 1.05] closest to 1.00, both with an IV
Each daily value is averaged over the 5 trading days ending on the signal date, needing >= 3.

`upto` truncates every input at a date before anything is computed, so a development run cannot
read option prints, spot prices or dividends from later dates.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr

ROOT = Path(__file__).resolve().parents[2]
OPT_DIR = ROOT / "data" / "lse" / "options_1d"
RAW_DIR = ROOT / "data" / "stocks_raw_2014"
DIV_DIR = ROOT / "data" / "lse" / "dividends"
FRENCH = ROOT / "reports" / "higher_sharpe" / "inputs" / "french_daily.zip"

MIN_PRICE = 0.10
IV_LO, IV_HI = 0.01, 3.0
WINDOW, MIN_DAYS = 5, 3


# -- inputs -------------------------------------------------------------------------------------
def french_daily() -> pd.DataFrame:
    z = zipfile.ZipFile(FRENCH)
    text = z.read(z.namelist()[0]).decode("latin1")
    lines = [ln for ln in text.splitlines() if ln[:8].strip().isdigit() and len(ln.split(",")) == 5]
    df = pd.read_csv(io.StringIO("\n".join(lines)), header=None, names=["date", "mkt_rf", "smb", "hml", "rf"])
    df["date"] = pd.to_datetime(df["date"].astype(str).str.strip(), format="%Y%m%d")
    return df.set_index("date")[["mkt_rf", "rf"]] / 100.0


def rate_series(calendar: pd.DatetimeIndex) -> pd.Series:
    """Annualised continuous rate on each trading day; last French value carried forward (amendment 1.4)."""
    rf = french_daily()["rf"].reindex(calendar.union(french_daily().index)).ffill().reindex(calendar)
    return np.log1p(rf) * 252.0


def load_spot(t: str, upto: pd.Timestamp | None = None) -> pd.DataFrame:
    d = pd.read_parquet(RAW_DIR / f"{t}.parquet")
    d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    d = d.set_index("date").sort_index()
    if upto is not None:
        d = d.loc[:upto]
    return d


def split_dates(spot: pd.DataFrame) -> list[pd.Timestamp]:
    s = spot["Stock Splits"].fillna(0)
    return list(s.index[(s != 0) & (s != 1)])


def raw_dividends(t: str) -> pd.Series:
    """Raw cash dividend per ex-date from the yfinance raw file (amendment 1.3): Dividends x
    split_factor_after, the same back-out that turns its Close into raw_close. Empty if absent."""
    d = pd.read_parquet(RAW_DIR / f"{t}.parquet")
    if not {"Dividends", "split_factor_after"} <= set(d.columns):
        return pd.Series(dtype=float)
    d = d[d["Dividends"].fillna(0) > 0]
    idx = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    return pd.Series((d["Dividends"] * d["split_factor_after"]).to_numpy(), index=pd.DatetimeIndex(idx))


def load_dividends(t: str, upto: pd.Timestamp | None = None, horizon_days: int = 70) -> pd.DataFrame:
    """Cash dividends by ex-date. A development run may see ex-dates up to `upto` + horizon, because
    the registered IV uses dividends expected before expiry (amendment 1.8, realised ex-dates).
    Amendment 3: the vault's rows set which dividends exist and when; where the raw yfinance file has a
    dividend on the same ex-date, its raw amount replaces the vault amount (back-adjusted for GE, T)."""
    p = DIV_DIR / f"{t}.parquet"
    if not p.exists():
        return pd.DataFrame(columns=["ex", "amount"])
    d = pd.read_parquet(p)
    d = pd.DataFrame({"ex": pd.to_datetime(d["effective_date"]), "amount": d["dividend_amount"].astype(float)})
    d = d[d["amount"] > 0]
    raw = raw_dividends(t)
    if len(raw):
        d["amount"] = d["ex"].map(raw).fillna(d["amount"])
    if upto is not None:
        d = d[d["ex"] <= upto + pd.Timedelta(days=horizon_days)]
    return d.sort_values("ex").reset_index(drop=True)


def load_options(t: str, upto: pd.Timestamp | None = None) -> pd.DataFrame:
    d = pd.read_parquet(OPT_DIR / f"{t}.parquet",
                        columns=["ts", "expiry", "opt_type", "strike", "osi", "close", "volume"])
    d["date"] = d["ts"].dt.tz_convert(None).dt.normalize()
    if upto is not None:
        d = d[d["date"] <= upto]
    d["expiry"] = pd.to_datetime(d["expiry"])
    d = d[(d["close"] >= MIN_PRICE) & (d["volume"] >= 1)]
    return d.drop(columns=["ts"]).reset_index(drop=True)


def drop_split_adjusted(opt: pd.DataFrame, splits: list[pd.Timestamp]) -> pd.DataFrame:
    """Amendment 1.1: after a split on D, drop every row whose expiry was already listed before D."""
    keep = np.ones(len(opt), dtype=bool)
    for D in splits:
        pre = set(opt.loc[opt["date"] < D, "expiry"].unique())
        keep &= ~((opt["date"] >= D).to_numpy() & opt["expiry"].isin(pre).to_numpy())
    return opt[keep].reset_index(drop=True)


# -- Black-Scholes implied volatility -------------------------------------------------------------
def bs_price(S, K, T, r, sig, is_call):
    sqT = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sig * sig) * T) / (sig * sqT)
    d2 = d1 - sig * sqT
    disc = K * np.exp(-r * T)
    call = S * ndtr(d1) - disc * ndtr(d2)
    put = disc * ndtr(-d2) - S * ndtr(-d1)
    return np.where(is_call, call, put)


def implied_vol(price, S, K, T, r, is_call, iters: int = 80) -> np.ndarray:
    """Vectorised bisection on [IV_LO, IV_HI]; NaN where the price is outside the attainable range."""
    price, S, K, T, r = (np.asarray(x, dtype=float) for x in (price, S, K, T, r))
    is_call = np.asarray(is_call, dtype=bool)
    lo = np.full(price.shape, IV_LO)
    hi = np.full(price.shape, IV_HI)
    p_lo = bs_price(S, K, T, r, lo, is_call)
    p_hi = bs_price(S, K, T, r, hi, is_call)
    ok = (price > p_lo) & (price < p_hi) & (S > 0) & (T > 0)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        above = bs_price(S, K, T, r, mid, is_call) > price
        hi = np.where(above, mid, hi)
        lo = np.where(above, lo, mid)
    return np.where(ok, 0.5 * (lo + hi), np.nan)


def pv_dividends(dates: np.ndarray, expiries: np.ndarray, r: np.ndarray, divs: pd.DataFrame) -> np.ndarray:
    out = np.zeros(len(dates))
    for ex, amt in zip(divs["ex"].to_numpy(), divs["amount"].to_numpy()):
        inside = (ex > dates) & (ex <= expiries)
        if inside.any():
            tau = (ex - dates[inside]) / np.timedelta64(1, "D") / 365.0
            out[inside] += amt * np.exp(-r[inside] * tau)
    return out


INTEGRITY_MIN_PAIRS, INTEGRITY_MAX_DEV = 3, 0.05


def wrong_underlying_days(opt: pd.DataFrame, rates: pd.Series, divs: pd.DataFrame) -> pd.DatetimeIndex:
    """Amendments 4-5: days whose options imply a spot more than 5% from the recorded raw close.

    Every same-strike, same-expiry call/put pair traded that day with 7 <= DTE <= 60, at any strike,
    gives S_impl = C - P + K e^(-rT) + PV(div); a day with at least 3 pairs is flagged when the median
    S_impl is more than 5% from the raw close (a different company behind the ticker, e.g. DD)."""
    o = opt[(opt["dte"] >= 7) & (opt["dte"] <= 60)]
    if o.empty:
        return pd.DatetimeIndex([])
    is_call = o["opt_type"].str.upper().str.startswith("C")
    key = ["date", "expiry", "strike"]
    pairs = o[is_call].set_index(key)[["close", "S", "dte"]].join(
        o[~is_call].set_index(key)[["close"]], lsuffix="_c", rsuffix="_p", how="inner").reset_index()
    if pairs.empty:
        return pd.DatetimeIndex([])
    r = rates.reindex(pairs["date"]).fillna(0.0).to_numpy()
    T = pairs["dte"].to_numpy() / 365.0
    pvd = pv_dividends(pairs["date"].to_numpy(), pairs["expiry"].to_numpy(), r, divs)
    pairs["s_impl"] = pairs["close_c"] - pairs["close_p"] + pairs["strike"] * np.exp(-r * T) + pvd
    g = pairs.groupby("date").agg(n=("s_impl", "size"), s_impl=("s_impl", "median"), S=("S", "first"))
    bad = (g["n"] >= INTEGRITY_MIN_PAIRS) & ((g["s_impl"] / g["S"] - 1).abs() > INTEGRITY_MAX_DEV)
    return pd.DatetimeIndex(g.index[bad])


# -- per-underlying daily signals -----------------------------------------------------------------
def daily_signals(t: str, upto: pd.Timestamp | None = None, rates: pd.Series | None = None) -> pd.DataFrame:
    spot = load_spot(t, upto)
    all_opt = load_options(t, upto)
    opt = drop_split_adjusted(all_opt, split_dates(spot))
    cal = spot.index
    if rates is None:
        rates = rate_series(cal)
    out = pd.DataFrame(index=cal)

    # H1: option-to-stock volume, both in shares; every contract counts (amendment 2)
    optvol = all_opt.groupby("date")["volume"].sum().reindex(cal)
    out["opt_shares"] = optvol * 100.0
    out["stock_shares"] = spot["raw_volume"]

    # contracts that need IVs
    opt = opt.join(spot["raw_close"].rename("S"), on="date")
    opt = opt[opt["S"].notna()]
    opt["dte"] = (opt["expiry"] - opt["date"]).dt.days
    opt["m"] = opt["strike"] / opt["S"]
    flagged = wrong_underlying_days(opt, rates, load_dividends(t, upto))
    need = opt[(opt["dte"] >= 7) & (opt["dte"] <= 60) & (opt["m"] >= 0.80) & (opt["m"] <= np.exp(0.10))].copy()
    if need.empty:
        out["ivspread"] = np.nan
        out["skew"] = np.nan
        out.loc[out.index.isin(flagged), ["opt_shares"]] = np.nan
        return out
    need["r"] = rates.reindex(need["date"]).to_numpy()
    need["T"] = need["dte"] / 365.0
    divs = load_dividends(t, upto)
    need["pvd"] = pv_dividends(need["date"].to_numpy(), need["expiry"].to_numpy(), need["r"].to_numpy(), divs)
    need["Sx"] = need["S"] - need["pvd"]
    need = need[need["Sx"] > 0]
    need["is_call"] = need["opt_type"].str.upper().str.startswith("C")
    need["iv"] = implied_vol(need["close"], need["Sx"], need["strike"], need["T"], need["r"], need["is_call"])

    # H2: volume-weighted call-minus-put IV over matched pairs
    h2 = need[(need["dte"] >= 7) & (np.abs(np.log(need["m"])) <= 0.10)]
    calls = h2[h2["is_call"]].set_index(["date", "expiry", "strike"])
    puts = h2[~h2["is_call"]].set_index(["date", "expiry", "strike"])
    pairs = calls[["close", "volume", "iv", "Sx", "T", "r"]].join(
        puts[["close", "volume", "iv"]], lsuffix="_c", rsuffix="_p", how="inner").reset_index()
    if not pairs.empty:
        gap = pairs["close_c"] - pairs["close_p"] - (pairs["Sx"] - pairs["strike"] * np.exp(-pairs["r"] * pairs["T"]))
        spot_at = spot["raw_close"].reindex(pairs["date"]).to_numpy()
        pairs = pairs[(np.abs(gap.to_numpy()) <= 0.10 * spot_at) & pairs["iv_c"].notna() & pairs["iv_p"].notna()]
        pairs["w"] = 0.5 * (pairs["volume_c"] + pairs["volume_p"])
        pairs["wd"] = pairs["w"] * (pairs["iv_c"] - pairs["iv_p"])
        g = pairs.groupby("date")[["wd", "w"]].sum()
        out["ivspread"] = (g["wd"] / g["w"]).reindex(cal)
    else:
        out["ivspread"] = np.nan

    # H3: OTM put (K/S closest to 0.95 within [0.80, 0.95]) minus ATM call (closest to 1.00 within [0.95, 1.05])
    h3 = need[(need["dte"] >= 10) & need["iv"].notna()]
    put_c = h3[(~h3["is_call"]) & (h3["m"] >= 0.80) & (h3["m"] <= 0.95)].copy()
    call_c = h3[h3["is_call"] & (h3["m"] >= 0.95) & (h3["m"] <= 1.05)].copy()
    put_c["dist"] = (put_c["m"] - 0.95).abs()
    call_c["dist"] = (call_c["m"] - 1.00).abs()
    best_put = put_c.sort_values(["date", "expiry", "dist", "strike"]).groupby(["date", "expiry"]).first()["iv"]
    best_call = call_c.sort_values(["date", "expiry", "dist", "strike"]).groupby(["date", "expiry"]).first()["iv"]
    both = pd.concat([best_put.rename("iv_put"), best_call.rename("iv_call")], axis=1, join="inner").reset_index()
    if not both.empty:
        nearest = both.sort_values(["date", "expiry"]).groupby("date").first()
        out["skew"] = (nearest["iv_put"] - nearest["iv_call"]).reindex(cal)
    else:
        out["skew"] = np.nan
    out.loc[out.index.isin(flagged), ["opt_shares", "ivspread", "skew"]] = np.nan  # amendments 4-5
    return out


def rolling_signals(daily: pd.DataFrame) -> pd.DataFrame:
    """5-trading-day aggregation ending on each date, needing at least 3 observed days."""
    res = pd.DataFrame(index=daily.index)
    have = daily["opt_shares"].notna() & daily["stock_shares"].gt(0)
    num = daily["opt_shares"].where(have).rolling(WINDOW, min_periods=MIN_DAYS).sum()
    den = daily["stock_shares"].where(have).rolling(WINDOW, min_periods=MIN_DAYS).sum()
    res["os"] = num / den
    for c in ("ivspread", "skew"):
        res[c] = daily[c].rolling(WINDOW, min_periods=MIN_DAYS).mean()
    return res
