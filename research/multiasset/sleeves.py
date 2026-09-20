"""The seven candidate sleeves from PLAN.md, each returning DAILY EXCESS returns
(over the T-bill rate) net of trading costs and borrow, on the NYSE calendar.

Shared execution rule: a weight decided with data through session t earns the
asset's return from session t+2 on (traded at the t+1 close). Costs are charged
on the change in weight on the day the trade happens.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.multiasset import panel

ETF_COST = 5e-4        # one-way, fraction of notional traded
FX_COST = 1e-4
ETF_BORROW = 0.01      # annual, on short notional
VIXY_BORROW = 0.03
LAG = 2


def month_ends(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby([index.year, index.month]).max().values)


def hold_monthly(targets: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Targets set on month-end sessions, held (as constant weights) until the next."""
    return targets.reindex(index).ffill()


def run_weights(weights: pd.DataFrame, excess: pd.DataFrame, cost: float | pd.Series,
                borrow: float = 0.0) -> pd.DataFrame:
    """Daily P&L of held weights. weights[t] is decided at close t."""
    weights = weights.reindex(excess.index).fillna(0.0)
    held = weights.shift(LAG).fillna(0.0)          # earning weights
    traded = weights.shift(LAG - 1).fillna(0.0)    # the trade executes at close t+1
    turnover = traded.diff().abs().fillna(traded.abs())
    gross = (held * excess.fillna(0.0)).sum(axis=1)
    costs = (turnover * cost).sum(axis=1)
    days = pd.Series(excess.index, index=excess.index).diff().dt.days.fillna(1)
    borrow_cost = (held.clip(upper=0).abs() * borrow).sum(axis=1) * days / 365.0
    net = gross - costs - borrow_cost
    return pd.DataFrame({"net": net, "gross": gross, "cost": costs + borrow_cost,
                         "gross_exposure": held.abs().sum(axis=1)})


def ewma_vol(returns: pd.DataFrame, com: int = 60) -> pd.DataFrame:
    """Moskowitz-Ooi-Pedersen ex-ante volatility: EWMA of squared returns, annualized."""
    return np.sqrt((returns ** 2).ewm(com=com, min_periods=com).mean() * 261)


def side_weights(values: pd.Series, k: int) -> pd.Series:
    """+1/k on the top k, -1/k on the bottom k. Ties across a cut share its slots equally."""
    v = values.dropna()
    w = pd.Series(0.0, index=values.index)
    if len(v) < 2 * k:
        return w
    for sign, ordered in ((1.0, v.sort_values(ascending=False)), (-1.0, v.sort_values())):
        cut = ordered.iloc[k - 1]
        strictly = ordered[(ordered > cut) if sign > 0 else (ordered < cut)]
        tied = ordered[ordered == cut]
        slots = k - len(strictly)
        w[strictly.index] += sign / k
        w[tied.index] += sign * slots / (k * len(tied))
    return w


# ---------------------------------------------------------------------------
# 1. Cross-asset time-series momentum (Moskowitz, Ooi, Pedersen 2012)
# ---------------------------------------------------------------------------
def tsmom(end=None, lookback: int = 252, target_vol: float = 0.40, com: int = 60) -> pd.DataFrame:
    rets = panel.etf_returns(end)
    rf = panel.risk_free(end)
    excess = rets.sub(rf, axis=0)
    vol = ewma_vol(rets, com)
    past = (1 + excess).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True) - 1
    raw = np.sign(past) * target_vol / vol
    me = month_ends(rets.index)
    targets = raw.loc[me]
    n = targets.notna().sum(axis=1).replace(0, np.nan)
    targets = targets.div(n, axis=0).fillna(0.0)   # average across the instruments alive that month
    w = hold_monthly(targets, rets.index)
    return run_weights(w, excess, ETF_COST, ETF_BORROW)


# ---------------------------------------------------------------------------
# 2-3. G10 FX carry and dollar carry
# ---------------------------------------------------------------------------
def fx_excess(end=None) -> pd.DataFrame:
    """Daily excess return of holding each foreign currency against USD: spot move plus
    the interest differential, accrued on calendar days (money-market 360 basis)."""
    spot = panel.fx_usd_per_unit(end)
    rates = panel.policy_rates(end)
    days = pd.Series(spot.index, index=spot.index).diff().dt.days
    diff = rates[spot.columns].sub(rates["USD"], axis=0).shift(1)
    return spot.pct_change(fill_method=None) + diff.mul(days / 360.0, axis=0)


