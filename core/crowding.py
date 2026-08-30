import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from core.utils import clamp

@st.cache_data(ttl=3600, show_spinner=False)
def get_crowding_snapshot(ticker):
    out = {
        'Short_%_Float': np.nan,
        'Short_%_Shares': np.nan,
        'Short_Ratio_Days': np.nan,
        'Insider_%': np.nan,
        'Institution_%': np.nan,
        'Shares_Short': np.nan,
        'Shares_Short_Prior_Month': np.nan,
        'Crowding_Score': 50,
        'Crowding_Risk': 'NORMAL',
    }
    try:
        info = yf.Ticker(ticker).info or {}
        out['Short_%_Float'] = info.get('shortPercentOfFloat', np.nan)
        out['Short_%_Shares'] = info.get('sharesPercentSharesOut', np.nan)
        out['Short_Ratio_Days'] = info.get('shortRatio', np.nan)
        out['Insider_%'] = info.get('heldPercentInsiders', np.nan)
        out['Institution_%'] = info.get('heldPercentInstitutions', np.nan)
        out['Shares_Short'] = info.get('sharesShort', np.nan)
        out['Shares_Short_Prior_Month'] = info.get('sharesShortPriorMonth', np.nan)

        score = 50
        sf = out['Short_%_Float']
        sr = out['Short_Ratio_Days']
        if pd.notna(sf):
            sfp = float(sf) * 100 if float(sf) <= 1 else float(sf)
            score += 25 if sfp >= 20 else 15 if sfp >= 10 else 5 if sfp >= 5 else 0
        if pd.notna(sr):
            score += 15 if float(sr) >= 7 else 8 if float(sr) >= 4 else 0
        s0, s1 = out['Shares_Short'], out['Shares_Short_Prior_Month']
        if pd.notna(s0) and pd.notna(s1) and float(s1) > 0:
            change = float(s0) / float(s1) - 1
            score += 8 if change >= .10 else -5 if change <= -.10 else 0
        score = int(clamp(score))
        out['Crowding_Score'] = score
        out['Crowding_Risk'] = 'HIGH' if score >= 80 else 'ELEVATED' if score >= 65 else 'NORMAL'
    except Exception:
        pass
    return out
