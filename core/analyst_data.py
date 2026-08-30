import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from core.cache_policy import ANALYST_TTL


def _to_df(obj):
    return obj.copy() if isinstance(obj,pd.DataFrame) else pd.DataFrame()

@st.cache_data(ttl=ANALYST_TTL,show_spinner=False)
def get_analyst_snapshot(ticker):
    t=yf.Ticker(ticker)
    out={
        'EPS_Revision_Score':np.nan,'Revision_Direction':'N/D','Price_Target_Upside_%':np.nan,
        'Recommendation_Mean':np.nan,'Recommendation_Key':'N/D','Analyst_Count':np.nan,
        'Earnings_Surprise_%':np.nan,'Next_Earnings':'N/D','Revision_Detail':pd.DataFrame(),
        'EPS_Current_Estimate':np.nan,'EPS_30d_Ago':np.nan,'Revision_Velocity_%':np.nan,
        'Revenue_Estimate_Growth_%':np.nan,'Target_Dispersion_%':np.nan,'Historical_Beat_Rate_%':np.nan,
        'Management_Execution_Score':np.nan,
    }
    try:
        info=t.info or {}
        out['Recommendation_Mean']=info.get('recommendationMean',np.nan)
        out['Recommendation_Key']=info.get('recommendationKey','N/D')
        out['Analyst_Count']=info.get('numberOfAnalystOpinions',np.nan)
        target=info.get('targetMeanPrice',np.nan); price=info.get('currentPrice',info.get('regularMarketPrice',np.nan))
        if pd.notna(target) and pd.notna(price) and price:
            out['Price_Target_Upside_%']=(float(target)/float(price)-1)*100
        hi=info.get('targetHighPrice',np.nan); lo=info.get('targetLowPrice',np.nan)
        if pd.notna(hi) and pd.notna(lo) and pd.notna(target) and target:
            out['Target_Dispersion_%']=(float(hi)-float(lo))/abs(float(target))*100
    except Exception: pass

    revisions=[]
    score=50
    try:
        ee=_to_df(getattr(t,'earnings_estimate',pd.DataFrame()))
        if not ee.empty:
            ee=ee.reset_index()
            out['Revision_Detail']=ee
            cols=[c for c in ee.columns if 'growth' in str(c).lower() or 'avg' in str(c).lower() or 'estimate' in str(c).lower()]
            # yfinance commonly exposes avgEstimate and growth by period.
            avg=next((c for c in ee.columns if str(c).lower()=='avgestimate'),None)
            growth=next((c for c in ee.columns if str(c).lower()=='growth'),None)
            if avg and len(ee): out['EPS_Current_Estimate']=pd.to_numeric(ee[avg],errors='coerce').iloc[0]
            if growth and len(ee):
                gv=pd.to_numeric(ee[growth],errors='coerce').iloc[0]
                if pd.notna(gv): out['Revenue_Estimate_Growth_%']=float(gv)*100 if abs(float(gv))<2 else float(gv)
    except Exception: pass

    try:
        rev=_to_df(getattr(t,'eps_revisions',pd.DataFrame()))
        if not rev.empty:
            rev2=rev.reset_index()
            out['Revision_Detail']=rev2
            # Common yfinance columns: upLast7days, upLast30days, downLast7days, downLast30days
            up=down=0
            for c in rev.columns:
                lc=str(c).lower()
                vals=pd.to_numeric(rev[c],errors='coerce').fillna(0)
                if 'up' in lc: up += vals.sum()
                if 'down' in lc: down += vals.sum()
            net=float(up-down)
            score=max(0,min(100,50+net*4))
            revisions.append(net)
    except Exception: pass

    try:
        trend=_to_df(getattr(t,'eps_trend',pd.DataFrame()))
        if not trend.empty:
            nums=trend.apply(pd.to_numeric,errors='coerce')
            # Reward improving current estimates vs older snapshots when columns exist.
            cols=list(nums.columns)
            if len(cols)>=2:
                delta=(nums[cols[0]]-nums[cols[-1]]).replace([np.inf,-np.inf],np.nan).dropna()
                if len(delta):
                    score += max(-20,min(20,float(delta.mean())*10))
            # Try to expose current vs 30d-ago EPS expectation when named columns exist.
            cur=next((c for c in nums.columns if str(c).lower() in {'current','currentestimate'}),None)
            ago=next((c for c in nums.columns if '30' in str(c).lower()),None)
            if cur and ago and len(nums):
                cv=pd.to_numeric(nums[cur],errors='coerce').iloc[0]; av=pd.to_numeric(nums[ago],errors='coerce').iloc[0]
                out['EPS_Current_Estimate']=cv
                out['EPS_30d_Ago']=av
                if pd.notna(cv) and pd.notna(av) and av!=0: out['Revision_Velocity_%']=(float(cv)/float(av)-1)*100
    except Exception: pass

    out['EPS_Revision_Score']=int(max(0,min(100,round(score))))
    out['Revision_Direction']='IMPROVING' if score>=60 else 'DETERIORATING' if score<=40 else 'NEUTRAL'

    try:
        cal=t.calendar
        if isinstance(cal,dict):
            ed=cal.get('Earnings Date')
            if isinstance(ed,(list,tuple)) and ed: out['Next_Earnings']=str(ed[0])[:10]
            elif ed is not None: out['Next_Earnings']=str(ed)[:10]
    except Exception: pass

    try:
        hist=_to_df(t.get_earnings_dates(limit=8))
        if not hist.empty:
            col=next((c for c in hist.columns if 'Surprise' in str(c)),None)
            if col:
                x=pd.to_numeric(hist[col],errors='coerce').dropna()
                if len(x):
                    out['Earnings_Surprise_%']=float(x.iloc[0])
                    out['Historical_Beat_Rate_%']=float((x>0).mean()*100)
                    med=float(x.median())
                    out['Management_Execution_Score']=int(max(0,min(100,50+(out['Historical_Beat_Rate_%']-50)*.5+max(-15,min(15,med*2)))))
    except Exception: pass
    return out