def fx_carry(end=None, k: int = 3) -> pd.DataFrame:
    excess = fx_excess(end)
    rates = panel.policy_rates(end)
    me = month_ends(excess.index)
    rows = {}
    for d in me:
        r = rates.loc[d]
        if r.isna().any() or excess.loc[:d, "EUR"].notna().sum() < 5:
            continue
        w = side_weights(r, k)           # ranked across all ten, USD included
        rows[d] = w.drop("USD")          # the USD leg earns zero excess by construction
    w = hold_monthly(pd.DataFrame(rows).T, excess.index)
    return run_weights(w, excess, FX_COST)


def dollar_carry(end=None) -> pd.DataFrame:
    excess = fx_excess(end)
    rates = panel.policy_rates(end)
    me = month_ends(excess.index)
    rows = {}
    for d in me:
        r = rates.loc[d]
        if r.isna().any() or excess.loc[:d, "EUR"].notna().sum() < 5:
            continue
        sign = np.sign(r.drop("USD").mean() - r["USD"])
        rows[d] = pd.Series(sign / 9.0, index=excess.columns)
    w = hold_monthly(pd.DataFrame(rows).T, excess.index)
    return run_weights(w, excess, FX_COST)


# ---------------------------------------------------------------------------
# 4. Global bond carry (Koijen, Moskowitz, Pedersen, Vrugt 2018)
# ---------------------------------------------------------------------------
def bond_excess(end=None) -> pd.DataFrame:
    """Daily FX-hedged excess return of a constant-maturity 10-year par bond, from yields:
    carry y*dt, minus duration times the yield change, plus convexity, less the local
    short rate. A research approximation of a bond future, not a traded price."""
    y = panel.yields10(end)
    rates = panel.policy_rates(end)
    days = pd.Series(y.index, index=y.index).diff().dt.days
    y0 = y.shift(1)
    dur = (1 - (1 + y0 / 2) ** -20) / y0.where(y0.abs() > 1e-4)
    dur = dur.fillna(10.0)
    dy = y - y0
    local = pd.DataFrame({c: rates[panel.BOND_CCY[c]] for c in y.columns}).shift(1)
    return y0.mul(days / 365.0, axis=0) - dur * dy + 0.5 * dur ** 2 * dy ** 2 - local.mul(days / 360.0, axis=0)


def bond_carry(end=None, k: int = 3) -> pd.DataFrame:
    excess = bond_excess(end)
    y = panel.yields10(end)
    rates = panel.policy_rates(end)
    carry = pd.DataFrame({c: y[c] - rates[panel.BOND_CCY[c]] for c in y.columns})
    vol = excess.rolling(252, min_periods=126).std() * np.sqrt(252)
    me = month_ends(excess.index)
    rows = {}
    for d in me:
        c = carry.loc[d].where(vol.loc[d].notna())
        if c.notna().sum() < 2 * k:
            continue
        s = side_weights(c, k)
        inv = (1.0 / vol.loc[d]).where(s != 0, 0.0).fillna(0.0)
        w = pd.Series(0.0, index=c.index)
        for sign in (1, -1):
            side = s[np.sign(s) == sign].index
            if len(side):
                w[side] = sign * inv[side] / inv[side].sum()
        rows[d] = w
    w = hold_monthly(pd.DataFrame(rows).T, excess.index)
    # Bond futures: roughly 1 bp one-way at the tick; charged like FX.
    return run_weights(w, excess, FX_COST)


# ---------------------------------------------------------------------------
# 5. VIX futures basis (Simon and Campasano 2014)
# ---------------------------------------------------------------------------
def vix_basis(end=None) -> pd.DataFrame:
    v = panel.vol_panel(end)
    rf = panel.risk_free(end)
    excess = pd.DataFrame({"VIXY": v["VIXY"].pct_change(fill_method=None) - rf})
    contango = (v["VIX"] < v["VIX3M"]) & v["VIXY"].notna()
    w = pd.DataFrame({"VIXY": -contango.astype(float)})
    return run_weights(w, excess, ETF_COST, VIXY_BORROW)


# ---------------------------------------------------------------------------
# 6. Intraday market momentum (Gao, Han, Li, Zhou 2018)
# ---------------------------------------------------------------------------
FUT_SPEC = {"ES.F": {"multiplier": 50.0, "tick": 0.25}, "NQ.F": {"multiplier": 20.0, "tick": 0.25}}
COMMISSION_RT = 4.50


