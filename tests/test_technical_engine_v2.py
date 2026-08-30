import numpy as np, pandas as pd
from core.indicators import enrich_indicators
from core.technical_engine_v2 import professional_technical_snapshot
from core.equity_sector_model import professional_equity_framework

def _df(n=320):
    idx=pd.date_range('2024-01-01',periods=n,freq='D')
    c=np.linspace(100,180,n)+np.sin(np.arange(n)/8)*3
    return pd.DataFrame({'Open':c*.998,'High':c*1.01,'Low':c*.99,'Close':c,'Volume':np.linspace(1e6,1.5e6,n)},index=idx)

def test_professional_ta_fields_and_score():
    d=enrich_indicators(_df())
    x=professional_technical_snapshot(d,'Acción')
    assert 0<=x['TA_Quality_Score']<=100
    assert x['Weekly_State'] in {'Bullish','Bearish','Neutral','N/D'}
    assert 'Anchored_VWAP' in x and 'Volume_Profile_POC_Proxy' in x
    assert x['FourH_State']=='N/A (daily feed)'

def test_industry_lenses_are_specific():
    assert 'CET1' in professional_equity_framework('Financials','Banks - Regional')
    assert 'FFO/AFFO' in professional_equity_framework('Real Estate','REIT - Industrial')
    assert 'ARR/RPO' in professional_equity_framework('Technology','Software - Application')
