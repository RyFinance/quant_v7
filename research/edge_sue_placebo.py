"""Decisive SUE placebo test: is the post-earnings drift SUE-driven at all?

Predeclared BEFORE running; specification.json freezes it with input hashes.
  H0 (null): the assignment of SUE values to events within a calendar date
  carries no information about forward returns; any signed drift is a
  generic post-earnings effect (or period effect) independent of SUE.
  H1: SUE sign and/or magnitude identify WHICH events drift.

  Buckets (descriptive): {SUE>0, SUE<0} x {|SUE|>=1, |SUE|<1}; mean raw
  next-open->20-session forward return and SPY-excess; per period.

  Placebo: permute the SUE value across events WITHIN each event date
  (preserves co-timing, each date's marginal SUE distribution, and every
  harness rule). 10,000 iterations for event-level statistics; 300
  iterations through the full portfolio harness (runtime-bound).

  Statistics:
    s1 signed mean position return  mean(sign(SUE)*raw_forward)
    s2 long-short spread            (mean(rf|SUE>0) - mean(rf|SUE<0))/2
    s3 magnitude-selected mean      mean(rf | |SUE|>=1)
    s4 harness Sharpe (full, confirmation) for pead_long_short and
       pead_large_sue_long under the same permutations.

  Verdict rule (fixed now): the SUE family is declared DEAD if BOTH the
  s2 long-short statistic and the s4 long-short harness Sharpe fall inside
  the central 95% of their placebo distributions (two-sided p > .05), and
  the s3 magnitude selection shows no significant excess (p > .05). On a
  dead verdict: no further SUE-filter variants; pivot signal families.
  A live edge requires the true statistic to sit in the placebo's extreme
  tail in the PREDICTED direction.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.edge_first_backtest import load_panel, simulate, metrics, PERIODS  # noqa: E402

OUT = ROOT / 'reports/edge_sue_placebo'
N_PERM_EVENT = 10_000
N_PERM_PORT = 300
SEED = 17092026
ARMS_UNDER_TEST = ['pead_long_short', 'pead_large_sue_long']
COST_BPS = 10.0


def within_date_permutations(signal: np.ndarray, codes: np.ndarray, n_iter: int, rng):
    """Yield SUE arrays with values permuted uniformly within each date."""
    order = np.argsort(codes, kind='stable')
    sig_sorted = signal[order]
    n = len(signal)
    for _ in range(n_iter):
        u = rng.random(n)
        pw = np.lexsort((u, codes[order]))
        shuffled_sorted = np.empty(n, dtype=signal.dtype)
        shuffled_sorted[pw] = sig_sorted
        out = np.empty(n, dtype=signal.dtype)
        out[order] = shuffled_sorted
        yield out


def main():
    OUT.mkdir(exist_ok=True)
    events = pd.read_parquet(ROOT / 'reports/edge_executable_probe/events.parquet')
    spec = {'n_perm_event': N_PERM_EVENT, 'n_perm_portfolio': N_PERM_PORT, 'seed': SEED,
            'arms_under_test': ARMS_UNDER_TEST, 'cost_bps': COST_BPS,
            'verdict_rule': 'DEAD if long-short stat and harness Sharpe both inside central 95% '
                            'of placebo (two-sided p>.05) and magnitude selection p>.05',
            'input_sha256': {'reports/edge_executable_probe/events.parquet':
                             hashlib.sha256((ROOT / 'reports/edge_executable_probe/events.parquet').read_bytes()).hexdigest()}}
    (OUT / 'specification.json').write_text(json.dumps(spec, indent=2))

    codes = pd.factorize(events.date)[0]
    sig = events.signal.to_numpy(dtype=float)
    rf = events.raw_forward.to_numpy()
    ex = events.spy_excess.to_numpy()
    big = np.abs(sig) >= 1
    up, dn = sig > 0, sig < 0
    true = {
        's1_signed_mean_bps': float(np.mean(np.sign(sig) * rf) * 1e4),
        's2_long_short_spread_bps': float((rf[up].mean() - rf[dn].mean()) / 2 * 1e4),
        's3_abs_sue_ge1_mean_bps': float(rf[big].mean() * 1e4),
        'n_up': int(up.sum()), 'n_down': int(dn.sum()), 'n_abs_ge1': int(big.sum()),
        's3_excess_vs_all_bps': float((rf[big].mean() - rf.mean()) * 1e4),
    }

    # ---- 4 buckets, descriptive, per period ----
    rows = []
    for p, (lo, hi) in PERIODS.items():
        m = (events.date >= lo) & (events.date <= hi)
        for su in [1, -1]:
            for mlabel in ['|SUE|>=1', '|SUE|<1']:
                mg = mlabel == '|SUE|>=1'
                sel = m & (np.sign(sig) == su) & (big == mg)
                if sel.sum():
                    rows.append({'period': p, 'bucket': f"{'+' if su > 0 else '-'}SUE & {mlabel}",
                                 'n': int(sel.sum()),
                                 'raw_forward_bps': float(rf[sel].mean() * 1e4),
                                 'spy_excess_bps': float(ex[sel].mean() * 1e4)})
    buckets = pd.DataFrame(rows)
    buckets.to_csv(OUT / 'buckets.csv', index=False)

    # ---- event-level placebo ----
    rng = np.random.default_rng(SEED)
    s1s, s2s, s3s = [], [], []
    for perm_sig in within_date_permutations(sig, codes, N_PERM_EVENT, rng):
        p_up, p_dn = perm_sig > 0, perm_sig < 0
        s1 = np.mean(np.sign(perm_sig) * rf)
        s2 = (rf[p_up].mean() - rf[p_dn].mean()) / 2
        s3 = rf[np.abs(perm_sig) >= 1].mean()
        s1s.append(s1); s2s.append(s2); s3s.append(s3)
    placebo = {'s1_bps': np.array(s1s) * 1e4, 's2_bps': np.array(s2s) * 1e4,
               's3_bps': np.array(s3s) * 1e4}

    def p_two(true_v, dist):
        return float(min((dist <= true_v).mean(), (dist >= true_v).mean()) * 2)

    event_p = {'s1_p': p_two(true['s1_signed_mean_bps'], placebo['s1_bps']),
               's2_p': p_two(true['s2_long_short_spread_bps'], placebo['s2_bps']),
               's3_p': p_two(true['s3_abs_sue_ge1_mean_bps'], placebo['s3_bps']),
               's1_placebo_mean_bps': float(placebo['s1_bps'].mean()),
               's2_placebo_ci_bps': [float(np.quantile(placebo['s2_bps'], .025)),
                                     float(np.quantile(placebo['s2_bps'], .975))],
               's3_placebo_ci_bps': [float(np.quantile(placebo['s3_bps'], .025)),
                                     float(np.quantile(placebo['s3_bps'], .975))]}

    # ---- portfolio-level placebo through the full harness ----
    calendar = pd.date_range('1999-01-01', periods=1)  # placeholder, replaced below
    spy = pd.read_parquet(ROOT / 'data/raw_legacy/SPY.parquet').set_index('timestamp').sort_index()
    spy.index = pd.to_datetime(spy.index).tz_localize(None).normalize()
    calendar = spy.index
    events = events.copy()
    events['entry_i'] = calendar.get_indexer(events.entry_date)
    tickers = sorted(events.ticker.unique())
    col = {t: j for j, t in enumerate(tickers)}
    print('loading price panel...', flush=True)
    opens, closes, ff = load_panel(tickers, calendar)

    arm_fns = {'pead_long_short': lambda s: 1 if s > 0 else (-1 if s < 0 else 0),
               'pead_large_sue_long': lambda s: 1 if s >= 1 else 0}
    port = {a: {'full_sharpe': [], 'conf_sharpe': []} for a in ARMS_UNDER_TEST}
    conf_lo, conf_hi = PERIODS['confirmation']
    for i, perm_sig in enumerate(within_date_permutations(sig, codes, N_PERM_PORT, rng)):
        ev = events.copy()
        ev['signal'] = perm_sig
        for arm in ARMS_UNDER_TEST:
            daily, *_ = simulate(arm_fns[arm], opens, ff, col, ev, COST_BPS)
            port[arm]['full_sharpe'].append(metrics(daily, calendar, calendar.min(), calendar.max())['sharpe'])
            port[arm]['conf_sharpe'].append(metrics(daily, calendar, conf_lo, conf_hi)['sharpe'])
        if (i + 1) % 50 == 0:
            print(f'portfolio placebo {i + 1}/{N_PERM_PORT}', flush=True)

    results = {'true_event_stats': true, 'event_placebo_p': event_p, 'buckets': rows,
               'portfolio_placebo': {}, 'portfolio_true': {}}
    for arm in ARMS_UNDER_TEST:
        f = np.array(port[arm]['full_sharpe'])
        c = np.array(port[arm]['conf_sharpe'])
        results['portfolio_placebo'][arm] = {
            'full_sharpe_ci95': [float(np.quantile(f, .025)), float(np.quantile(f, .975))],
            'conf_sharpe_ci95': [float(np.quantile(c, .025)), float(np.quantile(c, .975))]}
    daily_true = {}
    for arm in ARMS_UNDER_TEST:
        daily, *_ = simulate(arm_fns[arm], opens, ff, col, events, COST_BPS)
        results['portfolio_true'][arm] = {
            'full_sharpe': metrics(daily, calendar, calendar.min(), calendar.max())['sharpe'],
            'conf_sharpe': metrics(daily, calendar, conf_lo, conf_hi)['sharpe']}
    results['portfolio_p'] = {arm: {
        'full_p': p_two(results['portfolio_true'][arm]['full_sharpe'], np.array(port[arm]['full_sharpe'])),
        'conf_p': p_two(results['portfolio_true'][arm]['conf_sharpe'], np.array(port[arm]['conf_sharpe']))}
        for arm in ARMS_UNDER_TEST}

    def inside(true_v, ci):
        return ci[0] <= true_v <= ci[1]

    dead = (event_p['s2_p'] > .05
            and inside(results['portfolio_true']['pead_long_short']['full_sharpe'],
                       results['portfolio_placebo']['pead_long_short']['full_sharpe_ci95'])
            and event_p['s3_p'] > .05)
    results['verdict'] = {'sue_family_dead': bool(dead), 'rule': spec['verdict_rule']}
    (OUT / 'results.json').write_text(json.dumps(results, indent=2, default=float))
    print(buckets.to_string(index=False))
    print('TRUE:', json.dumps(true, indent=2))
    print('EVENT PLACEBO P:', event_p)
    for arm in ARMS_UNDER_TEST:
        print(arm, 'true full', round(results['portfolio_true'][arm]['full_sharpe'], 3),
              'placebo CI', [round(x, 3) for x in results['portfolio_placebo'][arm]['full_sharpe_ci95']],
              'true conf', round(results['portfolio_true'][arm]['conf_sharpe'], 3),
              'placebo CI', [round(x, 3) for x in results['portfolio_placebo'][arm]['conf_sharpe_ci95']])
    print('VERDICT sue_family_dead:', dead)


if __name__ == '__main__':
    main()
