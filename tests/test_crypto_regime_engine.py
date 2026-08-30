import numpy as np
import pandas as pd
from core.crypto_professional import professional_crypto_cycle

def _trend(n=500, start=20000, end=100000):
    idx=pd.date_range('2024-01-01', periods=n, freq='D')
    close=np.geomspace(start,end,n)
    return pd.DataFrame({'Close':close},index=idx)

def test_bull_regime_does_not_make_extension_automatically_bad():
    d=_trend()
    x=professional_crypto_cycle('BTC-USD',d,{'Funding_Rate':0.01,'OI_24h_%':4})
    assert x['Structural_Trend_Score'] >= 70
    assert x['Crypto_Regime'] in {'BULL EXPANSION','EARLY / DEVELOPING BULL'}
    assert x['Long_Term_Opportunity_Score'] >= 65
    assert x['Leverage_Risk']=='LOW'

def test_high_leverage_is_separate_from_cycle():
    d=_trend()
    x=professional_crypto_cycle('BTC-USD',d,{'Funding_Rate':0.12,'OI_24h_%':25})
    assert x['Leverage_Risk']=='HIGH'
    assert x['Structural_Trend_Score'] >= 70
