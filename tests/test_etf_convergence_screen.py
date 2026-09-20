import numpy as np
import pandas as pd

from research.etf_convergence_screen import target_weights


def test_future_prices_cannot_change_prior_orders():
    dates = pd.bdate_range('2006-01-01', periods=800)
    rng = np.random.default_rng(7)
    common = np.cumsum(rng.normal(0, .01, len(dates)))
    residual = .035 * np.sin(np.arange(len(dates)) / 30)
    close = pd.DataFrame({'A': np.exp(4 + common + residual),
                          'B': np.exp(4 + common)}, index=dates)
    before = target_weights(close)
    altered = close.copy()
    altered.iloc[600:, 0] *= np.linspace(1, 5, 200)
    after = target_weights(altered)
    pd.testing.assert_frame_equal(before.iloc[:600], after.iloc[:600])
    assert (before.iloc[:251].fillna(0) == 0).all().all()
    entries = before.dropna().abs().sum(axis=1)
    assert (entries > .9).any(), 'test must exercise actual entries'
    assert entries.max() <= 1 + 1e-12
