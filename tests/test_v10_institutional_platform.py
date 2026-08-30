import pandas as pd
import numpy as np
from core.institutional_v10 import relative_value_rank, etf_lookthrough, signal_agreement, event_study, probability_calibration

def test_relative_value_is_missing_aware():
    x=pd.DataFrame({'Ticker':['A','B','C'],'Quality':[90,70,np.nan],'Opportunity':[80,60,50]})
    y=relative_value_rank(x)
    assert 'Relative_Value_Score' in y
    assert y.loc[2,'Relative_Value_Coverage_%'] < y.loc[0,'Relative_Value_Coverage_%']

def test_etf_lookthrough_reports_coverage():
    h=pd.DataFrame({'Ticker':['A','B'],'Weight':[.6,.4]})
    out=etf_lookthrough(h,{'A':{'Quality':80}})
    assert round(out['Lookthrough_Coverage_%'])==60
    assert out['Quality']==80

def test_signal_disagreement_visible():
    x=signal_agreement({'fundamental':90,'technical':85,'positioning':20,'valuation':30})
    assert x['Agreement_%'] < 100

def test_event_study():
    idx=pd.date_range('2024-01-01',periods=50,freq='D')
    p=pd.DataFrame({'Close':range(100,150)},index=idx)
    e=event_study(p,['2024-01-20'])
    assert len(e)==1 and 'T+5_%' in e

def test_probability_calibration():
    x=probability_calibration([.1,.2,.8,.9],[0,0,1,1],bins=2)
    assert x['N'].sum()==4
