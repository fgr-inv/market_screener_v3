from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
CURVE_FILE=ROOT/'data'/'premium'/'commodity_curve.csv'


def load_curve(root_symbol, asof=None):
    if not CURVE_FILE.exists(): return pd.DataFrame()
    df=pd.read_csv(CURVE_FILE)
    df['asof_date']=pd.to_datetime(df['asof_date'],errors='coerce')
    df['expiry']=pd.to_datetime(df['expiry'],errors='coerce')
    x=df[df['root'].astype(str).str.upper()==root_symbol.upper()].copy()
    if x.empty: return x
    if asof is None: asof=x['asof_date'].max()
    d=pd.Timestamp(asof)
    x=x[x['asof_date']==x.loc[x['asof_date']<=d,'asof_date'].max()].sort_values('expiry')
    return x


def curve_metrics(root_symbol, asof=None):
    x=load_curve(root_symbol,asof)
    if len(x)<2:
        return {'available':False,'Term_Structure':'N/D','Front_Second_Spread_%':np.nan,'Annualized_Carry_%':np.nan,'Curve':x}
    p1=float(x.iloc[0]['price']); p2=float(x.iloc[1]['price'])
    spread=(p2/p1-1)*100 if p1 else np.nan
    days=max((x.iloc[1]['expiry']-x.iloc[0]['expiry']).days,1)
    carry=((p2/p1)**(365/days)-1)*100 if p1 and p2>0 else np.nan
    structure='CONTANGO' if p2>p1 else 'BACKWARDATION'
    return {'available':True,'Term_Structure':structure,'Front_Second_Spread_%':spread,'Annualized_Carry_%':carry,'Curve':x}
