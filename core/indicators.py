
import numpy as np
import pandas as pd

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()

def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().dropna(subset=["Open","High","Low","Close"])
    c = out["Close"]
    for span in [20,21,50,62,79]:
        out[f"EMA{span}"] = c.ewm(span=span, adjust=False).mean()
    out["SMA20"] = c.rolling(20).mean()
    out["SMA50"] = c.rolling(50).mean()
    out["SMA100"] = c.rolling(100).mean()
    out["SMA200"] = c.rolling(200).mean()
    out["ATR10"] = atr(out,10)
    out["ATR14"] = atr(out,14)
    out["ATR_%"] = out["ATR14"] / c * 100
    out["KC_Upper"] = out["EMA20"] + 2*out["ATR10"]
    out["KC_Lower"] = out["EMA20"] - 2*out["ATR10"]
    out["RSI14"] = rsi(c,14)
    out["Vol20"] = out["Volume"].rolling(20).mean()
    out["High20"] = out["High"].rolling(20).max()
    out["High20_prev"] = out["High20"].shift(1)
    out["Low20"] = out["Low"].rolling(20).min()
    out["High50"] = out["High"].rolling(50).max()
    out["Low50"] = out["Low"].rolling(50).min()
    out["High252"] = out["High"].rolling(252).max()
    out["Low252"] = out["Low"].rolling(252).min()
    out["Ret5"] = c.pct_change(5)*100
    out["Ret20"] = c.pct_change(20)*100
    out["Ret63"] = c.pct_change(63)*100
    out["Ret126"] = c.pct_change(126)*100
    out["Drawdown_%"] = (c/c.cummax()-1)*100
    return out