def intraday_momentum_one(symbol: str, end=None) -> pd.DataFrame:
    bars = panel.futures_30m(symbol, end)
    t = bars["ts"]
    bars = bars.assign(day=t.dt.tz_localize(None).dt.normalize(), hm=t.dt.hour * 60 + t.dt.minute)
    rth = bars[(bars.hm >= 9 * 60 + 30) & (bars.hm <= 15 * 60 + 30)]
    g = rth.groupby("day")
    session_close = g.apply(lambda x: x.loc[x.hm.idxmax(), "close"], include_groups=False)
    last_bar = g["hm"].max()
    at = rth.set_index(["day", "hm"])["close"]
    p10 = at.xs(9 * 60 + 30, level="hm")        # close of the 9:30 bar = 10:00 price
    p1530 = at.xs(15 * 60, level="hm")          # close of the 15:00 bar = 15:30 price
    p16 = at.xs(15 * 60 + 30, level="hm")       # close of the 15:30 bar = 16:00 price
    prev_close = session_close.shift(1)
    df = pd.DataFrame({"prev_close": prev_close, "p10": p10, "entry": p1530, "exit": p16,
                       "full_day": last_bar == 15 * 60 + 30}).dropna()
    df = df[df.full_day]
    spec = FUT_SPEC[symbol]
    signal = np.sign(df.p10 / df.prev_close - 1)
    move = df.exit / df.entry - 1
    cost = (spec["tick"] * spec["multiplier"] + COMMISSION_RT) / (df.entry * spec["multiplier"])
    out = pd.DataFrame({"gross": signal * move, "cost": cost * (signal != 0)})
    out["net"] = out.gross - out.cost
    out["gross_exposure"] = (signal != 0).astype(float)
    return out


def intraday_momentum(end=None) -> pd.DataFrame:
    cal = panel.calendar(end)
    legs = [intraday_momentum_one(s, end).reindex(cal).fillna(0.0) for s in ("ES.F", "NQ.F")]
    out = sum(legs) / len(legs)
    first = min(l.index[l.gross_exposure > 0][0] for l in legs)
    return out[out.index >= first]


# ---------------------------------------------------------------------------
# 7. Cross-sectional momentum within asset classes (Asness, Moskowitz, Pedersen 2013)
# ---------------------------------------------------------------------------
def xs_momentum(end=None) -> pd.DataFrame:
    rets = panel.etf_returns(end)
    rf = panel.risk_free(end)
    excess = rets.sub(rf, axis=0)
    score = (1 + rets).rolling(231, min_periods=231).apply(np.prod, raw=True).shift(21) - 1  # 12-1 month
    me = month_ends(rets.index)
    class_pnls, class_w = [], []
    for cls, names in panel.ETF_CLASSES.items():
        if len(names) < 6:
            continue
        k = len(names) // 3
        rows = {d: side_weights(score.loc[d, names], k) for d in me}
        w = hold_monthly(pd.DataFrame(rows).T, rets.index)
        # scale each class to equal risk with its own trailing vol (lagged), then average
        res = run_weights(w, excess[names], ETF_COST, ETF_BORROW)
        vol = res.net.rolling(252, min_periods=126).std() * np.sqrt(252)
        # resized only at the monthly rebalance, so scaling adds no daily turnover
        scale = (0.10 / vol).clip(upper=4.0).reindex(me).reindex(w.index).ffill()
        class_w.append(w.mul(scale, axis=0))
    w_all = pd.concat(class_w, axis=1).fillna(0.0) / len(class_w)
    return run_weights(w_all, excess[w_all.columns], ETF_COST, ETF_BORROW)


