"""Manual portfolio import with no broker or credential dependency."""
from __future__ import annotations

import pandas as pd


def normalize_positions_csv(file_obj):
    df=pd.read_csv(file_obj)
    aliases={
        'symbol':'ticker','Symbol':'ticker','Ticker':'ticker','ticker':'ticker',
        'qty':'quantity','Qty':'quantity','Quantity':'quantity','quantity':'quantity',
        'avg_entry_price':'avg_cost','Avg Cost':'avg_cost','Average Cost':'avg_cost','avg_cost':'avg_cost',
    }
    df=df.rename(columns={column:aliases.get(column,column) for column in df.columns})
    if not all(column in df.columns for column in ('ticker','quantity')):
        raise ValueError('CSV must contain ticker/symbol and quantity/qty columns.')
    if 'avg_cost' not in df.columns: df['avg_cost']=0.0
    df['ticker']=df['ticker'].astype(str).str.upper().str.strip()
    df['quantity']=pd.to_numeric(df['quantity'],errors='coerce')
    df['avg_cost']=pd.to_numeric(df['avg_cost'],errors='coerce').fillna(0)
    df=df.dropna(subset=['ticker','quantity'])[['ticker','quantity','avg_cost']]
    df=df[df['ticker']!='']
    # A consolidated export can contain the same underlying at more than one
    # broker. Combine quantities and preserve a quantity-weighted average cost
    # instead of silently overwriting the first account with the second one.
    df['_cost_value']=df['quantity']*df['avg_cost']
    grouped=df.groupby('ticker',as_index=False).agg(quantity=('quantity','sum'),_cost_value=('_cost_value','sum'))
    grouped['avg_cost']=grouped.apply(lambda row:row['_cost_value']/row['quantity'] if row['quantity']>0 else 0.0,axis=1)
    return grouped[['ticker','quantity','avg_cost']]
