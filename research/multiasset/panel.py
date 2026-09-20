"""Clean daily panels for the multi-asset sleeves, with a hard hold-out guard.

Nothing here returns a date after DEV_END unless the hold-out pre-registration
exists AND its SHA-256 is in research/preregistrations.jsonl. That makes the
protocol in PLAN.md mechanical instead of a matter of discipline.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/multiasset"
DEV_END = pd.Timestamp("2017-12-31")
HOLDOUT_START = pd.Timestamp("2018-01-01")
HOLDOUT_END = pd.Timestamp("2026-09-17")  # last complete session when the data was pulled
HOLDOUT_PREREG = ROOT / "research/multiasset/PREREGISTRATION_holdout.md"
REGISTRY = ROOT / "research/preregistrations.jsonl"

ETF_CLASSES = json.loads((DATA / "manifest.json").read_text())["etf_classes"] if (DATA / "manifest.json").exists() else {}
FX_PAIRS = {"EUR": "EURUSD", "GBP": "GBPUSD", "AUD": "AUDUSD", "NZD": "NZDUSD",
            "JPY": "USDJPY", "CHF": "USDCHF", "CAD": "USDCAD", "SEK": "USDSEK", "NOK": "USDNOK"}
POLICY = {"USD": "fdtr", "EUR": "eurr002w", "GBP": "ukbrbase", "JPY": "bojdtr", "CHF": "szlttr",
          "AUD": "rbatctr", "NZD": "nzocrs", "CAD": "cclr", "SEK": "swrratei", "NOK": "nobrdep"}
# 10-year yield -> the currency whose policy rate is its local short rate
BOND_CCY = {"US10Y": "USD", "DE10Y": "EUR", "FR10Y": "EUR", "IT10Y": "EUR", "ES10Y": "EUR", "JP10Y": "JPY",
            "CA10Y": "CAD", "AU10Y": "AUD", "CH10Y": "CHF", "SE10Y": "SEK", "NO10Y": "NOK", "NZ10Y": "NZD"}


class HoldoutLocked(RuntimeError):
    pass


def holdout_unlocked() -> bool:
    if not HOLDOUT_PREREG.exists():
        return False
    digest = hashlib.sha256(HOLDOUT_PREREG.read_bytes()).hexdigest()
    rel = str(HOLDOUT_PREREG.relative_to(ROOT))
    for line in REGISTRY.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("file") == rel and rec.get("sha256") == digest:
            return True
    return False


def resolve_end(end) -> pd.Timestamp:
    end = pd.Timestamp(end) if end is not None else DEV_END
    if end > DEV_END and not holdout_unlocked():
        raise HoldoutLocked(f"dates after {DEV_END.date()} need the registered hold-out pre-registration "
                            f"({HOLDOUT_PREREG.relative_to(ROOT)})")
    return min(end, HOLDOUT_END)


def _read(folder: str, name: str) -> pd.DataFrame:
    return pd.read_parquet(DATA / folder / f"{name}.parquet")


@lru_cache(maxsize=None)
def _calendar_full() -> pd.DatetimeIndex:
    """NYSE sessions, taken from SPY's official bars."""
    d = pd.to_datetime(_read("etf", "SPY")["date"]).dt.tz_localize(None).dt.normalize()
    return pd.DatetimeIndex(d.sort_values().unique())


def calendar(end=None) -> pd.DatetimeIndex:
    end = resolve_end(end)
    cal = _calendar_full()
    return cal[cal <= end]


def _yf_close(folder: str, name: str, field: str = "close") -> pd.Series:
    d = _read(folder, name)
    idx = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
    s = pd.Series(d[field].to_numpy(dtype=float), index=idx).sort_index()
    return s[~s.index.duplicated(keep="last")]


def etf_prices(end=None, field: str = "close") -> pd.DataFrame:
    cal = calendar(end)
    names = [s for syms in ETF_CLASSES.values() for s in syms]
    return pd.DataFrame({s: _yf_close("etf", s, field).reindex(cal) for s in names})


def etf_returns(end=None) -> pd.DataFrame:
    px = etf_prices(end)
    # pct_change with fill_method=None leaves pre-inception NaN instead of inventing zeros
    return px.pct_change(fill_method=None)


