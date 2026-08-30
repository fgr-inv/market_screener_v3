import numpy as np
import pandas as pd


def decision_summary(row, edge=None, portfolio_note=None):
    positives=[]; negatives=[]
    def val(k,default=np.nan):
        x=row.get(k,default)
        return x
    if pd.notna(val('Quality_Score')) and float(val('Quality_Score'))>=75: positives.append('strong business quality')
    if pd.notna(val('Revision_Score')) and float(val('Revision_Score'))>=65: positives.append('positive estimate revisions')
    if float(val('Trend_Score',0) or 0)>=75: positives.append('high-quality uptrend')
    if float(val('RS_Percentile',0) or 0)>=85: positives.append('top-decile relative strength')
    if float(val('Entry_Score',0) or 0)>=70: positives.append('constructive entry zone')
    if float(val('Sector_Score',0) or 0)>=70: positives.append('strong sector backdrop')
    if float(val('Macro_Fit',0) or 0)>=65: positives.append('supportive macro fit')
    rr=val('RR')
    if pd.notna(rr) and float(rr)>=2: positives.append('favorable risk/reward')
    if pd.notna(val('Valuation_Score')) and float(val('Valuation_Score'))<40: negatives.append('valuation is demanding')
    if str(val('Event_Risk','')).upper() in {'HIGH','ELEVATED'}: negatives.append('near-term event risk')
    if bool(val('Scan_Extended_Trim',False)): negatives.append('price is extended')
    if pd.notna(rr) and float(rr)<1.5: negatives.append('weak risk/reward')
    if portfolio_note: negatives.append(portfolio_note)
    action=row.get('Action','WAIT')
    return {'Action':action,'Positives':positives,'Negatives':negatives,'Historical_Edge':edge or {}}
