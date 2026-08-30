import pandas as pd
from core.utils import clamp
from core.position_sizing import size_position
from core.opportunity import attach_scores
from core.model_registry import get_active_model


def test_clamp():
    assert clamp(120)==100
    assert clamp(-2)==0
    assert clamp(55)==55


def test_position_sizing_positive():
    out=size_position(100000,1.0,100,95,20)
    assert out['shares'] >= 0
    assert out['actual_risk'] <= 1000 + 1e-9


def test_opportunity_bounds():
    df=pd.DataFrame([{
        'Quality_Score':80,'Revision_Score':70,'Valuation_Score':60,'Confidence_Score':90,
        'Trend_Score':85,'Entry_Score':80,'RS_Percentile':90,'Risk_Score':80,
        'Sector_Score':75,'Macro_Fit':70,'RR':2.5,'Scan_Extended_Trim':False,
        'Scan_Breakout_Base':False,'Event_Risk':'NORMAL'
    }])
    out=attach_scores(df)
    assert 0 <= out.iloc[0]['Opportunity_Score'] <= 100


def test_model_weights_sum_reasonable():
    m=get_active_model(); total=sum(m['weights'].values())
    assert 0.95 <= total <= 1.05
