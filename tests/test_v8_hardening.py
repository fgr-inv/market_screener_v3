import numpy as np
import pandas as pd

from core.alert_state import should_notify
from core.quality_weighting import available_weighted_score
from core.themes import ticker_themes,theme_exposure
from core.factor_diagnostics import factor_correlation,redundant_pairs
from core.change_detection import latest_changes
from core.portfolio_risk import portfolio_risk,high_correlation_pairs
from core.opportunity import model_coverage,opportunity_score
from core.data_quality import completeness_score,quality_label


def test_alert_false_resets():
    ok,reason=should_notify(False,{'last_hit':True})
    assert ok is False and reason=='RESET'


def test_alert_edge_fires():
    ok,reason=should_notify(True,{'last_hit':False})
    assert ok is True and reason=='EDGE'


def test_alert_true_does_not_repeat_by_default():
    ok,reason=should_notify(True,{'last_hit':True},repeat_while_true=False)
    assert ok is False and reason=='ALREADY_ACTIVE'


def test_alert_cooldown_blocks_repeat():
    now=pd.Timestamp('2026-08-24T12:00:00Z')
    state={'last_hit':True,'last_triggered_at':pd.Timestamp('2026-08-24T11:30:00Z')}
    ok,reason=should_notify(True,state,cooldown_minutes=60,repeat_while_true=True,now=now)
    assert ok is False and reason=='COOLDOWN'


def test_alert_cooldown_allows_repeat():
    now=pd.Timestamp('2026-08-24T12:31:00Z')
    state={'last_hit':True,'last_triggered_at':pd.Timestamp('2026-08-24T11:30:00Z')}
    ok,reason=should_notify(True,state,cooldown_minutes=60,repeat_while_true=True,now=now)
    assert ok is True and reason=='COOLDOWN_ELAPSED'


def test_weighted_score_ignores_missing_not_neutralizes():
    score,coverage,used=available_weighted_score({'a':100,'b':np.nan},{'a':.5,'b':.5})
    assert score==100
    assert coverage==50
    assert used==['a']


def test_weighted_score_normalizes_available_weights():
    score,coverage,_=available_weighted_score({'a':100,'b':0},{'a':.75,'b':.25})
    assert round(score,4)==75
    assert coverage==100


def test_weighted_score_empty_is_nan():
    score,coverage,used=available_weighted_score({'a':np.nan},{'a':1})
    assert pd.isna(score) and coverage==0 and used==[]


def test_gev_theme_weights_sum_to_one():
    themes=ticker_themes('GEV','Industrials')
    assert abs(sum(themes.values())-1)<1e-9
    assert 'Power / Electrification' in themes


def test_unknown_ticker_falls_back_to_sector_theme():
    assert ticker_themes('XYZ','Industrials')=={'Industrials':1.0}


def test_theme_exposure_sums_to_100():
    detail=pd.DataFrame([
        {'Ticker':'NVDA','Sector':'Technology','Weight %':60},
        {'Ticker':'WMT','Sector':'Consumer Staples','Weight %':40},
    ])
    out=theme_exposure(detail)
    assert abs(out['Weight %'].sum()-100)<1e-9


def test_factor_correlation_detects_redundancy():
    n=30
    df=pd.DataFrame({'Trend_Score':np.arange(n),'RS_Percentile':np.arange(n)*2,'Entry_Score':np.arange(n)[::-1]})
    corr=factor_correlation(df,min_obs=20)
    pairs=redundant_pairs(corr,.8)
    assert not pairs.empty
    assert ((pairs['Factor A']=='Trend_Score') & (pairs['Factor B']=='RS_Percentile')).any()


def test_change_detection_uses_two_latest_dates():
    h=pd.DataFrame([
        {'ts':'2026-08-22','ticker':'A','entry':50,'action':'WAIT','price':10},
        {'ts':'2026-08-23','ticker':'A','entry':70,'action':'WATCH','price':11},
        {'ts':'2026-08-22','ticker':'B','entry':60,'action':'WAIT','price':20},
        {'ts':'2026-08-23','ticker':'B','entry':61,'action':'WAIT','price':20},
    ])
    out=latest_changes(h,min_abs_delta=5)
    assert list(out['ticker'])==['A']
    assert float(out.iloc[0]['delta_entry'])==20


def _synthetic_prices(scale=1.0, seed=1):
    rng=np.random.default_rng(seed)
    ret=rng.normal(.0005,.01,300)*scale
    close=100*np.cumprod(1+ret)
    idx=pd.date_range('2025-01-01',periods=300,freq='B')
    return pd.DataFrame({'Close':close},index=idx)


def test_portfolio_risk_contributions_sum_approximately_100():
    pos=pd.DataFrame([
        {'ticker':'A','quantity':10,'sector':'Tech'},
        {'ticker':'B','quantity':10,'sector':'Staples'},
    ])
    pm={'A':_synthetic_prices(1,1),'B':_synthetic_prices(.5,2),'SPY':_synthetic_prices(.8,3)}
    summary,detail,corr=portfolio_risk(pos,pm)
    assert not detail.empty
    assert abs(detail['Risk Contribution %'].sum()-100)<1e-6


def test_portfolio_risk_has_cvar_and_drawdown():
    pos=pd.DataFrame([{'ticker':'A','quantity':10,'sector':'Tech'}])
    pm={'A':_synthetic_prices(1,1),'SPY':_synthetic_prices(.8,3)}
    summary,_,_=portfolio_risk(pos,pm)
    assert '1d CVaR 95 $' in summary
    assert 'Historical Max Drawdown %' in summary


def test_high_corr_pairs():
    corr=pd.DataFrame([[1,.9,.2],[.9,1,.3],[.2,.3,1]],index=['A','B','C'],columns=['A','B','C'])
    out=high_correlation_pairs(corr,.8)
    assert len(out)==1 and out.iloc[0]['Asset A']=='A' and out.iloc[0]['Asset B']=='B'


def test_model_coverage_declines_with_missing_factors():
    row={'Quality_Score':90,'Trend_Score':80,'Entry_Score':70,'RS_Percentile':np.nan,'Sector_Score':np.nan,'Macro_Fit':60,'Revision_Score':np.nan,'Valuation_Score':np.nan}
    cov,used=model_coverage(pd.Series(row))
    assert cov<100 and cov>0
    assert 'quality' in used


def test_opportunity_missing_optional_factors_not_filled_with_50():
    row=pd.Series({'Quality_Score':100,'Trend_Score':100,'Entry_Score':100,'RS_Percentile':np.nan,'Sector_Score':np.nan,'Macro_Fit':np.nan,'Revision_Score':np.nan,'Valuation_Score':np.nan,'RR':2.5,'Scan_Extended_Trim':False,'Event_Risk':'LOW'})
    score=opportunity_score(row)
    assert score>=90


def test_completeness_score():
    assert completeness_score({'a':1,'b':None},['a','b'])==50


def test_quality_labels():
    assert quality_label(95)=='EXCELLENT'
    assert quality_label(80)=='GOOD'
    assert quality_label(60)=='PARTIAL'
    assert quality_label(20)=='LOW'
