
import numpy as np, pandas as pd
from core.utils import clamp

def pct_distance(price,ref):
    if ref is None or pd.isna(ref) or ref==0: return np.nan
    return (price/ref-1)*100

def slope_score(series,lookback=10):
    s=series.dropna()
    if len(s)<lookback+1: return 50
    now,old=float(s.iloc[-1]),float(s.iloc[-(lookback+1)])
    if old==0: return 50
    return int(clamp(50+((now/old-1)*100)*10))

def _entry_levels(df,price):
    last=df.iloc[-1]
    atr=float(last["ATR14"]) if pd.notna(last["ATR14"]) else price*.03
    ema62,ema79,sma200=float(last["EMA62"]),float(last["EMA79"]),float(last["SMA200"])
    low20=float(last["Low20"]) if pd.notna(last["Low20"]) else min(ema79,sma200)
    high50=float(last["High50"]) if pd.notna(last["High50"]) else price+2*atr
    high252=float(last["High252"]) if pd.notna(last["High252"]) else high50
    entry_low=max(min(ema62,ema79)*.99,sma200*.995)
    entry_high=max(ema62,ema79)*1.02
    support=max(min(low20,ema79),sma200)
    stop=support-.75*atr
    risk=max(price-stop,atr*.75)
    target=max(high50,min(high252,price+2.5*risk))
    rr=max(target-price,0)/risk if risk>0 else np.nan
    return entry_low,entry_high,stop,target,rr

