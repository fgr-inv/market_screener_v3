from __future__ import annotations
import numpy as np
import pandas as pd
from core.utils import clamp

def macro_regime(m:dict):
    m=m or {}; g=m.get('Slow_Growth',m.get('Growth',np.nan)); inf=m.get('Slow_Inflation_Pressure',m.get('Inflation_Pressure',np.nan)); liq=m.get('Liquidity',np.nan); credit=m.get('Credit',np.nan); risk=m.get('Risk_Appetite',np.nan); rates=m.get('Rates',np.nan)
    if pd.notna(g) and pd.notna(inf):
        regime='GOLDILOCKS' if g>=50 and inf<55 else 'REFLATION' if g>=50 and inf>=55 else 'STAGFLATION' if g<50 and inf>=55 else 'SLOWDOWN / DISINFLATION'
    else: regime='UNKNOWN'
    vals=[x for x in [liq,credit,risk,rates] if pd.notna(x)]; liquidity_score=int(clamp(round(np.mean(vals)))) if vals else 50
    return {'Macro_Regime':regime,'Growth_Score':g,'Inflation_Pressure_Score':inf,'Global_Liquidity_Proxy_Score':liquidity_score,
            'Risk_Appetite':risk,'Credit_Conditions':credit,'Rates_Regime_Score':rates,
            'Regime_Note':'Regime is a probabilistic classification from public growth/inflation/liquidity/market-condition proxies, not a forecast certainty.'}
