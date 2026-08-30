
import pandas as pd
def fmt_pct(x,decimals=1):
    if x is None or pd.isna(x): return "N/D"
    x=float(x)
    if abs(x)<=1: x*=100
    return f"{x:.{decimals}f}%"
def fmt_num(x,decimals=2):
    if x is None or pd.isna(x): return "N/D"
    return f"{float(x):,.{decimals}f}"
def fmt_money(x):
    if x is None or pd.isna(x): return "N/D"
    x=float(x); a=abs(x)
    if a>=1e12: return f"${x/1e12:.2f}T"
    if a>=1e9: return f"${x/1e9:.2f}B"
    if a>=1e6: return f"${x/1e6:.2f}M"
    return f"${x:,.2f}"
def clamp(x,lo=0,hi=100):
    return max(lo,min(hi,x))
