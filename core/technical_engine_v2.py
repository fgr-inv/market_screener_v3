"""Professional technical-analysis layer shared by asset-specific engines.

This module deliberately separates *observations* (structure, participation,
volatility, location) from the asset-class scoring performed in asset_models.
It only uses data that are actually available. Daily bars can produce weekly
confirmation, but never pretend to provide 4-hour confirmation.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from core.utils import clamp


def _f(v, default=np.nan):
    try: return float(v) if pd.notna(v) else default
    except Exception: return default


def _weekly_state(df: pd.DataFrame) -> str:
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex): return 'N/D'
    w=df['Close'].dropna().resample('W').last().dropna()
    if len(w)<30: return 'N/D'
    e21=w.ewm(span=21,adjust=False).mean(); s40=w.rolling(40).mean()
    p=_f(w.iloc[-1]); e=_f(e21.iloc[-1]); s=_f(s40.iloc[-1])
    if pd.isna(s): return 'Bullish' if p>e and e>_f(e21.iloc[-5]) else 'Bearish' if p<e else 'Neutral'
    return 'Bullish' if p>e>s else 'Bearish' if p<e and e<s else 'Neutral'


def _structure(df: pd.DataFrame, window=5) -> tuple[str,float,float]:
    """Confirmed swing structure from centered pivots; last bar is never a pivot."""
    c=df['Close'].dropna(); h=df['High'].reindex(c.index); l=df['Low'].reindex(c.index)
    if len(c)<window*4+10: return 'Insufficient history',np.nan,np.nan
    rh=h.rolling(window*2+1,center=True).max(); rl=l.rolling(window*2+1,center=True).min()
    ph=h[(h==rh)].dropna(); pl=l[(l==rl)].dropna()
    ph=ph.iloc[:-window] if len(ph)>window else ph.iloc[0:0]
    pl=pl.iloc[:-window] if len(pl)>window else pl.iloc[0:0]
    if len(ph)<2 or len(pl)<2: return 'Unclear',np.nan,np.nan
    h1,h2=_f(ph.iloc[-2]),_f(ph.iloc[-1]); l1,l2=_f(pl.iloc[-2]),_f(pl.iloc[-1])
    state='HH / HL' if h2>h1 and l2>l1 else 'LH / LL' if h2<h1 and l2<l1 else 'Transition / Mixed'
    return state,h2,l2


def _anchored_vwap(df: pd.DataFrame, lookback=126):
    if 'Volume' not in df or len(df)<20: return np.nan,np.nan
    x=df.tail(min(lookback,len(df))).copy()
    vol=pd.to_numeric(x['Volume'],errors='coerce').fillna(0)
    if vol.sum()<=0: return np.nan,np.nan
    # Anchor to the most recent significant low inside the window, a reproducible
    # price-action anchor. This is not an earnings/event AVWAP unless event data exist.
    anchor=x['Low'].rolling(10,min_periods=1).min().idxmin()
    y=x.loc[anchor:]
    v=pd.to_numeric(y['Volume'],errors='coerce').fillna(0)
    tp=(y['High']+y['Low']+y['Close'])/3
    if v.sum()<=0: return np.nan,np.nan
    av=float((tp*v).sum()/v.sum()); return av,anchor


def _volume_profile_proxy(df: pd.DataFrame, lookback=126, bins=24):
    """Daily-bar volume-at-price proxy, explicitly not an exchange tick profile."""
    if 'Volume' not in df: return np.nan
    x=df.tail(min(lookback,len(df))).dropna(subset=['High','Low','Close','Volume'])
    if len(x)<20 or x['Volume'].sum()<=0: return np.nan
    tp=((x['High']+x['Low']+x['Close'])/3).to_numpy(); vol=x['Volume'].to_numpy(dtype=float)
    lo,hi=float(np.nanmin(tp)),float(np.nanmax(tp))
    if not np.isfinite(lo+hi) or hi<=lo: return np.nan
    edges=np.linspace(lo,hi,bins+1); idx=np.clip(np.digitize(tp,edges)-1,0,bins-1)
    sums=np.bincount(idx,weights=vol,minlength=bins); k=int(np.argmax(sums))
    return float((edges[k]+edges[k+1])/2)


def professional_technical_snapshot(df: pd.DataFrame, asset_class='Equity') -> dict:
    if df is None or df.empty or len(df)<30:
        return {'TA_Quality_Score':50,'Market_Structure':'Insufficient history','Weekly_State':'N/D','FourH_State':'N/A (daily feed)'}
    last=df.iloc[-1]; p=_f(last.get('Close')); atrp=_f(last.get('ATR_%')); rsi=_f(last.get('RSI14'))
    structure,last_sh,last_sl=_structure(df)
    weekly=_weekly_state(df)
    avwap,anchor=_anchored_vwap(df); vpoc=_volume_profile_proxy(df)
    rv=_f(last.get('Volume'))/_f(last.get('Vol20')) if _f(last.get('Vol20'))>0 else np.nan
    atrs=df['ATR_%'].dropna() if 'ATR_%' in df else pd.Series(dtype=float)
    volreg=np.nan
    if len(atrs)>=60:
        hist=atrs.tail(252); volreg=float((hist<=atrp).mean()*100)
    # Participation: up-volume vs down-volume over one month.
    x=df.tail(20); ch=x['Close'].diff(); vol=x['Volume'] if 'Volume' in x else pd.Series(0,index=x.index)
    up=float(vol[ch>0].sum()); down=float(vol[ch<0].sum()); ud=up/down if down>0 else np.nan
    # Gap frequency matters most for equities; still report observation for all.
    prev=df['Close'].shift(1); gaps=((df['Open']/prev-1).abs()>0.02).tail(63).sum() if 'Open' in df else 0
    avdist=(p/avwap-1)*100 if pd.notna(avwap) and avwap else np.nan
    vpdist=(p/vpoc-1)*100 if pd.notna(vpoc) and vpoc else np.nan

    score=50
    score += 16 if structure=='HH / HL' else -16 if structure=='LH / LL' else 0
    score += 12 if weekly=='Bullish' else -12 if weekly=='Bearish' else 0
    if pd.notna(avdist): score += 8 if 0<=avdist<=8 else 3 if avdist>8 else -8
    if pd.notna(rv): score += 6 if rv>=1.25 else -3 if rv<.65 else 0
    if pd.notna(ud): score += 7 if ud>=1.25 else -7 if ud<=.75 else 0
    if pd.notna(rsi): score += 5 if 45<=rsi<=68 else -5 if rsi>=80 else 0
    if pd.notna(volreg): score -= 6 if volreg>=90 else 0
    score=int(clamp(score))

    participation='Accumulation' if pd.notna(ud) and ud>=1.25 else 'Distribution' if pd.notna(ud) and ud<=.75 else 'Balanced'
    volatility='High' if pd.notna(volreg) and volreg>=80 else 'Low' if pd.notna(volreg) and volreg<=20 else 'Normal'
    location='Above AVWAP' if pd.notna(avdist) and avdist>=0 else 'Below AVWAP' if pd.notna(avdist) else 'N/D'
    return {
        'TA_Quality_Score':score,'Market_Structure':structure,'Weekly_State':weekly,
        'FourH_State':'N/A (daily feed)','Last_Swing_High':last_sh,'Last_Swing_Low':last_sl,
        'Anchored_VWAP':round(avwap,4) if pd.notna(avwap) else np.nan,
        'AVWAP_Anchor':str(anchor.date()) if hasattr(anchor,'date') else 'N/D',
        'Dist_AVWAP_%':round(avdist,2) if pd.notna(avdist) else np.nan,
        'Volume_Profile_POC_Proxy':round(vpoc,4) if pd.notna(vpoc) else np.nan,
        'Dist_Volume_POC_%':round(vpdist,2) if pd.notna(vpdist) else np.nan,
        'Relative_Volume_20d':round(rv,2) if pd.notna(rv) else np.nan,
        'Up_Down_Volume_20d':round(ud,2) if pd.notna(ud) else np.nan,
        'Participation':participation,'Volatility_Regime':volatility,
        'ATR_Percentile_1y':round(volreg,1) if pd.notna(volreg) else np.nan,
        'Gap_Count_2pct_63d':int(gaps),'Technical_Location':location,
        'TA_Data_Note':'AVWAP uses a reproducible recent-low anchor; Volume Profile is a daily-bar proxy, not tick-level exchange volume.'
    }
