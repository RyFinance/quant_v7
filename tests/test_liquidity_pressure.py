import numpy as np
import pandas as pd

from research.liquidity_pressure import build_features, cohort_targets


def test_features_and_eligibility_do_not_use_future_prices():
    rng = np.random.default_rng(9)
    dates = pd.bdate_range('2009-01-01', periods=500)
    c = pd.DataFrame(np.exp(4 + np.cumsum(rng.normal(0, .01, (500, 3)), axis=0)),
                     index=dates, columns=['A', 'B', 'SPY'])
    p = dict(close=c, open=c * .999, volume=c * 0 + 1e7)
    x, y, e, b, _ = build_features(p)
    altered = {k: v.copy() for k, v in p.items()}
    for k in ['open', 'close']:
        altered[k].iloc[400:] *= 3
    xa, ya, ea, ba, _ = build_features(altered)
    np.testing.assert_allclose(x[:400], xa[:400], equal_nan=True)
    pd.testing.assert_frame_equal(e.iloc[:400], ea.iloc[:400])
    pd.testing.assert_frame_equal(b.iloc[:400], ba.iloc[:400])
    # Labels may use future observations; six-session purge is essential.
    pd.testing.assert_frame_equal(y.iloc[:394], ya.iloc[:394])


def test_cohort_is_held_five_decisions_and_hedged():
    dates = pd.bdate_range('2020-01-01', periods=8)
    score = pd.DataFrame(np.nan, index=dates, columns=['A', 'B', 'SPY'])
    score.loc[dates[0], ['A', 'B']] = [2., -2.]
    eligible = pd.DataFrame(True, index=dates, columns=score.columns)
    eligible['SPY'] = False
    beta = pd.DataFrame({'A': 2., 'B': .5, 'SPY': 1.}, index=dates)
    target = cohort_targets(score, eligible, beta, thresholds=False)
    np.testing.assert_allclose(target.A.to_numpy(), [.01] * 5 + [0] * 3)
    np.testing.assert_allclose(target.B.to_numpy(), [-.01] * 5 + [0] * 3)
    np.testing.assert_allclose((target * beta).sum(axis=1), 0, atol=1e-14)
    assert target.abs().sum(axis=1).max() <= 1


def test_prediction_rank_is_cross_sectionally_centered():
    dates = pd.bdate_range('2020-01-01', periods=2)
    s = pd.DataFrame({'A': [.02, .02], 'B': [.01, .01], 'SPY': [np.nan, np.nan]}, index=dates)
    eligible = s.notna()
    beta = pd.DataFrame(1., index=dates, columns=s.columns)
    a = cohort_targets(s, eligible, beta)
    b = cohort_targets(s + .5, eligible, beta)
    pd.testing.assert_frame_equal(a, b)
