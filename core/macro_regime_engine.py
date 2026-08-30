from __future__ import annotations
import numpy as np
import pandas as pd
from core.utils import clamp

def _first_number(m, *keys):
    for key in keys:
        v=m.get(key,np.nan)
        try:
            x=float(v)
            if np.isfinite(x): return x
        except Exception:
            pass
    return np.nan

def macro_regime(m:dict):
    m=m or {}
    # A key present with value None must not block the faster market-based fallback.
    # This was the source of Market Intelligence showing UNKNOWN even when Growth
    # and Inflation_Pressure were already available.
    g=_first_number(m,'Slow_Growth','Growth')
    inf=_first_number(m,'Slow_Inflation_Pressure','Inflation_Pressure')
    liq=_first_number(m,'Liquidity'); credit=_first_number(m,'Credit'); risk=_first_number(m,'Risk_Appetite'); rates=_first_number(m,'Rates')
    if pd.notna(g) and pd.notna(inf):
        regime='GOLDILOCKS' if g>=50 and inf<55 else 'REFLATION' if g>=50 and inf>=55 else 'STAGFLATION' if g<50 and inf>=55 else 'SLOWDOWN / DISINFLATION'
    else: regime='UNKNOWN'
    vals=[x for x in [liq,credit,risk,rates] if pd.notna(x)]; liquidity_score=int(clamp(round(np.mean(vals)))) if vals else 50
    return {'Macro_Regime':regime,'Growth_Score':g,'Inflation_Pressure_Score':inf,'Global_Liquidity_Proxy_Score':liquidity_score,
            'Risk_Appetite':risk,'Credit_Conditions':credit,'Rates_Regime_Score':rates,
            'Regime_Note':'Regime is a probabilistic classification from public growth/inflation/liquidity/market-condition proxies, not a forecast certainty.'}
