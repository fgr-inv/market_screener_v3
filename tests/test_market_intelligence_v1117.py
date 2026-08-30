import pandas as pd
import numpy as np
from core.market_intelligence import opportunity_radar, macro_sensitivity_table, breadth_dashboard

def _px(start=100,n=220,step=.2):
    idx=pd.date_range('2025-01-01',periods=n,freq='B'); c=np.arange(n)*step+start
    return pd.DataFrame({'Open':c,'High':c+1,'Low':c-1,'Close':c,'Volume':1_000_000},index=idx)

def test_opportunity_radar_missing_aware():
    df=pd.DataFrame({'Ticker':['A','B'],'Sector':['Technology','Energy'],'Quality_Score':[90,60],'Valuation_Score':[80,np.nan],'Technical_Score':[70,90]})
    out=opportunity_radar(df)
    assert 'Market_Intelligence_Score' in out
    assert out['Market_Intelligence_Score'].notna().all()

def test_macro_sensitivity_has_all_sectors():
    out=macro_sensitivity_table()
    assert len(out)==11 and 'Real Estate' in set(out['Sector'])

def test_breadth_proxy_is_explicit():
    pm={k:_px(step=v) for k,v in {'SPY':.2,'QQQ':.3,'RSP':.1,'IWM':.05}.items()}
    tab,rel=breadth_dashboard(pm)
    assert len(tab)==4
    assert 'RSP_vs_SPY_3M_pp' in rel
