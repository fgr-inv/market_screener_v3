"""Normalize quantity-based and percentage-based portfolio positions."""
from __future__ import annotations

import math
import pandas as pd


def _finite(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _last_price(raw):
    if raw is None or not isinstance(raw,pd.DataFrame) or raw.empty or 'Close' not in raw:
        return None
    close=pd.to_numeric(raw['Close'],errors='coerce').dropna()
    return None if close.empty else _finite(close.iloc[-1])


def resolve_position_allocations(positions,price_map=None):
    """Return position weights while preserving percentage allocations exactly.

    Percentage rows consume their declared share. Quantity-only rows share the
    remaining allocation according to current market value. Unused allocation is
    treated as cash. More than 100% is rejected instead of silently normalized.
    """
    price_map=price_map or {}
    if positions is None or positions.empty:
        return pd.DataFrame(),{'status':'EMPTY','basis':'NONE','allocation_total_pct':0.0,'cash_pct':100.0,'dollar_total':None}
    rows=[]
    for _,position in positions.iterrows():
        ticker=str(position.get('ticker','')).upper().strip()
        if not ticker: continue
        allocation=_finite(position.get('allocation_pct'))
        allocation=allocation if allocation is not None and allocation>0 else None
        quantity=_finite(position.get('quantity')) or 0.0
        avg_cost=_finite(position.get('avg_cost')) or 0.0
        price=_last_price(price_map.get(ticker))
        market_value=(quantity*price if price is not None and quantity>0 else None)
        rows.append({'Ticker':ticker,'Sector':str(position.get('sector','Unknown') or 'Unknown'),
                     'Quantity':quantity,'Avg Cost':avg_cost,'Price':price,'Market Value':market_value,
                     'Declared Allocation %':allocation,'Note':str(position.get('note','') or '')})
    detail=pd.DataFrame(rows)
    if detail.empty:
        return detail,{'status':'EMPTY','basis':'NONE','allocation_total_pct':0.0,'cash_pct':100.0,'dollar_total':None}
    explicit=detail['Declared Allocation %'].notna()
    explicit_total=float(detail.loc[explicit,'Declared Allocation %'].sum())
    if explicit_total>100.000001:
        detail['Weight %']=0.0; detail['Allocation Source']='INVALID'
        return detail,{'status':'OVER_ALLOCATED','basis':'ALLOCATION_PCT','allocation_total_pct':explicit_total,
                       'cash_pct':0.0,'dollar_total':None}
    if explicit.any():
        detail['Weight %']=detail['Declared Allocation %'].fillna(0.0)
        detail['Allocation Source']=explicit.map({True:'DECLARED_PERCENTAGE',False:'QUANTITY_REMAINDER'})
        remainder=max(0.0,100.0-explicit_total)
        quantity_mask=~explicit & detail['Market Value'].notna() & (detail['Market Value']>0)
        quantity_total=float(detail.loc[quantity_mask,'Market Value'].sum())
        if quantity_total>0 and remainder>0:
            detail.loc[quantity_mask,'Weight %']=detail.loc[quantity_mask,'Market Value']/quantity_total*remainder
        invested=float(detail['Weight %'].sum())
        basis='MIXED' if (~explicit).any() else 'ALLOCATION_PCT'
        meta={'status':'CURRENT','basis':basis,'allocation_total_pct':invested,
              'cash_pct':max(0.0,100.0-invested),'dollar_total':None}
    else:
        values=pd.to_numeric(detail['Market Value'],errors='coerce').fillna(0.0)
        total=float(values.sum())
        detail['Weight %']=values/total*100 if total>0 else 0.0
        detail['Allocation Source']='MARKET_VALUE'
        meta={'status':'CURRENT' if total>0 else 'UNAVAILABLE','basis':'QUANTITY',
              'allocation_total_pct':100.0 if total>0 else 0.0,'cash_pct':0.0 if total>0 else 100.0,
              'dollar_total':total if total>0 else None}
    return detail,meta