# ---------------------------------------------------------------------------
# Round 2 (PLAN_ADDENDUM_1.md)
# ---------------------------------------------------------------------------
def broad_universe(end=None) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Excess returns of the ETFs, the G10 currencies and the constructed 10-year bonds,
    with per-instrument one-way cost and short borrow."""
    rf = panel.risk_free(end)
    etf = panel.etf_returns(end).sub(rf, axis=0)
    fx = fx_excess(end).add_prefix("FX_")
    bonds = bond_excess(end).add_prefix("BOND_")
    excess = pd.concat([etf, fx, bonds], axis=1)
    cost = pd.Series(FX_COST, index=excess.columns)
    cost[etf.columns] = ETF_COST
    borrow = pd.Series(0.0, index=excess.columns)
    borrow[etf.columns] = ETF_BORROW
    return excess, cost, borrow


def _tsmom_on(excess: pd.DataFrame, signal: pd.DataFrame, cost, borrow,
              target_vol: float = 0.40, com: int = 60) -> pd.DataFrame:
    vol = ewma_vol(excess, com)
    raw = signal * target_vol / vol
    me = month_ends(excess.index)
    targets = raw.loc[me]
    n = targets.notna().sum(axis=1).replace(0, np.nan)
    targets = targets.div(n, axis=0).fillna(0.0)
    return run_weights(hold_monthly(targets, excess.index), excess, cost, borrow)


def trailing(excess: pd.DataFrame, n: int) -> pd.DataFrame:
    return np.exp(np.log1p(excess).rolling(n, min_periods=n).sum()) - 1


def tsmom_broad(end=None) -> pd.DataFrame:
    excess, cost, borrow = broad_universe(end)
    return _tsmom_on(excess, np.sign(trailing(excess, 252)), cost, borrow)


def tsmom_broad_multi(end=None) -> pd.DataFrame:
    excess, cost, borrow = broad_universe(end)
    sig = (np.sign(trailing(excess, 21)) + np.sign(trailing(excess, 63)) + np.sign(trailing(excess, 252))) / 3
    sig = sig.where(trailing(excess, 252).notna())
    return _tsmom_on(excess, sig, cost, borrow)


def _rank_monthly_with_usd(score: pd.DataFrame, k: int = 3) -> pd.DataFrame:
    """Rank the nine foreign currencies plus USD (scored at zero) each month-end."""
    me = month_ends(score.index)
    rows = {}
    for d in me:
        s = score.loc[d]
        if s.isna().any():
            continue
        w = side_weights(pd.concat([s, pd.Series({"USD": 0.0})]), k)
        rows[d] = w.drop("USD")
    return hold_monthly(pd.DataFrame(rows).T, score.index)


def fx_momentum(end=None) -> pd.DataFrame:
    excess = fx_excess(end)
    w = _rank_monthly_with_usd(trailing(excess, 21))
    return run_weights(w, excess, FX_COST)


def fx_value(end=None) -> pd.DataFrame:
    excess = fx_excess(end)
    spot = panel.fx_spot_long(end)
    prices = panel.cpi(end)
    real = np.log(spot) + np.log(prices[spot.columns]).sub(np.log(prices["USD"]), axis=0)
    five_years_ago = real.shift(1260)
    value = -(real - five_years_ago)          # a real depreciation over five years reads as cheap
    w = _rank_monthly_with_usd(value.reindex(excess.index))
    return run_weights(w, excess, FX_COST)


def _bond_cross_section(score: pd.DataFrame, excess: pd.DataFrame, k: int = 3) -> pd.DataFrame:
    vol = excess.rolling(252, min_periods=126).std() * np.sqrt(252)
    me = month_ends(excess.index)
    rows = {}
    for d in me:
        c = score.loc[d].where(vol.loc[d].notna())
        if c.notna().sum() < 2 * k:
            continue
        s = side_weights(c, k)
        inv = (1.0 / vol.loc[d]).where(s != 0, 0.0).fillna(0.0)
        w = pd.Series(0.0, index=c.index)
        for sign in (1, -1):
            side = s[np.sign(s) == sign].index
            if len(side):
                w[side] = sign * inv[side] / inv[side].sum()
        rows[d] = w
    return run_weights(hold_monthly(pd.DataFrame(rows).T, excess.index), excess, FX_COST)


def bond_momentum(end=None) -> pd.DataFrame:
    excess = bond_excess(end)
    score = trailing(excess, 231).shift(21)     # 12 months skipping the latest one
    return _bond_cross_section(score, excess)


def bond_value(end=None) -> pd.DataFrame:
    excess = bond_excess(end)
    y = panel.yields10(end)
    score = y - y.shift(1260)                   # a bigger five-year rise in yield reads as cheap
    return _bond_cross_section(score, excess)


def turn_of_month(end=None) -> pd.DataFrame:
    """Hold SPY over the last session of each month and the first three of the next.
    held[t] = 1 means the position is on over session t (bought at the close of t-1)."""
    rf = panel.risk_free(end)
    spy = panel.etf_returns(end)["SPY"] - rf
    idx = spy.index
    ym = pd.Series(idx.year * 12 + idx.month, index=idx)
    pos_in_month = ym.groupby(ym).cumcount() + 1                           # 1, 2, 3, ...
    from_end = ym.groupby(ym).cumcount(ascending=False) + 1                # ..., 2, 1
    held = ((pos_in_month <= 3) | (from_end == 1)).astype(float)
    held.iloc[:1] = 0.0
    trade = (held.shift(-1).fillna(0.0) - held).abs()                     # executed at the close of t
    net = held * spy.fillna(0.0) - trade * ETF_COST
    return pd.DataFrame({"net": net, "gross": held * spy.fillna(0.0), "cost": trade * ETF_COST,
                         "gross_exposure": held})


# ---------------------------------------------------------------------------
# Round 3 (PLAN_ADDENDUM_2.md): overnight versus intraday, S&P 500 members
# ---------------------------------------------------------------------------
AUCTION_COST = 2e-4    # one-way, every entry and every exit


def half_session_returns(end=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Overnight (previous close to open) and intraday (open to close) returns.

    Data rules, fixed before any round-3 result was computed:
      * a day whose open equals the previous close, or equals that day's close, EXACTLY
        cannot be split into two halves (yfinance fills missing opens this way; SW, FERG
        and AMCR carry synthetic pre-listing history where every open equals the close),
        so both halves are treated as missing that day;
      * a half-session move beyond -40%/+60% is treated as a bad print.
    """
    o, c = panel.stock_open_close(end)
    prev = c.shift(1)
    split = ~(((o - prev).abs() < 1e-9) | ((o - c).abs() < 1e-9))
    overnight = (o / prev - 1).where(split)
    intraday = (c / o - 1).where(split)
    bad = lambda r: r.where((r > -0.4) & (r < 0.6))
    return bad(overnight), bad(intraday)


