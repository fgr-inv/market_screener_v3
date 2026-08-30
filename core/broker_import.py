import io
import os
import pandas as pd
import requests
import streamlit as st


def normalize_positions_csv(file_obj):
    df=pd.read_csv(file_obj)
    aliases={
        'symbol':'ticker','Symbol':'ticker','Ticker':'ticker','ticker':'ticker',
        'qty':'quantity','Qty':'quantity','Quantity':'quantity','quantity':'quantity',
        'avg_entry_price':'avg_cost','Avg Cost':'avg_cost','Average Cost':'avg_cost','avg_cost':'avg_cost',
    }
    df=df.rename(columns={c:aliases.get(c,c) for c in df.columns})
    required=['ticker','quantity']
    if not all(c in df.columns for c in required):
        raise ValueError('CSV must contain ticker/symbol and quantity/qty columns.')
    if 'avg_cost' not in df.columns: df['avg_cost']=0.0
    df['ticker']=df['ticker'].astype(str).str.upper().str.strip()
    df['quantity']=pd.to_numeric(df['quantity'],errors='coerce')
    df['avg_cost']=pd.to_numeric(df['avg_cost'],errors='coerce').fillna(0)
    return df.dropna(subset=['ticker','quantity'])[['ticker','quantity','avg_cost']]


def alpaca_positions():
    try:
        key=str(st.secrets.get('ALPACA_API_KEY',''))
        sec=str(st.secrets.get('ALPACA_SECRET_KEY',''))
        base=str(st.secrets.get('ALPACA_BASE_URL','https://paper-api.alpaca.markets'))
    except Exception:
        key=os.getenv('ALPACA_API_KEY',''); sec=os.getenv('ALPACA_SECRET_KEY',''); base=os.getenv('ALPACA_BASE_URL','https://paper-api.alpaca.markets')
    if not key or not sec: return pd.DataFrame(), 'Missing Alpaca credentials'
    try:
        r=requests.get(base.rstrip('/')+'/v2/positions',headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':sec},timeout=10)
        r.raise_for_status(); d=r.json()
        df=pd.DataFrame(d)
        if df.empty: return df,'OK'
        out=pd.DataFrame({'ticker':df['symbol'],'quantity':pd.to_numeric(df['qty'],errors='coerce'),'avg_cost':pd.to_numeric(df['avg_entry_price'],errors='coerce')})
        return out,'OK'
    except Exception as e:
        return pd.DataFrame(),str(e)[:150]
