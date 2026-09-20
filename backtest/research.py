"""Offline research accounting: close decisions, next-open fills, daily MTM.

Signals are weights known at each close. They may be NaN for 'hold'.
Costs are per dollar actually traded; cash earns zero; short borrow is
charged daily. No production imports, network calls or state writes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def simulate_weights(opens, closes, targets, start, end, cost_bps=10.0,
                     target_vol=None, gross_cap=0.60, position_cap=0.10,
                     borrow_rate=0.03, cash_returns=None):
    """10 bps round trip = 5 bps per side. Position limits at execution;
    subsequent market drift is allowed until the next rebalance. Target
    volatility uses 63 trailing close returns available before execution.
    Returns are close-to-close, including overnight P&L on old positions.
    Missing execution/valuation prices for held positions fail loudly.
    """
    if not opens.index.equals(closes.index) or not opens.columns.equals(closes.columns):
        raise ValueError('open and close panels must align')
    targets = targets.reindex(index=closes.index, columns=closes.columns)
    if isinstance(position_cap, pd.Series):
        position_cap = position_cap.reindex(closes.columns).to_numpy(float)
        if not np.isfinite(position_cap).all() or (position_cap <= 0).any():
            raise ValueError('position caps must be positive and supplied for every asset')
    returns = closes.pct_change(fill_method=None)
    shares = np.zeros(len(closes.columns))
    cash = previous_nav = 1.0
    previous_short_value = 0.0
    rates = pd.Series(0.0, index=closes.index) if cash_returns is None else cash_returns.reindex(closes.index)
    rows = []
    for i, date in enumerate(closes.index):
        if date < pd.Timestamp(start) or date > pd.Timestamp(end):
            continue
        if not np.isfinite(rates.loc[date]):
            raise ValueError(f'missing cash rate on {date}')
        # No interest rebate on short-sale collateral; only free cash earns.
        cash += max(0.0, cash - previous_short_value) * rates.loc[date]
        op = opens.iloc[i].to_numpy(float)
        cp = closes.iloc[i].to_numpy(float)
        held = shares != 0
        if np.any(held & (~np.isfinite(op) | ~np.isfinite(cp) | (op <= 0) | (cp <= 0))):
            raise ValueError(f'missing/nonpositive held price on {date}')
        old_value = shares * np.nan_to_num(op)
        nav_open = cash + old_value.sum()
        if nav_open <= 0:
            raise ValueError('portfolio insolvent')
        traded = 0.0
        decision = targets.iloc[i - 1] if i > 0 else pd.Series(dtype=float)
        if not rows and i > 0:
            # Initialize every strategy from its last known target, avoiding
            # artificial cash waiting for monthly strategies at a midmonth start.
            prior = targets.iloc[:i].dropna(how='all')
            if len(prior):
                decision = prior.iloc[-1]
        if i > 0 and decision.notna().any():
            w = decision.fillna(0).to_numpy(float)
            if not np.isfinite(w).all():
                raise ValueError('weights must be finite')
            # Missing current open prevents a NEW fill, without consulting
            # the current close or any later data when making the decision.
            w[~np.isfinite(op) | (op <= 0)] = 0
            if target_vol is not None:
                hist = returns.iloc[max(0, i - 63):i]
                active = np.abs(w) > 0
                if active.any():
                    observations = hist.iloc[:, active].dropna().to_numpy()
                    if not np.isfinite(observations).all():
                        raise ValueError('nonfinite historical return in volatility estimate')
                    # Elementwise reduction avoids spurious Accelerate BLAS
                    # floating-point warnings on some macOS NumPy builds.
                    path = np.sum(observations * w[active], axis=1)
                    vol = np.std(path, ddof=1) * np.sqrt(252) if len(path) >= 40 else np.nan
                    w *= min(1.0, target_vol / vol) if np.isfinite(vol) and vol > 0 else 0.0
            w = np.clip(w, -position_cap, position_cap)
            gross = np.abs(w).sum()
            if gross > gross_cap:
                w *= gross_cap / gross
            # Reserve costs before sizing so execution caps use post-cost NAV.
            post_cost_nav = nav_open
            for _ in range(12):
                desired = w * post_cost_nav
                fee = np.abs(desired - old_value).sum() * cost_bps / 20000
                post_cost_nav = nav_open - fee
            desired = w * post_cost_nav
            traded = np.abs(desired - old_value).sum()
            fee = traded * cost_bps / 20000
            cash -= (desired - old_value).sum() + fee
            shares = np.divide(desired, op, out=np.zeros_like(w), where=np.isfinite(op) & (op > 0))
        if np.any((shares != 0) & (~np.isfinite(cp) | (cp <= 0))):
            raise ValueError(f'missing new-position close on {date}')
        marked = shares * np.nan_to_num(cp)
        previous_short_value = np.abs(np.minimum(marked, 0)).sum()
        borrow = np.abs(np.minimum(marked, 0)).sum() * borrow_rate / 252
        cash -= borrow
        nav = cash + marked.sum()
        if nav <= 0:
            raise ValueError('portfolio insolvent')
        rows.append((date, nav / previous_nav - 1, nav,
                     np.abs(marked).sum() / nav, traded / nav_open, borrow / nav_open))
        previous_nav = nav
    out = pd.DataFrame(rows, columns=['date', 'return', 'nav', 'gross', 'turnover', 'borrow']).set_index('date')
    if len(out):
        # Liquidate at final close and include the exit cost in the final NAV.
        fee = np.abs(marked).sum() * cost_bps / 20000
        before = out['nav'].iloc[-2] if len(out) > 1 else 1.0
        out.iloc[-1, out.columns.get_loc('nav')] -= fee
        out.iloc[-1, out.columns.get_loc('return')] = (nav - fee) / before - 1
        out.iloc[-1, out.columns.get_loc('turnover')] += np.abs(marked).sum() / nav
    return out


def ledger_mark_to_market(records, closes, dates, cost_bps=10.0, borrow_rate=0.03,
                          starting_capital=100000.0, cash_returns=None):
    """Revalue the recorded trade schedule, preserving original notionals.
    This audits accounting; it does NOT re-run risk decisions with corrected
    equity. Long/short share cash flows reconcile to recorded realized P&L.
    """
    grouped = {}
    for r in records:
        date = pd.Timestamp(r['entry_date'] if r['event'] == 'open' else r['exit_date'])
        grouped.setdefault(date, []).append(r)
    cash = previous = starting_capital
    positions = {}
    rows = []
    previous_short_value = 0.0
    rates = pd.Series(0.0, index=dates) if cash_returns is None else cash_returns.reindex(dates)
    for date in dates:
        rate = rates.loc[date]
        if not np.isfinite(rate):
            raise ValueError(f'missing cash rate on {date}')
        cash += max(0.0, cash - previous_short_value) * rate
        traded = 0.0
        for r in grouped.get(date, []):
            ticker = r['ticker']
            if r['event'] == 'open':
                if ticker in positions:
                    raise ValueError('duplicate open')
                shares = r['notional'] / r['fill_price'] * (1 if r['direction'] == 'long' else -1)
                positions[ticker] = shares
                cash -= shares * r['fill_price']
                traded += r['notional']
            else:
                shares = positions.pop(ticker)
                cash += shares * r['exit_price']
                traded += abs(shares * r['exit_price'])
        cash -= traded * cost_bps / 20000
        values = np.array([qty * closes.loc[date, ticker] for ticker, qty in positions.items()])
        if not np.isfinite(values).all():
            raise ValueError(f'missing ledger valuation on {date}')
        previous_short_value = np.abs(np.minimum(values, 0)).sum()
        cash -= previous_short_value * borrow_rate / 252
        nav = cash + values.sum()
        rows.append((date, nav / previous - 1, nav, np.abs(values).sum() / nav))
        previous = nav
    return pd.DataFrame(rows, columns=['date', 'return', 'nav', 'gross']).set_index('date')


def block_sharpe_difference(a, b, samples=2000, block=20, seed=1709):
    """Paired circular moving-block bootstrap, preserves same-day dependence.
    Exploratory interval, not a multiple-testing-adjusted discovery test.
    """
    values = pd.concat([a, b], axis=1).dropna().to_numpy()
    rng = np.random.default_rng(seed)
    n = len(values)
    draws = []
    for _ in range(samples):
        idx = (rng.integers(n, size=int(np.ceil(n / block)))[:, None] + np.arange(block)) % n
        x = values[idx.ravel()[:n]]
        sd = x.std(axis=0, ddof=1)
        sr = np.divide(x.mean(axis=0) * np.sqrt(252), sd, out=np.zeros(2), where=sd > 0)
        draws.append(sr[0] - sr[1])
    return dict(zip(['lower_95', 'median', 'upper_95'], map(float, np.quantile(draws, [.025, .5, .975]))))
