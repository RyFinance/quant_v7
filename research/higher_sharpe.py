"""Fixed-hypothesis, fee-aware beta-controlled screen. Never deploys.

Run: OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m research.higher_sharpe
Snapshots input bytes and panels; subsequent runs reuse those exact inputs.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
import re
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.metrics import compute_metrics
from backtest.research import simulate_weights, ledger_mark_to_market, block_sharpe_difference
from research.compare_strategies import event_targets, summarize

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/higher_sharpe'
PERIODS = {'discovery': ('2016-01-04', '2020-12-31'),
           'selection': ('2021-01-01', '2023-12-31'),
           'evaluation': ('2024-01-01', '2025-06-27')}


def inputs(refresh=False):
    """Frozen snapshot of every input, so a rerun reproduces byte for byte.
    The snapshot pins upstream files that DO change (the replay ledger this
    report benchmarks against), so a stale snapshot would silently keep
    reporting an old baseline: the current hashes are compared on every run and
    a drift is reported. Pass refresh=True to re-snapshot deliberately.
    """
    folder = OUT / 'inputs'
    folder.mkdir(parents=True, exist_ok=True)
    if refresh:
        (folder / 'manifest.json').unlink(missing_ok=True)
    if not (folder / 'manifest.json').exists():
        all_panels, hashes = {}, {}
        paths = sorted((ROOT / 'data/raw').glob('*.parquet')) + [ROOT / 'data/raw_legacy/SPY.parquet']
        for path in paths:
            raw = path.read_bytes()
            hashes[str(path.relative_to(ROOT))] = hashlib.sha256(raw).hexdigest()
            d = pd.read_parquet(BytesIO(raw)).set_index('timestamp').sort_index()
            d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
            if d.index.has_duplicates:
                raise ValueError(f'duplicate dates: {path}')
            all_panels[path.stem] = d.loc[:'2025-06-27']
        for col in ['open', 'close', 'volume']:
            pd.DataFrame({t: d[col] for t, d in all_panels.items()}).sort_index().to_parquet(folder / f'{col}.parquet')
        for source, dest in [('data/pead_signal_expanded.parquet', 'events.parquet'),
                             ('live_backtest/state/sweep_wide_5p0_ledger.jsonl', 'wide_ledger.jsonl'),
                             ('live_backtest/state/sweep_wide_5p0_cycle_log.jsonl', 'wide_cycles.jsonl')]:
            raw = (ROOT / source).read_bytes()
            hashes[source] = hashlib.sha256(raw).hexdigest()
            (folder / dest).write_bytes(raw)
        (folder / 'manifest.json').write_text(json.dumps(hashes, indent=2))
    else:
        manifest = json.loads((folder / 'manifest.json').read_text())
        for source in ['data/pead_signal_expanded.parquet', 'live_backtest/state/sweep_wide_5p0_ledger.jsonl',
                       'live_backtest/state/sweep_wide_5p0_cycle_log.jsonl']:
            path = ROOT / source
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get(source):
                print(f'WARNING: {source} changed since the snapshot; results use the FROZEN copy. '
                      f'Rerun inputs(refresh=True) to adopt the new one.', flush=True)
    return ({c: pd.read_parquet(folder / f'{c}.parquet') for c in ['open', 'close', 'volume']},
            pd.read_parquet(folder / 'events.parquet'))


def cash_rates():
    url = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip'
    path = OUT / 'inputs/french_daily.zip'
    if not path.exists():
        path.write_bytes(urllib.request.urlopen(url, timeout=30).read())
    with zipfile.ZipFile(path) as z:
        text = z.read(z.namelist()[0]).decode()
    rows = [s.split(',') for s in text.splitlines() if re.match(r'^\d{8},', s)]
    return pd.Series([float(r[-1]) / 100 for r in rows],
                     index=pd.to_datetime([r[0] for r in rows], format='%Y%m%d'), name='RF')


def scheduled(dates, period):
    labels = pd.Series(dates.to_period(period), index=dates)
    return labels.ne(labels.shift())


GROSS_CAP = .60
STOCK_CAP = .10
VOL_TARGET = .05


def add_beta_hedge(target, beta, gross_cap=GROSS_CAP):
    """Hedge estimated dollar beta at each decision; include ETF in gross cap.
    Monthly/weekly decisions remain such: NaN rows mean retain holdings.
    The cap is shared with simulate_weights via GROSS_CAP so the hedge and the
    simulator can never drift apart.
    """
    out = target.copy()
    for date in out.index[out.notna().any(axis=1)]:
        w = out.loc[date].fillna(0)
        valid = beta.loc[date].notna()
        w.loc[~valid] = 0
        w['SPY'] = 0
        w['SPY'] = -float((w * beta.loc[date].fillna(0)).sum())
        gross = w.abs().sum()
        if gross > gross_cap:
            w *= gross_cap / gross
        out.loc[date] = w
    return out


def build_targets(prices, events):
    close, volume = prices['close'], prices['volume']
    returns = close.pct_change(fill_method=None)
    market = returns.SPY
    beta = returns.rolling(126, min_periods=100).cov(market).div(market.rolling(126, min_periods=100).var(), axis=0)
    beta['SPY'] = 1.0
    # Betas for each daily residual use estimates available at the prior close.
    residual = returns - beta.shift().mul(market, axis=0)
    momentum = residual.rolling(231, min_periods=231).sum().shift(21)
    reversal = -residual.rolling(5).sum()
    volatility = returns.rolling(63).std()
    adv = (close * volume).rolling(63).mean()
    eligible = close.shift(252).notna() & close.notna() & (close > 5) & (adv > 10_000_000)
    eligible['SPY'] = False
    # Top 150 liquidity ranks are recomputed with information available then.
    liquid = adv.where(eligible).rank(axis=1, ascending=False, method='first') <= 150
    targets = {}
    for name, score, period, kind in [
        ('residual_momentum', momentum, 'M', 'long_short'),
        ('residual_reversal', reversal, 'W', 'long_short'),
        ('low_beta_spread', -beta, 'M', 'bab'),
        ('low_vol_long', -volatility, 'M', 'long'),
        ('liquid_equal_weight', adv * 0, 'M', 'equal'),
    ]:
        t = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        for date in close.index[scheduled(close.index, period)]:
            s = score.loc[date].where(liquid.loc[date]).dropna().sort_values(kind='stable')
            t.loc[date] = 0.0
            if len(s) < 60:
                continue
            longs = s.index[-20:] if kind != 'equal' else s.index
            if kind in ('long', 'equal'):
                t.loc[date, longs] = GROSS_CAP / len(longs)
            else:
                shorts = s.index[:20]
                if kind == 'bab':
                    bl = max(.2, float(beta.loc[date, longs].mean()))
                    bs = max(.2, float(beta.loc[date, shorts].mean()))
                    wl, ws = 1 / bl, 1 / bs
                    t.loc[date, longs] = GROSS_CAP * wl / (wl + ws) / len(longs)
                    t.loc[date, shorts] = -GROSS_CAP * ws / (wl + ws) / len(shorts)
                else:
                    t.loc[date, longs] = GROSS_CAP / 2 / len(longs)
                    t.loc[date, shorts] = -GROSS_CAP / 2 / len(shorts)
        targets[name] = t
    # All three spreads hedged for remaining estimated market beta.
    for name in ['residual_momentum', 'residual_reversal', 'low_beta_spread']:
        targets[name] = add_beta_hedge(targets[name], beta)
    targets['low_vol_hedged'] = add_beta_hedge(targets['low_vol_long'], beta)
    # Fixed diversification; no correlation-optimized weights fitted to returns.
    blend = .5 * targets['residual_momentum'].ffill().fillna(0) + .5 * targets['residual_reversal'].ffill().fillna(0)
    blend.loc[~scheduled(close.index, 'W')] = np.nan
    targets['momentum_reversal_blend'] = blend
    # PEAD controls on the SAME historically selected liquidity pool.
    events = events.copy()
    events['date'] = pd.to_datetime(events.date)
    events = events[[t in liquid and d in liquid.index and liquid.loc[d, t]
                     for d, t in zip(events.date, events.ticker)]]
    raw = event_targets(close, events, hold=20)
    targets['pead_sue_hedged'] = add_beta_hedge(raw, beta)
    # Reaction-confirmed surprise: predeclared 1-sigma reaction at the event
    # close, direction must agree with SUE. Execute the NEXT session open.
    reaction_z = residual.div(volatility.shift())
    confirmed = events[[np.isfinite(reaction_z.loc[e.date, e.ticker]) and
                        np.sign(reaction_z.loc[e.date, e.ticker]) == np.sign(e.signal) and
                        abs(reaction_z.loc[e.date, e.ticker]) >= 1 for e in events.itertuples()]]
    targets['pead_reaction_confirmed'] = add_beta_hedge(event_targets(close, confirmed, hold=20), beta)
    # Mix a defensive long sleeve with the beta-controlled momentum sleeve.
    mix = .5 * targets['low_vol_long'].ffill().fillna(0) + .5 * targets['residual_momentum'].ffill().fillna(0)
    mix.loc[~scheduled(close.index, 'M')] = np.nan
    targets['defensive_momentum_blend'] = mix
    spy = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    spy.loc[scheduled(close.index, 'M')] = 0
    spy.loc[scheduled(close.index, 'M'), 'SPY'] = GROSS_CAP
    targets['SPY_control'] = spy
    return targets


def alpha_hac(returns, market, lag=20):
    """OLS intercept with Newey-West/Bartlett HAC errors, zero cash rate.
    Market control is SPY total return; no industry/style factor controls.
    """
    d = pd.concat([returns, market], axis=1).dropna().to_numpy()
    y, x = d[:, 0], np.column_stack([np.ones(len(d)), d[:, 1]])
    inv = np.linalg.inv(np.einsum('ni,nj->ij', x, x))
    coef = np.einsum('ij,jn,n->i', inv, x.T, y)
    u = (y - np.einsum('ni,i->n', x, coef))[:, None] * x
    meat = np.einsum('ni,nj->ij', u, u)
    for k in range(1, min(lag + 1, len(y))):
        v = np.einsum('ni,nj->ij', u[k:], u[:-k])
        meat += (1 - k / (lag + 1)) * (v + v.T)
    se = np.sqrt(max(0, np.einsum('ij,jk,kl->il', inv, meat, inv)[0, 0]))
    return {'beta': float(coef[1]), 'alpha_annual': float(coef[0] * 252),
            'alpha_hac_t': float(coef[0] / se) if se > 0 else 0.0}


def stats(frame, market, rf):
    r = frame['return']
    risk_free = rf.reindex(r.index)
    if risk_free.isna().any():
        raise ValueError('missing risk-free data')
    excess = r - risk_free
    excess_metrics = compute_metrics(excess, 0)
    m = summarize(frame)
    m['return_vol_ratio'] = m['sharpe_ratio']
    m['sharpe_ratio'] = excess_metrics.sharpe_ratio
    m['sortino_ratio'] = excess_metrics.sortino_ratio
    m['annualized_excess_mean'] = float(excess.mean() * 252)
    return {**m, **alpha_hac(excess, market - rf)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    prices, events = inputs()
    rf = cash_rates()
    targets = build_targets(prices, events)
    specs = {'candidates': list(targets), 'periods': PERIODS, 'execution': 'close decision; next open fill; daily MTM',
        'stock_universe': 'current cached constituents, historically ranked top150 trailing63-day ADV; 252day history; price>5; ADV>$10m',
        'hypotheses': 'residual momentum; residual reversal; low beta; defensive low vol; beta hedged PEAD; reaction confirmation; fixed 50/50 blends',
        'gross_cap': GROSS_CAP, 'stock_cap': STOCK_CAP, 'SPY_hedge_cap': GROSS_CAP, 'vol_target': VOL_TARGET,
        'base_round_trip_bps': 10, 'stress_round_trip_bps': 25, 'base_borrow': .03, 'stress_borrow': .10,
        'cash_yield_and_risk_free': 'French daily RF (1-month Tbill); free cash only; no short collateral rebate',
        'cash_data_sha256': hashlib.sha256((OUT/'inputs/french_daily.zip').read_bytes()).hexdigest(),
        'initialization': 'start flat, enter last target known strictly before first simulated open',
        'selection': 'highest 2021-2023 excess-return Sharpe, 2024-2025 only for later evaluation',
        'gate': 'later excess Sharpe >=1, positive later excess mean at 25bps AND 10% borrow, paired later excess Sharpe advantage CI vs wide PEAD excludes zero',
        'limitations': ['11 additional candidate/control definitions after earlier 26 configurations; exploratory multiple testing, no pristine holdout.',
            'Current constituent survivorship persists despite causal liquidity ranking.',
            'Hedges reduce estimated beta but neither guarantee zero beta nor neutralize sector/style factors.',
            'Historical data and revised earnings estimates are not independently vendor verified.',
            'All positions paper/research. No borrow availability, locate fees, tax or market impact model.',
            'Cash assumes a Treasury-bill-like return on free cash. Actual broker interest may be lower; short collateral earns no rebate.',
            'Adjusted Yahoo OHLC are total-return proxies, not literal historical trade prices. Adjusted-price ADV is not point-in-time unadjusted dollar volume.',
            'Sizing constraints only: production risk gates/circuit breaker are not replayed for these candidates.']}
    (OUT / 'specification.json').write_text(json.dumps(specs, indent=2))
    close = prices['close']
    market = close.SPY.pct_change(fill_method=None)
    cap = pd.Series(STOCK_CAP, index=close.columns); cap['SPY'] = GROSS_CAP
    records = [json.loads(x) for x in (OUT/'inputs/wide_ledger.jsonl').read_text().splitlines()]
    cycles = [json.loads(x) for x in (OUT/'inputs/wide_cycles.jsonl').read_text().splitlines()]
    dates = pd.DatetimeIndex([pd.Timestamp(r['as_of_date']) for r in cycles])
    baseline = ledger_mark_to_market(records, close, dates, cash_returns=rf)
    baseline.to_csv(OUT / 'wide_pead_mtm.csv')
    result = {'wide_pead': stats(baseline, market, rf),
              'wide_pead_evaluation': stats(baseline.loc['2024':], market, rf), 'strategies': {}}
    paths, stresses = {}, {}
    for name, target in targets.items():
        base = simulate_weights(prices['open'], close, target, '2016-01-04', '2025-06-27',
                                target_vol=VOL_TARGET, position_cap=cap, cash_returns=rf)
        stress = simulate_weights(prices['open'], close, target, '2016-01-04', '2025-06-27',
                                  target_vol=VOL_TARGET, position_cap=cap, cost_bps=25, borrow_rate=.10, cash_returns=rf)
        paths[name], stresses[name] = base, stress
        base.to_csv(OUT / f'{name}.csv')
        stress.to_csv(OUT / f'{name}_stress.csv')
        result['strategies'][name] = {p: stats(base.loc[a:b], market, rf) for p, (a,b) in PERIODS.items()}
        result['strategies'][name]['common_pead_window'] = stats(base.loc[dates[0]:dates[-1]], market, rf)
        result['strategies'][name]['evaluation_stressed'] = stats(stress.loc['2024':], market, rf)
        result['strategies'][name]['full_stressed'] = stats(stress, market, rf)
        print(name, 'selection', result['strategies'][name]['selection']['sharpe_ratio'],
              'evaluation', result['strategies'][name]['evaluation']['sharpe_ratio'], flush=True)
    selected = max((n for n in paths if n != 'SPY_control'),
                   key=lambda n: result['strategies'][n]['selection']['sharpe_ratio'])
    r = result['strategies'][selected]
    ci = block_sharpe_difference(paths[selected].loc['2024':, 'return'] - rf,
                                baseline['return'] - rf, block=63)
    result['selection'] = {'name': selected, 'evaluation_delta_sharpe_ci_95': ci,
        'passes_research_gate': bool(r['evaluation']['sharpe_ratio'] >= 1 and
                                    r['evaluation_stressed']['annualized_excess_mean'] > 0 and ci['lower_95'] > 0)}
    (OUT / 'results.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    lines = ['# Higher-Sharpe, fee-aware research', '',
             'Frozen cache; next-open fills; daily mark-to-market; 5% ex-ante volatility target; 60% gross exposure cap. Sharpe uses excess returns over French daily RF; free cash earns RF, short collateral earns nothing.', '',
             'Base: 10 bps round trip + 3% annual short borrow. Stress: 25 bps + 10% borrow. All numbers below are on 2024-01-02 through 2025-06-27, after selection on 2021–2023.', '',
             '| Strategy | Selection Sharpe | Later CAGR | Later volatility | Later Sharpe | Later drawdown | Beta | Alpha HAC t | Stress CAGR |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    b = result['wide_pead_evaluation']
    lines.append(f"| Wide PEAD recorded schedule | — | {b['annualized_return']:.2%} | {b['annualized_std']:.2%} | {b['sharpe_ratio']:.2f} | {b['max_drawdown']:.2%} | {b['beta']:.2f} | {b['alpha_hac_t']:.2f} | — |")
    for n, r in result['strategies'].items():
        e = r['evaluation']
        lines.append(f"| {n} | {r['selection']['sharpe_ratio']:.2f} | {e['annualized_return']:.2%} | {e['annualized_std']:.2%} | {e['sharpe_ratio']:.2f} | {e['max_drawdown']:.2%} | {e['beta']:.2f} | {e['alpha_hac_t']:.2f} | {r['evaluation_stressed']['annualized_return']:.2%} |")
    lines += ['', 'Selection result (63-day paired block bootstrap; unadjusted for multiple tests):', '',
              '```json', json.dumps(result['selection'], indent=2), '```', '',
              '## Limits', '', *['- '+s for s in specs['limitations']], '',
              'Wide PEAD accounting preserves recorded share quantities and decision schedule, charging reconstructed trading costs and borrow once and crediting free cash interest. It is an accounting audit, not a rerun of gates using marked equity. Recorded fills are same-day closes; candidate fills are next opens, so relative results are not a controlled signal-only experiment.', '',
              'Cash-rate source: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html (daily three-factor file RF column; downloaded snapshot hash in specification).', '',
              'Reproduce: `python3 -m research.higher_sharpe`. Frozen inputs, source hashes, complete earlier-window results, stressed paths and CSVs are saved beside this report.']
    (OUT / 'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    main()