def risk_free(end=None) -> pd.Series:
    """Daily T-bill return from ^IRX (percent, discount basis), accrued over calendar days."""
    cal = calendar(end)
    irx = _yf_close("rates", "IRX").reindex(cal).ffill() / 100.0
    days = pd.Series(cal, index=cal).diff().dt.days.fillna(1)
    return (irx.shift(1) * days / 360.0).fillna(0.0).rename("rf")


def vol_panel(end=None) -> pd.DataFrame:
    cal = calendar(end)
    return pd.DataFrame({"VIX": _yf_close("vol", "VIX").reindex(cal),
                         "VIX3M": _yf_close("vol", "VIX3M").reindex(cal),
                         "VIXY": _yf_close("vol", "VIXY").reindex(cal),
                         "SVXY": _yf_close("vol", "SVXY").reindex(cal)})


def _vault_daily(folder: str, name: str) -> pd.Series:
    d = _read(folder, name)
    ts = pd.to_datetime(d["ts"])
    s = pd.Series(d["close"].to_numpy(dtype=float), index=ts).sort_index()
    s = s[s.index.dayofweek < 5]  # the Sunday-evening open is folded into Monday's move
    return s[~s.index.duplicated(keep="last")]


def fx_usd_per_unit(end=None) -> pd.DataFrame:
    """USD value of one unit of each foreign currency, as of each NYSE session.

    Vault FX bars close at 00:00 UTC. The bar dated D closes at the end of UTC day D,
    which is about 20:00 ET on D, after the NYSE close. To avoid using a price that
    was not yet known at the NYSE close on D, the session D value is the close of
    the bar dated D-1 (the latest one fully printed before 16:00 ET on D).
    """
    cal = calendar(end)
    out = {}
    for ccy, pair in FX_PAIRS.items():
        s = _vault_daily("fx", pair)
        s.index = s.index + pd.Timedelta(days=1)  # bar D-1 is the known value on session D
        s = s.reindex(cal, method="ffill", tolerance=pd.Timedelta(days=5))
        out[ccy] = s if pair.startswith(ccy) else 1.0 / s
    return pd.DataFrame(out)


def policy_rates(end=None) -> pd.DataFrame:
    """Policy rates in decimal, as of each session. A decision dated D is used from D+1."""
    cal = calendar(end)
    out = {}
    for ccy, sym in POLICY.items():
        d = _read("policy", sym)
        s = pd.Series(d["value"].to_numpy(dtype=float) / 100.0, index=pd.to_datetime(d["date"])).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        s.index = s.index + pd.Timedelta(days=1)
        out[ccy] = s.reindex(cal.union(s.index)).ffill().reindex(cal)
    return pd.DataFrame(out)


def despike(s: pd.Series, threshold: float = 0.0015) -> pd.Series:
    """Drop one-day bad prints: a value that jumps more than `threshold` away from BOTH
    neighbours, in the same direction, while the neighbours agree with each other
    (JP10Y 0.701 -> 0.000 -> 0.669; NZ10Y 6.05 -> 5.11 -> 6.14). A real move does not
    reverse the next day, so it survives. This uses the next print, which is fine for
    removing vendor errors but means a live system needs its own bad-tick filter."""
    prev, nxt = s.shift(1), s.shift(-1)
    up, down = s - prev, s - nxt
    spike = (up.abs() > threshold) & (down.abs() > threshold) & (np.sign(up) == np.sign(down)) \
        & ((nxt - prev).abs() < 0.5 * np.minimum(up.abs(), down.abs()))
    zero = (s == 0) & (prev.abs() > 0.002) & (nxt.abs() > 0.002)
    return s[~(spike | zero)]


def yields10(end=None) -> pd.DataFrame:
    """10-year yields in decimal. Daily series; a gap of up to 5 sessions is carried forward."""
    cal = calendar(end)
    out = {}
    for sym in BOND_CCY:
        try:
            d = _read("yields", sym)
        except FileNotFoundError:
            continue
        s = pd.Series(d["value"].to_numpy(dtype=float) / 100.0, index=pd.to_datetime(d["date"])).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        s = despike(s[s.index <= cal[-1]])   # the filter peeks one print ahead; never past the window
        # Yields are end-of-day in their own market; most close before 16:00 ET, but JP/AU/NZ
        # close the same calendar day well before, and US closes at ~17:00 ET. Lag one day
        # uniformly so no session sees a later print.
        s.index = s.index + pd.Timedelta(days=1)
        out[sym] = s.reindex(cal.union(s.index)).ffill(limit=5).reindex(cal)
    return pd.DataFrame(out)


