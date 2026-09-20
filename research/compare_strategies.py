"""Reproducible OFFLINE strategy screen. Run: python3 -m research.compare_strategies

All candidate definitions are fixed before examining results. Selection uses
2021-08-11 through 2023 only; 2024-2025 is the later evaluation. These dates
have been studied by this repository already, so neither is a pristine
holdout. Current constituent survivorship remains in all cached stock data.
No research output here authorizes a production strategy change.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from backtest.metrics import compute_metrics
from backtest.research import simulate_weights, ledger_mark_to_market, block_sharpe_difference

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports' / 'strategy_research'
START, END = '2021-08-11', '2025-06-27'
TARGET_VOL = 0.05  # fixed round-number research target, NOT ex-post matched volatility


def load_prices(tickers):
    panels = {}
    fingerprints = {}
    for ticker in tickers:
        p = ROOT / 'data' / 'raw' / f'{ticker}.parquet'
        d = pd.read_parquet(p).set_index('timestamp').sort_index()
        d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
        if d.index.has_duplicates:
            raise ValueError(f'duplicate price date: {ticker}')
        panels[ticker] = d
        fingerprints[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return ({col: pd.DataFrame({t: d[col] for t, d in panels.items()}).sort_index()
             for col in ['open', 'close', 'volume']}, fingerprints)


def event_features(events, prices):
    """Same causal adjusted-price features in fit and score; adjusted-return label.
    Features use the effective-date close, and fills wait for the next open.
    Dollar-volume ranks are date-specific, never a 2026 static ranking.
    """
    close, op = prices['close'], prices['open']
    mom5 = close.pct_change(5, fill_method=None)
    mom20 = close.pct_change(20, fill_method=None)
    vol = close.pct_change(fill_method=None).rolling(63).std()
    adv = (close * prices['volume']).rolling(63).mean().rank(axis=1, pct=True)
    rows = []
    for e in events.itertuples():
        if e.ticker not in close or e.date not in close.index:
            continue
        i = close.index.get_loc(e.date)
        feat = [e.signal, abs(e.signal), np.clip(e.surprise_pct, -100, 100),
                mom5.loc[e.date, e.ticker], mom20.loc[e.date, e.ticker],
                vol.loc[e.date, e.ticker], adv.loc[e.date, e.ticker]]
        if not np.isfinite(feat).all():
            continue
        label, mature = np.nan, pd.NaT
        if i + 21 < len(op):
            entry, exit_ = op.iloc[i + 1][e.ticker], op.iloc[i + 21][e.ticker]
            if np.isfinite(entry) and np.isfinite(exit_) and entry > 0:
                realized = np.sign(e.signal) * (exit_ / entry - 1)
                label = int(realized > .001 + (.03 * 20 / 252 if e.signal < 0 else 0))
                mature = op.index[i + 21]
        rows.append([e.date, e.ticker, *feat, label, mature])
    return pd.DataFrame(rows, columns=['date', 'ticker', 'sue', 'abs_sue', 'surprise',
                                      'mom5', 'mom20', 'vol63', 'adv_rank', 'label', 'mature'])


def walkforward_probabilities(features):
    """One fixed regularized model, refit annually on matured prior labels.
    No cached production model, calibration tuning, or holdout fitting.
    """
    cols = ['sue', 'abs_sue', 'surprise', 'mom5', 'mom20', 'vol63', 'adv_rank']
    out, fits = [], []
    for year in range(2021, 2026):
        cutoff = pd.Timestamp(year=year, month=1, day=1)
        train = features[(features.mature < cutoff) & features.label.notna()]
        test = features[features.date.dt.year == year].copy()
        if len(train) < 200 or test.empty:
            continue
        model = HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=7,
                    min_samples_leaf=50, l2_regularization=10, learning_rate=.05,
                    early_stopping=False, random_state=1709)
        model.fit(train[cols], train.label.astype(int))
        test['probability'] = model.predict_proba(test[cols])[:, 1]
        out.append(test)
        fits.append({'year': year, 'train_events': len(train), 'test_events': len(test),
                     'latest_training_label_exit': str(train.mature.max().date())})
    return pd.concat(out, ignore_index=True), fits


def event_targets(close, events, hold=20, direction=1, long_only=False, threshold=1,
                  probability=None):
    """Fixed 5% target per qualifying event, max 12 simultaneous names.
    Holdings rebalance daily, expire after exactly hold observed sessions.
    This intentionally replaces Kelly with transparent research sizing.
    """
    targets = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    book = {}
    groups = {d: g for d, g in events.groupby('date')}
    for i, date in enumerate(close.index):
        book = {t: v for t, v in book.items() if v[0] > i}
        group = groups.get(date)
        if group is not None:
            sort_col = 'probability' if probability is not None else 'signal'
            group = group.assign(priority=group[sort_col].abs()).sort_values(['priority', 'ticker'], ascending=[False, True])
            for e in group.itertuples():
                if e.ticker not in close or e.ticker in book or len(book) >= 12:
                    continue
                if not np.isfinite(e.signal) or abs(e.signal) < threshold:
                    continue
                if probability is not None and e.probability < probability:
                    continue
                sign = np.sign(e.signal) * direction
                if sign == 0 or (long_only and sign < 0):
                    continue
                book[e.ticker] = (i + hold, .05 * sign)
        for t, (_, w) in book.items():
            targets.loc[date, t] = w
    return targets


def price_targets(prices):
    close = prices['close']
    daily = close.pct_change(fill_method=None)
    eligible = close.notna() & close.shift(252).notna()
    momentum = close.shift(21) / close.shift(252) - 1
    sma = close.rolling(200).mean()
    reversal = -close.pct_change(5, fill_method=None)
    lowvol = -daily.rolling(63).std()
    month = pd.Series(close.index.to_period('M'), index=close.index)
    # First-session close decisions avoid consulting future rows for a schedule.
    monthly = month.ne(month.shift())
    weekly = pd.Series(close.index.to_period('W'), index=close.index)
    weekly = weekly.ne(weekly.shift())
    result = {}
    for name, scores, trend, schedule in [
        ('equal_weight', None, False, monthly),
        ('trend_200d', None, True, monthly),
        ('momentum_12_1', momentum, False, monthly),
        ('momentum_trend', momentum, True, monthly),
        ('low_volatility', lowvol, False, monthly),
        ('reversal_5d', reversal, False, weekly),
    ]:
        t = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        for date in close.index[schedule]:
            mask = eligible.loc[date].copy()
            if trend:
                mask &= close.loc[date] > sma.loc[date]
            names = mask[mask].index
            if scores is not None:
                names = scores.loc[date, names].dropna().nlargest(15).index
            t.loc[date] = 0.0
            if len(names):
                t.loc[date, names] = min(.10, .60 / len(names))
        result[name] = t
    return result


def summarize(frame):
    m = asdict(compute_metrics(frame['return'], n_trades=0))
    m.pop('n_trades')  # weight adjustments are not round-trip trade counts
    m.pop('turnover_annualized')
    m['average_gross_exposure'] = float(frame.gross.mean())
    if 'turnover' in frame:
        m['one_way_turnover_annualized'] = float(frame.turnover.mean() * 252)
    return m


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tickers = (ROOT / 'reports/universe_selection.txt').read_text().splitlines()[1].split(',')
    prices, hashes = load_prices(tickers)
    close = prices['close']
    events = pd.read_parquet(ROOT / 'data/pead_signal_expanded.parquet')
    events = events[events.ticker.isin(tickers)].copy()
    events['date'] = pd.to_datetime(events.date)
    features = event_features(events, prices)
    scored, fits = walkforward_probabilities(features)
    scored = scored.rename(columns={'sue': 'signal'})
    targets = price_targets(prices)
    for hold in [10, 20, 40]:
        targets[f'pead_sue_{hold}d'] = event_targets(close, events, hold=hold)
    targets['pead_long_only'] = event_targets(close, events, long_only=True)
    targets['earnings_reversal'] = event_targets(close, events, direction=-1)
    targets['pead_causal_ml_55'] = event_targets(close, scored, threshold=0, probability=.55)
    targets['pead_causal_ml_65'] = event_targets(close, scored, threshold=0, probability=.65)

    # Persist the specification before running any candidate return simulation.
    spec = {'candidate_names': list(targets), 'start': START, 'end': END,
            'selection_end': '2023-12-29', 'later_evaluation_start': '2024-01-02',
            'gross_cap': .60, 'position_cap': .10, 'target_vol': TARGET_VOL,
            'cost_bps_round_trip': [10, 25], 'annual_short_borrow': .03,
            'cash_yield': 0, 'model_fits': fits, 'price_sha256': hashes,
            'limitations': [
                'Current 2026-selected 75-name universe has survivorship and selection bias.',
                'Historical Yahoo cache is not independently vendor-verified or point-in-time earnings-vintaged.',
                '2024-2025 was studied by previous repository experiments; not pristine out-of-sample.',
                'Research candidates use sizing caps but do not reproduce production circuit breaker/daily-loss/kill-switch policy.',
                'No stock loan availability, market impact, taxes, cash interest, or locate fees modeled.',
                'Annual ML refits use only prior matured labels, including earlier evaluation-year labels for later years.',
                '5% volatility target reduces exposure only, never adds leverage; not guaranteed realized volatility.',
                'Candidate screening is multiple testing; bootstrap intervals are descriptive, unadjusted.',
            ]}
    for rel in ['data/pead_signal_expanded.parquet', 'live_backtest/state/replay_ledger.jsonl',
                'live_backtest/state/replay_cycle_log.jsonl', 'reports/universe_selection.txt']:
        spec.setdefault('other_sha256', {})[rel] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
    (OUT / 'specification.json').write_text(json.dumps(spec, indent=2))
    logs = [json.loads(x) for x in (ROOT / 'live_backtest/state/replay_cycle_log.jsonl').read_text().splitlines()]
    ledger = [json.loads(x) for x in (ROOT / 'live_backtest/state/replay_ledger.jsonl').read_text().splitlines()]
    dates = pd.DatetimeIndex([pd.Timestamp(r['as_of_date']) for r in logs])
    calendar = close.index[(close.index >= START) & (close.index <= END)]
    if not dates.equals(calendar):
        raise ValueError('replay and market calendars differ')
    gross_ledger = ledger_mark_to_market(ledger, close, dates, cost_bps=0, borrow_rate=0)
    if not np.isclose(gross_ledger.nav.iloc[-1], logs[-1]['nav_after'], atol=.01):
        raise ValueError('ledger final equity does not reconcile (or open positions remain)')
    baseline = ledger_mark_to_market(ledger, close, dates)
    baseline.to_csv(OUT / 'current_pead_mark_to_market.csv')
    baseline_gross = summarize(gross_ledger)
    baseline_net = summarize(baseline)
    result = {'baseline_gross_mtm': baseline_gross, 'baseline_net_mtm': baseline_net,
              'candidates': {}, 'selected': {}}
    paths = {}
    for risk_mode, vol in [('caps_only', None), ('vol_5pct', TARGET_VOL)]:
        for name, target in targets.items():
            key = f'{name}__{risk_mode}'
            frame = simulate_weights(prices['open'], close, target, START, END, target_vol=vol)
            stress = simulate_weights(prices['open'], close, target, START, END, target_vol=vol, cost_bps=25)
            paths[key] = frame
            frame.to_csv(OUT / f'{key}.csv')
            selection = frame.loc[:'2023-12-31']
            later = frame.loc['2024-01-01':]
            result['candidates'][key] = {'full': summarize(frame),
                'selection_2021_2023': summarize(selection), 'later_2024_2025': summarize(later),
                'cost_25bps_full': summarize(stress),
                'yearly': {str(y): summarize(g) for y, g in frame.groupby(frame.index.year)}}
            print(key, result['candidates'][key]['full']['annualized_return'],
                  result['candidates'][key]['full']['sharpe_ratio'], flush=True)
        candidates = [k for k in paths if k.endswith(risk_mode)]
        selected = max(candidates, key=lambda k: result['candidates'][k]['selection_2021_2023']['sharpe_ratio'])
        later = paths[selected].loc['2024-01-01':, 'return']
        result['selected'][risk_mode] = {'name': selected,
            'later_sharpe_difference_vs_current_pead_ci': block_sharpe_difference(later, baseline['return'])}
    result['baseline_yearly'] = {str(y): summarize(g) for y, g in baseline.groupby(baseline.index.year)}
    result['baseline_selection'] = summarize(baseline.loc[:'2023-12-31'])
    result['baseline_later'] = summarize(baseline.loc['2024-01-01':])
    result['selected']['caps_only']['decision_including_current'] = (
        'Recorded close-filled baseline has higher selection Sharpe; no deployment inference from this execution-mismatched comparison'
        if result['baseline_selection']['sharpe_ratio'] >=
        result['candidates'][result['selected']['caps_only']['name']]['selection_2021_2023']['sharpe_ratio']
        else 'candidate has higher selection Sharpe; evaluate uncertainty before deployment')

    # Broad ETF benchmark avoids the 2026-picked individual-stock universe.
    spy_path = ROOT / 'data/raw_legacy/SPY.parquet'
    spy = pd.read_parquet(spy_path).set_index('timestamp').sort_index()
    spy.index = pd.to_datetime(spy.index).tz_localize(None).normalize()
    spy_open, spy_close = spy[['open']].rename(columns={'open': 'SPY'}), spy[['close']].rename(columns={'close': 'SPY'})
    spy_target = pd.DataFrame(np.nan, index=spy.index, columns=['SPY'])
    months = pd.Series(spy.index.to_period('M'), index=spy.index)
    spy_target.loc[months.ne(months.shift()), 'SPY'] = .60
    result['benchmarks'] = {}
    for mode, vol in [('caps_only', None), ('vol_5pct', TARGET_VOL)]:
        frame = simulate_weights(spy_open, spy_close, spy_target, START, END,
                                 target_vol=vol, position_cap=.60)
        result['benchmarks'][f'SPY_{mode}'] = summarize(frame)
        frame.to_csv(OUT / f'SPY_{mode}.csv')
    spec['other_sha256']['data/raw_legacy/SPY.parquet'] = hashlib.sha256(spy_path.read_bytes()).hexdigest()
    spec['benchmark_note'] = 'SPY holds up to 60% in one diversified ETF; individual-name 10% cap does not apply to this benchmark.'
    (OUT / 'specification.json').write_text(json.dumps(spec, indent=2))

    # Additional available price history after the common PEAD window, using
    # ONLY previously selected price candidates, no new parameter selection.
    result['post_pead_window'] = {}
    extension_panel = close.loc['2025-06-30':]
    missing_dates = extension_panel.index[extension_panel.isna().any(axis=1)]
    extension_end = close.index[-1]
    if len(missing_dates):
        extension_end = close.index[close.index.get_loc(missing_dates[0]) - 1]
    result['extension_data_quality'] = {'end': str(extension_end.date()),
        'first_missing_date': str(missing_dates[0].date()) if len(missing_dates) else None,
        'missing_tickers': close.columns[close.loc[missing_dates[0]].isna()].tolist() if len(missing_dates) else [],
        'policy': 'stop before first incomplete universe day; never fabricate a held-position mark'}
    for mode, info in result['selected'].items():
        name = info['name'].split('__')[0]
        if name not in price_targets(prices):
            continue
        frame = simulate_weights(prices['open'], close, targets[name], '2025-06-30', extension_end,
                                 target_vol=TARGET_VOL if mode == 'vol_5pct' else None)
        result['post_pead_window'][info['name']] = summarize(frame)
        frame.to_csv(OUT / f"extension_{info['name']}.csv")
    (OUT / 'results.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    lines = ['# Offline strategy comparison', '',
             'All returns are daily mark-to-market, net of 10 bps round-trip trading costs and 3% annual short borrow. Cash earns zero. Sharpe uses arithmetic mean daily returns with zero risk-free rate.', '',
             '| Candidate | CAGR | Volatility | Sharpe | Max drawdown | 2021–23 Sharpe | 2024–25 Sharpe | 25 bps CAGR |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    b = baseline_net
    lines.append(f"| Recorded PEAD, corrected accounting | {b['annualized_return']:.2%} | {b['annualized_std']:.2%} | {b['sharpe_ratio']:.2f} | {b['max_drawdown']:.2%} | {result['baseline_selection']['sharpe_ratio']:.2f} | {result['baseline_later']['sharpe_ratio']:.2f} | — |")
    for k, v in result['candidates'].items():
        m = v['full']
        lines.append(f"| {k} | {m['annualized_return']:.2%} | {m['annualized_std']:.2%} | {m['sharpe_ratio']:.2f} | {m['max_drawdown']:.2%} | {v['selection_2021_2023']['sharpe_ratio']:.2f} | {v['later_2024_2025']['sharpe_ratio']:.2f} | {v['cost_25bps_full']['annualized_return']:.2%} |")
    lines += ['', 'Selected among alternatives using 2021–23 Sharpe only:', '', '```json', json.dumps(result['selected'], indent=2), '```', '',
              '## SPY benchmark', '', spec['benchmark_note'], '',
              '| Benchmark | CAGR | Volatility | Sharpe | Max drawdown |',
              '|---|---:|---:|---:|---:|']
    for k, m in result['benchmarks'].items():
        lines.append(f"| {k} | {m['annualized_return']:.2%} | {m['annualized_std']:.2%} | {m['sharpe_ratio']:.2f} | {m['max_drawdown']:.2%} |")
    lines += ['', '## Price-only extension: 2025-06-30 through ' + str(extension_end.date()), '',
              'Earlier selected candidates only. No comparable PEAD earnings history in this extension; current-universe bias still applies.', '',
              'Data-quality stop: ' + json.dumps(result['extension_data_quality']), '',
              '```json', json.dumps(result['post_pead_window'], indent=2), '```', '',
              '## Interpretation limits', '', *['- ' + x for x in spec['limitations']], '',
              'Recorded PEAD keeps the original trade schedule and dollar sizes; its corrected equity is not fed back into historical risk decisions. Candidates run continuously across the selection/evaluation boundary; subperiod metrics include carried holdings. Initial entry and final liquidation costs are included. No candidate is deployed.', '',
              'Reproduce: `python3 -m research.compare_strategies`. Input hashes and annual training cutoffs are in specification.json.']
    (OUT / 'COMPARISON.md').write_text('\n'.join(lines) + '\n')
    return result


if __name__ == '__main__':
    main()
