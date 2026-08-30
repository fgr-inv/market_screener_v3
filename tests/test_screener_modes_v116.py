import numpy as np
import pandas as pd
from core.asset_models import analyze_asset


def _bars(n=520):
    idx=pd.date_range('2024-01-01',periods=n,freq='B')
    close=pd.Series(np.linspace(100,180,n),index=idx)
    df=pd.DataFrame({'Open':close*.999,'High':close*1.01,'Low':close*.99,'Close':close,'Volume':1_000_000},index=idx)
    # analyze_asset expects enriched indicators in production
    from core.indicators import enrich_indicators
    return enrich_indicators(df)


def test_fast_technical_skips_deep_ta_layer():
    out=analyze_asset('TEST',_bars(),None,'Technology','Acción',technical_depth='Rápido')
    assert out['Technical_Depth']=='Rápido'
    assert pd.isna(out['TA_Quality_Score'])
    assert 'Fast technical mode' in out['TA_Data_Note']


def test_deep_technical_adds_structure_layer():
    out=analyze_asset('TEST',_bars(),None,'Technology','Acción',technical_depth='Profundo')
    assert out['Technical_Depth']=='Profundo'
    assert pd.notna(out['TA_Quality_Score'])
    assert 'Market_Structure' in out
