import numpy as np
import pandas as pd
from research.downside_rotation import targets
from research.crowding_unwind import available_dates, size_targets


def test_rotation_is_causal_and_bounded():
    dates=pd.bdate_range('2018-01-01',periods=650)
    rng=np.random.default_rng(31)
    c=pd.DataFrame(100*np.exp(np.cumsum(rng.normal(.0005,.012,(650,6)),axis=0)),index=dates)
    original=targets(c)
    changed=c.copy();changed.iloc[500:]*=np.linspace(1,5,150)[:,None]
    pd.testing.assert_frame_equal(original.iloc[:500],targets(changed).iloc[:500])
    finite=original.dropna()
    assert finite.ge(0).all().all()
    assert finite.le(.5+1e-12).all().all()
    assert finite.sum(axis=1).le(1.5+1e-12).all()
    assert finite.gt(0).sum(axis=1).le(4).all()
    assert len(finite)<40


def test_report_features_wait_for_delayed_predecessors():
    report=pd.Series(pd.to_datetime(['2019-03-05','2019-03-12','2019-03-19']))
    released=report+pd.Timedelta(days=3)
    known=available_dates(report,released)
    assert known.ge(report+pd.Timedelta(days=7)).all()
    assert known.is_monotonic_increasing
    assert known.iloc[1]>=known.iloc[0]
    assert known.iloc[0]==pd.Timestamp('2019-05-04')


def test_vendor_release_never_moved_earlier():
    report=pd.Series(pd.to_datetime(['2023-02-07']))
    release=pd.Series(pd.to_datetime(['2023-06-01']))
    assert available_dates(report,release).iloc[0]==pd.Timestamp('2023-06-02')


def test_crowding_sizing_causal_and_capped():
    dates=pd.bdate_range('2020-01-01',periods=150)
    rng=np.random.default_rng(42)
    c=pd.DataFrame(100*np.exp(np.cumsum(rng.normal(0,.01,(150,4)),axis=0)),index=dates)
    signal=pd.DataFrame(1.,index=dates,columns=c.columns)
    t=size_targets(signal,c)
    altered=c.copy();altered.iloc[110:]*=2
    pd.testing.assert_frame_equal(t.iloc[:110],size_targets(signal,altered).iloc[:110])
    assert t.dropna().abs().sum(axis=1).le(2+1e-12).all()
    assert t.dropna().abs().le(.5+1e-12).all().all()
