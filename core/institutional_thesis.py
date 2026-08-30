from __future__ import annotations
import math
import numpy as np
import pandas as pd

def _ok(x):
    try:return math.isfinite(float(x))
    except Exception:return False

def build_thesis(ticker,row,eq=None,research=None,macro=None,forensics=None,valuation=None,commodity=None):
    eq=eq or {}; research=research or {}; macro=macro or {}; forensics=forensics or {}; valuation=valuation or {}; commodity=commodity or {}
    catalysts=list(eq.get('Key_Catalysts',[]) or research.get('Catalysts',{}).get('Structural_Catalysts',[]) or [])
    risks=list(eq.get('Key_Risks',[]) or research.get('Catalysts',{}).get('Structural_Risks',[]) or [])
    why=[]
    if _ok(row.get('Trend_Score')) and float(row.get('Trend_Score'))>=70: why.append('strong structural trend')
    if _ok(row.get('Revision_Score')) and float(row.get('Revision_Score'))>=60: why.append('positive estimate revisions')
    if _ok(row.get('RS_Percentile')) and float(row.get('RS_Percentile'))>=70: why.append('relative-strength leadership')
    if macro.get('Macro_Regime') in {'GOLDILOCKS','REFLATION'}: why.append(f"supportive macro regime ({macro.get('Macro_Regime')})")
    if commodity and commodity.get('Term_Structure')=='BACKWARDATION': why.append('supportive backwardated futures curve')
    market_may_miss=[]
    revdcf=valuation.get('Reverse_DCF',{}) if valuation else {}
    if revdcf.get('available') and _ok(revdcf.get('Implied_FCF_Growth_%')):
        g=float(revdcf['Implied_FCF_Growth_%'])
        if g<10: market_may_miss.append('valuation embeds relatively modest long-term FCF growth')
        elif g>30: market_may_miss.append('valuation already embeds aggressive long-term FCF growth')
    if _ok(forensics.get('Earnings_Quality_Score')) and float(forensics['Earnings_Quality_Score'])>=75: market_may_miss.append('cash-flow quality is stronger than headline earnings alone suggest')
    invalid=row.get('Invalidation','N/D')
    scen=research.get('Scenarios',{}) if research else {}
    action=row.get('Action',row.get('Setup','N/D'))
    return {
        'Why_Now':why or ['no single dominant timing edge detected from available evidence'],
        'What_Market_May_Be_Missing':market_may_miss or ['insufficient evidence to claim a differentiated market-mispricing thesis'],
        'Catalysts':catalysts,
        'Risks':risks,
        'Invalidation':invalid,
        'Bear_Case':scen.get('Bear_Price',np.nan),'Base_Case':scen.get('Base_Price',np.nan),'Bull_Case':scen.get('Bull_Price',np.nan),
        'Expected_Return_%':scen.get('Expected_Return_%',np.nan),'Recommended_Execution':action,
        'Thesis_Note':'Narrative is assembled only from observed model evidence; it does not infer undisclosed company information.'
    }