def analyze_symbol(ticker,df,spy_df=None,sector="Unknown"):
    last=df.iloc[-1]
    price=float(last["Close"]); ema20=float(last["EMA20"]); ema50=float(last["EMA50"])
    ema62=float(last["EMA62"]); ema79=float(last["EMA79"]); sma200=float(last["SMA200"])
    rsi14=float(last["RSI14"]) if pd.notna(last["RSI14"]) else np.nan
    atr_pct=float(last["ATR_%"]) if pd.notna(last["ATR_%"]) else np.nan
    e62,e79,s200=slope_score(df["EMA62"],10),slope_score(df["EMA79"],10),slope_score(df["SMA200"],20)

    if price>ema62>ema79>sma200 and e62>50 and e79>50: trend="Strong Uptrend"
    elif price>sma200 and price>ema62: trend="Early Uptrend"
    elif price>sma200: trend="Neutral"
    else: trend="Downtrend"

    trend_score=0
    trend_score+=28 if price>sma200 else 0
    trend_score+=18 if price>ema62 else 0
    trend_score+=14 if ema62>ema79 else 0
    trend_score+=12 if ema79>sma200 else 0
    trend_score+=int(.12*e62)+int(.08*e79)+int(.08*s200)
    trend_score=int(clamp(trend_score))

    ku=float(last["KC_Upper"]) if pd.notna(last["KC_Upper"]) else np.nan
    kl=float(last["KC_Lower"]) if pd.notna(last["KC_Lower"]) else np.nan
    kpos="Upper/Above" if pd.notna(ku) and price>=ku else "Lower" if pd.notna(kl) and price<=kl else "Middle"

    rv=np.nan
    if pd.notna(last["Vol20"]) and float(last["Vol20"])>0: rv=float(last["Volume"])/float(last["Vol20"])

    rs63=np.nan
    if spy_df is not None and not spy_df.empty:
        close=df["Close"].dropna(); sc=spy_df["Close"].dropna()
        if len(close)>=64 and len(sc)>=64:
            rs63=((price/float(close.iloc[-64])-1)-(float(sc.iloc[-1])/float(sc.iloc[-64])-1))*100

    d62,d79,d200=pct_distance(price,ema62),pct_distance(price,ema79),pct_distance(price,sma200)

    entry=50
    if pd.notna(atr_pct) and atr_pct>0:
        u=abs(d62)/atr_pct
        entry += 25 if u<=.4 else 18 if u<=.8 else 8 if u<=1.4 else -18 if u>=2.5 else 0
    if pd.notna(rsi14):
        entry += 16 if 44<=rsi14<=58 else 9 if 38<=rsi14<44 or 58<rsi14<=65 else -16 if rsi14>=72 else -8 if rsi14<=30 else 0
    entry += 10 if kpos=="Middle" else -12 if kpos=="Upper/Above" else 0
    if -2<=d200<=5: entry+=8
    entry=int(clamp(entry))

    dd=float(last["Drawdown_%"]) if pd.notna(last["Drawdown_%"]) else np.nan
    risk=100
    if pd.notna(atr_pct):
        risk -= 42 if atr_pct>7 else 30 if atr_pct>5 else 18 if atr_pct>3.5 else 10 if atr_pct>2.5 else 0
    if pd.notna(dd):
        risk -= 25 if dd<-40 else 15 if dd<-25 else 7 if dd<-15 else 0
    risk=int(clamp(risk))

    hp=float(last["High20_prev"]) if pd.notna(last["High20_prev"]) else np.nan
    breakout=pd.notna(hp) and price>=hp*.995 and (pd.isna(rv) or rv>=1.0) and trend in {"Strong Uptrend","Early Uptrend"}
    ema_zone=price>sma200 and min(ema62,ema79)*.985<=price<=max(ema62,ema79)*1.035 and (pd.isna(rsi14) or 38<=rsi14<=66)
    pullback=trend=="Strong Uptrend" and -1.5<=d62<=5 and (pd.isna(rsi14) or 40<=rsi14<=65) and kpos!="Upper/Above"
    near200=-1.5<=d200<=4 and (pd.isna(rsi14) or rsi14>=36)
    extended=(pd.notna(rsi14) and rsi14>=72) or kpos=="Upper/Above" or (pd.notna(atr_pct) and d62>=max(10,atr_pct*2.2))

    setup="Uptrend Pullback" if pullback else "EMA62/79 Buy Zone" if ema_zone else "200D Bounce" if near200 else "Breakout / Base" if breakout else "Extended / Trim" if extended else "Watch"
    el,eh,stop,target,rr=_entry_levels(df,price)

    if pd.notna(rr):
        risk=int(clamp(risk-(30 if rr<1 else 20 if rr<1.25 else 12 if rr<1.5 else 0)+(5 if rr>=2.5 else 0)))

    rs_proxy=65 if pd.isna(rs63) else clamp(65+rs63*2)
    technical=int(clamp(.34*trend_score+.34*entry+.16*risk+.16*rs_proxy))

    high252=float(last["High252"]) if pd.notna(last["High252"]) else np.nan
    dh=pct_distance(price,high252) if pd.notna(high252) else np.nan

    notes=[]
    if trend=="Strong Uptrend": notes.append("Estructura alcista de alta calidad.")
    if pullback: notes.append("Pullback controlado.")
    if ema_zone: notes.append("Confluencia EMA62/79.")
    if breakout: notes.append("Breakout/base potencial.")
    if extended: notes.append("Extensión elevada.")
    if pd.notna(rs63) and rs63>0: notes.append("Fuerza relativa positiva vs SPY.")
    if pd.notna(rr) and rr>=2: notes.append("R/R favorable.")

    return {
        "Ticker":ticker,"Sector":sector,"Price":round(price,2),"Trend":trend,
        "Technical_Score":technical,"Trend_Score":trend_score,"Entry_Score":entry,"Risk_Score":risk,
        "EMA20":round(ema20,2),"EMA50":round(ema50,2),"EMA62":round(ema62,2),"EMA79":round(ema79,2),"SMA200":round(sma200,2),
        "Dist_EMA62_%":round(d62,2),"Dist_EMA79_%":round(d79,2),"Dist_SMA200_%":round(d200,2),
        "Dist_52wHigh_%":round(dh,2) if pd.notna(dh) else np.nan,
        "RSI14":round(rsi14,1) if pd.notna(rsi14) else np.nan,"ATR_%":round(atr_pct,2) if pd.notna(atr_pct) else np.nan,
        "Drawdown_%":round(dd,2) if pd.notna(dd) else np.nan,"Rel_Volume":round(float(rv),2) if pd.notna(rv) else np.nan,
        "RS_63d_%":round(float(rs63),2) if pd.notna(rs63) else np.nan,"Keltner_Pos":kpos,"Setup":setup,
        "Scan_Uptrend_Pullback":bool(pullback),"Scan_EMA_Buy_Zone":bool(ema_zone),"Scan_200D_Bounce":bool(near200),
        "Scan_Breakout_Base":bool(breakout),"Scan_Extended_Trim":bool(extended),
        "Entry_Zone":f"${el:,.2f} – ${eh:,.2f}","Invalidation":f"< ${stop:,.2f}","Target":f"${target:,.2f}",
        "RR":rr,"RR_Text":f"{rr:.2f} : 1" if pd.notna(rr) else "N/D",
        "Risk":"Low" if risk>=80 else "Medium" if risk>=55 else "High",
        "Comment":" ".join(notes) or "Sin confluencia suficiente.",
    }

def sector_strength_entry(row):
    rs=50 if pd.isna(row.get("RS_63d_%",np.nan)) else clamp(65+float(row["RS_63d_%"])*2)
    strength=int(clamp(.58*row["Trend_Score"]+.26*rs+.16*row["Risk_Score"]))
    entry=int(row["Entry_Score"])
    status="BUY ZONE" if strength>=75 and entry>=70 else "EXTENDED" if strength>=75 and entry<50 else "WATCH" if strength>=60 and entry>=55 else "WEAK / WAIT"
    return strength,entry,status