def _decile_weights(score: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    me = month_ends(score.index)
    rows = {}
    for d in me:
        s = score.loc[d].where(eligible.loc[d]).dropna()
        n = len(s) // 10
        if n < 5:
            continue
        ranked = s.sort_values()
        w = pd.Series(0.0, index=score.columns)
        w[ranked.index[-n:]] = 1.0 / n
        w[ranked.index[:n]] = -1.0 / n
        rows[d] = w
    return hold_monthly(pd.DataFrame(rows).T, score.index).fillna(0.0)


def _half_session_sleeve(score_on: str, hold_on: str, direction: float, end=None,
                         cost: float = AUCTION_COST) -> pd.DataFrame:
    overnight, intraday = half_session_returns(end)
    o, c = panel.stock_open_close(end)
    score_src = overnight if score_on == "overnight" else intraday
    score = np.exp(np.log1p(score_src).rolling(21, min_periods=15).sum()) - 1   # >= 15 of 21 valid
    eligible = c.notna().rolling(252, min_periods=252).sum().ge(252)
    formed = direction * _decile_weights(score, eligible)
    if hold_on == "overnight":
        held = formed.shift(2).fillna(0.0)     # formed at close d, bought at the close of d+1
        rets = overnight
        days = pd.Series(held.index, index=held.index).diff().dt.days.fillna(1)
        borrow = held.clip(upper=0).abs().sum(axis=1) * ETF_BORROW * days / 365.0
    else:
        held = formed.shift(1).fillna(0.0)     # formed at close d, bought at the open of d+1
        rets = intraday
        borrow = pd.Series(0.0, index=held.index)
    gross = (held * rets.fillna(0.0)).sum(axis=1)
    exposure = held.abs().sum(axis=1)
    trading = exposure * 2 * cost              # in at one auction, out at the next, every session
    net = gross - trading - borrow
    return pd.DataFrame({"net": net, "gross": gross, "cost": trading + borrow, "gross_exposure": exposure})


def overnight_persistence(end=None, cost: float = AUCTION_COST) -> pd.DataFrame:
    return _half_session_sleeve("overnight", "overnight", 1.0, end, cost)


def intraday_persistence(end=None, cost: float = AUCTION_COST) -> pd.DataFrame:
    return _half_session_sleeve("intraday", "intraday", 1.0, end, cost)


def overnight_intraday_reversal(end=None, cost: float = AUCTION_COST) -> pd.DataFrame:
    return _half_session_sleeve("overnight", "intraday", -1.0, end, cost)


SLEEVES = {
    "tsmom": tsmom,
    "fx_carry": fx_carry,
    "dollar_carry": dollar_carry,
    "bond_carry": bond_carry,
    "vix_basis": vix_basis,
    "intraday_momentum": intraday_momentum,
    "xs_momentum": xs_momentum,
    # round 2
    "tsmom_broad": tsmom_broad,
    "tsmom_broad_multi": tsmom_broad_multi,
    "fx_momentum": fx_momentum,
    "fx_value": fx_value,
    "bond_momentum": bond_momentum,
    "bond_value": bond_value,
    "turn_of_month": turn_of_month,
    # round 3
    "overnight_persistence": overnight_persistence,
    "intraday_persistence": intraday_persistence,
    "overnight_intraday_reversal": overnight_intraday_reversal,
}
TSMOM_VARIANTS = ["tsmom", "tsmom_broad", "tsmom_broad_multi"]
