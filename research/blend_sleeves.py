"""Does combining the research sleeves beat any one of them?

Portfolio math, not a new signal search: k sleeves with Sharpe s and average
pairwise correlation rho reach s*sqrt(k / (1 + (k-1)*rho)). Diversification is
the only lever that raises Sharpe without finding new edge, so it is worth
testing before any further searching -- and it costs no additional multiple
testing, because the sleeves already exist and the weighting rules below are
fixed in advance rather than fitted.

Two pre-declared rules, both on daily excess returns over French RF:
  all_sleeves    -- inverse-volatility weights over every primitive sleeve, no
                    selection whatsoever, so no selection bias can enter.
  positive_only  -- the same, restricted to sleeves whose SELECTION-window
                    (2021-2023) excess Sharpe is positive. The evaluation
                    window is never consulted to choose or weight anything.
Blend-of-blend candidates (momentum_reversal_blend, defensive_momentum_blend)
are excluded so their components are not double counted, and SPY_control is
held out as the benchmark.

Sleeve returns are combined after each sleeve has paid its own costs, which
overstates cost slightly: a real combined book would net offsetting trades.

Run: PYTHONPATH=. .venv/bin/python -m research.blend_sleeves
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.metrics import compute_metrics
from research.higher_sharpe import PERIODS, alpha_hac, cash_rates

ROOT = Path(__file__).resolve().parents[1]
SLEEVE_DIR = ROOT / 'reports/higher_sharpe'
OUT = ROOT / 'reports/sleeve_blend'
PRIMITIVES = ['residual_momentum', 'residual_reversal', 'low_beta_spread', 'low_vol_long',
              'low_vol_hedged', 'liquid_equal_weight', 'pead_sue_hedged', 'pead_reaction_confirmed']
BENCHMARK = 'SPY_control'
TRIALS_SO_FAR = 37  # 26 earlier configurations + 11 in higher_sharpe


def load(name, stress=False):
    path = SLEEVE_DIR / f"{name}{'_stress' if stress else ''}.csv"
    return pd.read_csv(path, index_col=0, parse_dates=True)['return']


def window(series, period):
    a, b = PERIODS[period]
    return series.loc[a:b]


def luck_threshold(n_days, trials):
    """Expected best annualized Sharpe from `trials` independent strategies that
    have no edge at all, measured over `n_days` (deflated-Sharpe approximation)."""
    from scipy.stats import norm
    se = np.sqrt(252 / n_days)
    g = 0.5772
    return se * ((1 - g) * norm.ppf(1 - 1 / trials) + g * norm.ppf(1 - 1 / (trials * np.e))), se


def stats(excess, market_excess):
    m = compute_metrics(excess, 0)
    out = {'annualized_return': m.annualized_return, 'annualized_std': m.annualized_std,
           'sharpe_ratio': m.sharpe_ratio, 'max_drawdown': m.max_drawdown}
    out.update(alpha_hac(excess, market_excess))
    return out


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    rf = cash_rates()
    sleeves = {n: load(n) for n in PRIMITIVES}
    stressed = {n: load(n, stress=True) for n in PRIMITIVES}
    bench = load(BENCHMARK)
    index = sorted(set.intersection(*(set(s.index) for s in sleeves.values())))
    index = pd.DatetimeIndex(index)
    rf = rf.reindex(index)
    if rf.isna().any():
        raise ValueError('missing risk-free data over the sleeve window')

    excess = pd.DataFrame({n: s.reindex(index) - rf for n, s in sleeves.items()})
    excess_stressed = pd.DataFrame({n: s.reindex(index) - rf for n, s in stressed.items()})
    market_excess = bench.reindex(index) - rf

    selection = excess.loc[PERIODS['selection'][0]:PERIODS['selection'][1]]
    sel_sharpe = {n: compute_metrics(selection[n], 0).sharpe_ratio for n in PRIMITIVES}
    corr = selection.corr()
    corr.to_csv(OUT / 'selection_correlations.csv')

    rules = {'all_sleeves': PRIMITIVES,
             'positive_only': [n for n in PRIMITIVES if sel_sharpe[n] > 0]}
    result = {'selection_sharpe': sel_sharpe,
              'mean_abs_pairwise_correlation': float(corr.where(~np.eye(len(corr), dtype=bool)).abs().stack().mean()),
              'blends': {}}

    for rule, members in rules.items():
        if not members:
            result['blends'][rule] = {'members': [], 'note': 'no sleeve qualified'}
            continue
        # Inverse-volatility weights from the SELECTION window only.
        vol = selection[members].std()
        weights = (1 / vol) / (1 / vol).sum()
        blend = (excess[members] * weights).sum(axis=1)
        blend_stressed = (excess_stressed[members] * weights).sum(axis=1)
        ev = blend.loc[PERIODS['evaluation'][0]:PERIODS['evaluation'][1]]
        ev_stressed = blend_stressed.loc[PERIODS['evaluation'][0]:PERIODS['evaluation'][1]]
        mk = market_excess.loc[ev.index]
        # Effective independent bets under the selection-window correlations.
        w = weights.to_numpy()
        c = corr.loc[members, members].to_numpy()
        n_eff = 1.0 / float(w @ c @ w) if float(w @ c @ w) > 0 else float('nan')
        result['blends'][rule] = {
            'members': members, 'weights': {k: round(float(v), 4) for k, v in weights.items()},
            'effective_independent_bets': round(n_eff, 2),
            'selection': stats(window(blend, 'selection'), market_excess.loc[window(blend, 'selection').index]),
            'evaluation': stats(ev, mk),
            'evaluation_stressed': stats(ev_stressed, mk),
        }
        pd.DataFrame({'excess_return': blend}).to_csv(OUT / f'{rule}.csv')

    ev_days = len(window(excess, 'evaluation'))
    threshold, se = luck_threshold(ev_days, TRIALS_SO_FAR)
    result['luck'] = {'evaluation_days': ev_days, 'sharpe_standard_error': round(float(se), 2),
                      'trials_so_far': TRIALS_SO_FAR, 'expected_best_sharpe_with_no_edge': round(float(threshold), 2)}
    result['benchmark_evaluation'] = stats(window(market_excess, 'evaluation'),
                                           window(market_excess, 'evaluation'))
    (OUT / 'results.json').write_text(json.dumps(result, indent=2))

    lines = ['# Do the sleeves combine into something better?', '',
             'Daily excess returns over French RF. Inverse-volatility weights fixed on 2021-2023 and applied',
             'unchanged to 2024-2025. No evaluation-window information selects or weights anything.', '',
             f"Any claim here has to clear luck: with {TRIALS_SO_FAR} strategies tried and only {ev_days} evaluation days,",
             f"the best of them averages Sharpe {threshold:.2f} with no edge at all (one Sharpe standard error is {se:.2f}).", '',
             '| Portfolio | Sleeves | Effective independent bets | Later Sharpe | Later return | Later vol | Later drawdown | Beta | Alpha HAC t | Stressed Sharpe |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for rule, blob in result['blends'].items():
        if not blob.get('members'):
            continue
        e, s = blob['evaluation'], blob['evaluation_stressed']
        lines.append(f"| {rule} | {len(blob['members'])} | {blob['effective_independent_bets']:.2f} | "
                     f"{e['sharpe_ratio']:.2f} | {e['annualized_return']:.2%} | {e['annualized_std']:.2%} | "
                     f"{e['max_drawdown']:.2%} | {e['beta']:.2f} | {e['alpha_hac_t']:.2f} | {s['sharpe_ratio']:.2f} |")
    b = result['benchmark_evaluation']
    lines.append(f"| {BENCHMARK} (benchmark) | 1 | 1.00 | {b['sharpe_ratio']:.2f} | {b['annualized_return']:.2%} | "
                 f"{b['annualized_std']:.2%} | {b['max_drawdown']:.2%} | 1.00 | — | — |")
    lines += ['', f"Mean absolute pairwise correlation across sleeves (selection window): "
                  f"{result['mean_abs_pairwise_correlation']:.2f}.",
              'Full matrix in `selection_correlations.csv`.', '',
              '## Limits', '',
              '- Sleeve returns are combined after each already paid its own costs; a real combined book would net',
              '  offsetting trades, so the blends are charged slightly too much.',
              '- The sleeves share one universe, one price source and one survivorship-biased constituent list, so',
              '  their independence is overstated relative to genuinely different strategies.',
              '- Inverse-volatility weighting is a fixed rule, not an optimization, but the sleeve DEFINITIONS were',
              '  still chosen by people who had seen this data.',
              '- No production deployment: this is sizing arithmetic over recorded research paths.', '',
              'Reproduce: `PYTHONPATH=. .venv/bin/python -m research.blend_sleeves`']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    return result


if __name__ == '__main__':
    r = main()
    for rule, blob in r['blends'].items():
        if blob.get('members'):
            print(rule, len(blob['members']), 'sleeves | later Sharpe',
                  round(blob['evaluation']['sharpe_ratio'], 2),
                  '| effective bets', blob['effective_independent_bets'])
    print('benchmark later Sharpe', round(r['benchmark_evaluation']['sharpe_ratio'], 2))
    print('luck threshold', r['luck'])
