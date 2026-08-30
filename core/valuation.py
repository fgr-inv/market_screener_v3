import numpy as np
import pandas as pd
from core.utils import clamp


def standalone_valuation_score(f):
    score=50
    pe=f.get('Forward_PE',np.nan); eve=f.get('EV_EBITDA',np.nan); fcf=f.get('FCF',np.nan); mc=f.get('Market_Cap',np.nan); growth=f.get('Earnings_Growth',np.nan)
    # Do not manufacture a neutral valuation score when no valuation evidence exists.
    has_pe=pd.notna(pe)
    has_eve=pd.notna(eve)
    has_fcf_yield=pd.notna(fcf) and pd.notna(mc) and bool(mc)
    if not (has_pe or has_eve or has_fcf_yield):
        return np.nan
    if pd.notna(pe): score += 12 if 0<pe<=18 else 7 if pe<=25 else 0 if pe<=35 else -8 if pe<=50 else -15
    if pd.notna(eve): score += 8 if 0<eve<=12 else 3 if eve<=18 else -6 if eve>25 else 0
    if pd.notna(fcf) and pd.notna(mc) and mc:
        y=float(fcf)/float(mc)*100
        score += 12 if y>=5 else 7 if y>=3 else 2 if y>=1 else -8
    if pd.notna(pe) and pd.notna(growth) and growth>0:
        # rough PEG-like sanity check using growth as decimal
        peg=float(pe)/(float(growth)*100)
        score += 8 if peg<=1.2 else 3 if peg<=2 else -6 if peg>3 else 0
    return int(clamp(score))


def add_peer_valuation_scores(df):
    out=df.copy()
    if 'Forward_PE' not in out:
        return out
    out['PE_Sector_Percentile']=np.nan
    out['PE_Percentile_Source']='NO_PE'
    out['PE_Peer_Count']=0
    all_vals=pd.to_numeric(out['Forward_PE'],errors='coerce')
    universe_pct=None
    if all_vals.notna().sum()>=2:
        universe_pct=(1-all_vals.rank(pct=True,method='average'))*100
    for sec,g in out.groupby('Sector',dropna=False):
        vals=pd.to_numeric(g['Forward_PE'],errors='coerce')
        n=int(vals.notna().sum())
        out.loc[g.index,'PE_Peer_Count']=n
        valid_idx=vals[vals.notna()].index
        if n>=2:
            # Lower P/E = better valuation percentile inside the observed sector peer set.
            pct=(1-vals.rank(pct=True,method='average'))*100
            out.loc[valid_idx,'PE_Sector_Percentile']=pct.loc[valid_idx].round(0)
            out.loc[valid_idx,'PE_Percentile_Source']='SECTOR'
        elif n==1 and universe_pct is not None:
            # A one-name sector sample cannot support a sector percentile. Use the
            # enriched equity universe as a transparent fallback instead of returning None.
            out.loc[valid_idx,'PE_Sector_Percentile']=universe_pct.loc[valid_idx].round(0)
            out.loc[valid_idx,'PE_Percentile_Source']='UNIVERSE_FALLBACK'
    if 'Valuation_Score' not in out:
        out['Valuation_Score']=np.nan
    out['Valuation_Score']=out['Valuation_Score'].fillna(out['PE_Sector_Percentile'])
    return out
