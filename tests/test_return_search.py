import numpy as np
import pandas as pd
from research.return_search.run import execute, targets, decision_mask, stats, eligible, features, predict


def prices(periods=400,n=5,crypto=False):
    dates=pd.date_range('2017-01-01',periods=periods) if crypto else pd.bdate_range('2017-01-01',periods=periods)
    rng=np.random.default_rng(56)
    c=pd.DataFrame(100*np.exp(np.cumsum(rng.normal(.0005,.01,(periods,n)),axis=0)),index=dates)
    return {'open':c*.999,'close':c,'high':c*1.01,'low':c*.99,'volume':c*0+1e6}


def test_cash_and_cost_reservation():
    p=prices(5,1);p={k:v*0+100 for k,v in p.items()};idx=p['close'].index
    t=pd.DataFrame(1.,index=idx,columns=[0]);rf=pd.Series(0.,index=idx)
    f=execute(p,t,rf,'etf',start=str(idx[0].date()))
    assert f.nav.iloc[-1]<1
    assert f.nav.iloc[0]==1  # No prior signal exists on the first data row.
    assert np.isclose(f.nav.iloc[1],1/1.0005)
    assert f.gross.max()<=1+1e-12
    assert np.allclose((1+f['return']).cumprod(),f.nav)


def test_crypto_waits_intervening_day():
    p=prices(6,1,True);idx=p['close'].index
    for k in ['open','close']:p[k][:]=100
    p['close'].iloc[2]=200;p['open'].iloc[3]=200;p['close'].iloc[3]=200
    t=pd.DataFrame(np.nan,index=idx,columns=[0]);t.iloc[0]=0;t.iloc[1]=1
    f=execute(p,t,pd.Series(0.,index=idx),'crypto',start=str(idx[0].date()))
    assert f.gross.iloc[2]==0
    assert f.nav.iloc[3]<1


def test_missing_held_price_fails():
    p=prices(5,1);idx=p['close'].index;p['close'].iloc[3]=np.nan
    t=pd.DataFrame(1.,index=idx,columns=[0])
    import pytest
    with pytest.raises(ValueError,match='missing held mark'):execute(p,t,pd.Series(0.,index=idx),'stocks',start=str(idx[0].date()))


def test_sizing_preserves_cash_slots():
    p=prices(50,5);score=p['close']*0-1;score.iloc[:,0]=1
    t=targets(p,'etf',{'test':score})['test'].dropna()
    assert np.allclose(t.sum(axis=1),.25)
    assert np.allclose(t.iloc[:,0],.25)


def test_first_loss_included_in_drawdown():
    idx=pd.bdate_range('2020-01-01',periods=3)
    f=pd.DataFrame({'return':[-.2,0,0],'cost':0,'turnover':0,'gross':1},index=idx)
    assert np.isclose(stats(f,pd.Series(0.,index=idx),252)['max_dd'],-.2)


def test_feature_future_perturbation(monkeypatch):
    import research.return_search.run as m
    monkeypatch.setattr(m,'macro',lambda dates,end:pd.DataFrame({'m':0.},index=dates))
    p=prices(450,4);end=str(p['close'].index[-1].date())
    original=features(p,'etf',end,False)[0]
    altered={k:v.copy() for k,v in p.items()}
    for k in altered:altered[k].iloc[380:]*=3
    changed=features(altered,'etf',end,False)[0]
    np.testing.assert_allclose(original[:380],changed[:380],equal_nan=True)


def test_walkforward_labels_mature_before_predictions():
    dates=pd.bdate_range('2014-01-01','2020-12-31');rng=np.random.default_rng(7)
    x=rng.normal(size=(len(dates),4,2)).astype('float32')
    y=pd.DataFrame(rng.normal(0,.1,(len(dates),4)),index=dates)
    e=y*0+True;e=e.astype(bool)
    _,audit=predict(x,y,e,dates,'etf',['ridge_price'],2,22,'2020-12-31')
    assert len(audit)==2
    assert all(a['last_label']<a['first_prediction'] for a in audit)