def futures_30m(symbol: str, end=None) -> pd.DataFrame:
    end = resolve_end(end)
    d = _read("futures", symbol.replace(".", "_"))
    d = d.copy()
    d["ts"] = pd.to_datetime(d["ts"]).dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    d = d[d["ts"].dt.tz_localize(None) <= end + pd.Timedelta(days=1)]
    return d.sort_values("ts").reset_index(drop=True)


def crypto_close(symbol: str, end=None) -> pd.Series:
    end = resolve_end(end)
    d = _read("crypto", symbol)
    s = pd.Series(d["close"].to_numpy(dtype=float), index=pd.to_datetime(d["ts"])).sort_index()
    return s[s.index <= end]


CPI_SYMBOLS = {"USD": "unitedstaconpriindcp", "EUR": "euroareaconpriindcp", "GBP": "unitedkinconpriindcp",
               "JPY": "japanconpriindcpi", "CHF": "switzerlanconpriindc", "AUD": "ausquacpi",
               "NZD": "newzealanconpriindcp", "CAD": "canadaconpriindcpi", "SEK": "swedenconpriindcpi",
               "NOK": "norwayconpriindcpi"}
QUARTERLY_CPI = {"AUD", "NZD"}
YF_FX = {"EUR": "EURUSD=X", "GBP": "GBPUSD=X", "AUD": "AUDUSD=X", "NZD": "NZDUSD=X", "JPY": "JPY=X",
         "CHF": "CHF=X", "CAD": "CAD=X", "SEK": "SEK=X", "NOK": "NOK=X"}


def cpi(end=None) -> pd.DataFrame:
    """CPI levels as known on each session: a monthly print is used two months after its
    reference month, a quarterly one (AU, NZ) three months after, which is after release."""
    cal = calendar(end)
    out = {}
    for ccy, sym in CPI_SYMBOLS.items():
        d = _read("cpi", sym)
        s = pd.Series(d["value"].to_numpy(dtype=float), index=pd.to_datetime(d["date"])).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        s.index = s.index + pd.DateOffset(months=3 if ccy in QUARTERLY_CPI else 2)
        out[ccy] = s.reindex(cal.union(s.index)).ffill().reindex(cal)
    return pd.DataFrame(out)


def fx_spot_long(end=None) -> pd.DataFrame:
    """USD per foreign unit back to 2003 for slow signals only: vault FX where it exists,
    yfinance spot before that. Same one-day lag as fx_usd_per_unit."""
    cal = calendar(end)
    vault = fx_usd_per_unit(end)
    out = {}
    for ccy, sym in YF_FX.items():
        s = _yf_close("fx_yf", _fname_yf(sym))
        s = s if sym.startswith(ccy) else 1.0 / s
        s.index = s.index + pd.Timedelta(days=1)
        yf_side = s.reindex(cal, method="ffill", tolerance=pd.Timedelta(days=5))
        out[ccy] = vault[ccy].combine_first(yf_side)
    return pd.DataFrame(out)


def _fname_yf(symbol: str) -> str:
    return symbol.replace("/", "").replace("^", "").replace(".", "_")


@lru_cache(maxsize=None)
def _stock_ohlc_full() -> tuple[pd.DataFrame, pd.DataFrame]:
    cal = _calendar_full()
    opens, closes = {}, {}
    for path in sorted((DATA / "stocks").glob("*.parquet")):
        d = pd.read_parquet(path)
        idx = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
        d = d.set_index(idx)
        d = d[~d.index.duplicated(keep="last")]
        opens[path.stem] = d["open"].reindex(cal)
        closes[path.stem] = d["close"].reindex(cal)
    return pd.DataFrame(opens), pd.DataFrame(closes)


def stock_open_close(end=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Official daily opens and closes (yfinance, adjusted) for the current S&P 500 members.
    SURVIVORSHIP-BIASED: today's constituents, back-filled."""
    cal = calendar(end)
    o, c = _stock_ohlc_full()
    return o.loc[cal], c.loc[cal]
