import numpy as np
import pandas as pd

from core.macro_regime_engine import macro_regime
from core.market_intelligence import _snapshot_sector_evidence, sector_fundamental_overlay


def test_macro_regime_falls_back_when_slow_fields_are_none():
    m={'Slow_Growth':None,'Slow_Inflation_Pressure':None,'Growth':38,'Inflation_Pressure':55,
       'Liquidity':50,'Credit':64,'Risk_Appetite':68,'Rates':58}
    out=macro_regime(m)
    assert out['Macro_Regime']=='STAGFLATION'
    assert out['Growth_Score']==38
    assert out['Inflation_Pressure_Score']==55


def test_snapshot_sector_evidence_excludes_nd_revision_fallbacks():
    df=pd.DataFrame([
        {'Sector':'Technology','Revision_Score':50,'Revision_Direction':'N/D','Valuation_Score':70},
        {'Sector':'Technology','Revision_Score':72,'Revision_Direction':'IMPROVING','Valuation_Score':60},
    ])
    x=_snapshot_sector_evidence(df)['Technology']
    assert x['revision']==72
    assert x['revision_n']==1
    assert x['valuation']==65


def test_sector_overlay_prefers_deep_snapshot_without_calling_live(monkeypatch):
    import core.market_intelligence as mi
    rows=[]
    for sector in mi.SECTOR_ETFS:
        rows.append({'Sector':sector,'Revision_Score':67,'Revision_Direction':'IMPROVING','Valuation_Score':61})
    df=pd.DataFrame(rows)
    monkeypatch.setattr(mi,'_live_representative_evidence',lambda: (_ for _ in ()).throw(AssertionError('live should not run')))
    out=sector_fundamental_overlay(df,live_fallback=True)
    assert all(v['revision']==67 for v in out.values())
    assert all(v['valuation']==61 for v in out.values())
    assert all(v['revision_source']=='DEEP SCREENER' for v in out.values())
