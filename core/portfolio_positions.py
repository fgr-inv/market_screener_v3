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


def apply_live_prices(detail, live_prices=None):
    """Overlay current quotes and recalculate market-value weights.

    Declared percentage positions intentionally remain fixed. Quantity-based
    portfolios move with their current quotes.  The function is pure so the UI,
    agents and tests all use the same financial calculation.
    """
    if detail is None or detail.empty:
        return pd.DataFrame() if detail is None else detail.copy()
    live_prices=live_prices or {}
    out=detail.copy()
    for index,row in out.iterrows():
        ticker=str(row.get('Ticker','')).upper().strip()
        quote=_finite(live_prices.get(ticker))
        if quote is None or quote<=0:
            continue
        out.at[index,'Price']=quote
        quantity=_finite(row.get('Quantity')) or 0.0
        out.at[index,'Market Value']=quantity*quote if quantity>0 else None

    explicit=out['Declared Allocation %'].notna()
    explicit_total=float(pd.to_numeric(out.loc[explicit,'Declared Allocation %'],errors='coerce').fillna(0).sum())
    if explicit_total>100.000001:
        return out
    if explicit.any():
        out['Weight %']=pd.to_numeric(out['Declared Allocation %'],errors='coerce').fillna(0.0)
        remainder=max(0.0,100.0-explicit_total)
        variable=~explicit & pd.to_numeric(out['Market Value'],errors='coerce').notna()
        variable &= pd.to_numeric(out['Market Value'],errors='coerce')>0
        total=float(pd.to_numeric(out.loc[variable,'Market Value'],errors='coerce').sum())
        if total>0 and remainder>0:
            out.loc[variable,'Weight %']=pd.to_numeric(out.loc[variable,'Market Value'])/total*remainder
    else:
        values=pd.to_numeric(out['Market Value'],errors='coerce').fillna(0.0)
        total=float(values.sum())
        out['Weight %']=values/total*100 if total>0 else 0.0
    return out


def portfolio_weight_alerts(detail, position_limit_pct=10.0, sector_limit_pct=30.0,
                            target_groups=None):
    """Return deterministic concentration and target-allocation observations."""
    if detail is None or detail.empty or 'Weight %' not in detail:
        return []
    alerts=[]
    weights=pd.to_numeric(detail['Weight %'],errors='coerce').fillna(0.0)
    for (_,row),weight in zip(detail.iterrows(),weights):
        if weight>=float(position_limit_pct):
            alerts.append({'level':'warning','kind':'POSITION_CONCENTRATION','label':str(row.get('Ticker','')),
                           'value_pct':round(float(weight),2),
                           'message':f"{row.get('Ticker','')} representa {weight:.2f}% de la cartera, por encima del límite de {position_limit_pct:.1f}%."})
    if 'Sector' in detail:
        sectors=detail.assign(_weight=weights).groupby('Sector',dropna=False)['_weight'].sum()
        for sector,weight in sectors.items():
            if float(weight)>=float(sector_limit_pct):
                alerts.append({'level':'warning','kind':'SECTOR_CONCENTRATION','label':str(sector),
                               'value_pct':round(float(weight),2),
                               'message':f"{sector} concentra {weight:.2f}% de la cartera, por encima del límite de {sector_limit_pct:.1f}%."})
    ticker_weights={str(row.get('Ticker','')).upper():float(weight) for (_,row),weight in zip(detail.iterrows(),weights)}
    for group in target_groups or []:
        tickers={str(t).upper() for t in group.get('tickers',[])}
        current=sum(ticker_weights.get(t,0.0) for t in tickers)
        target=_finite(group.get('target_pct'))
        if target is None: continue
        delta=current-target
        alerts.append({'level':'info','kind':'TARGET_GROUP','label':str(group.get('name','Grupo')),
                       'value_pct':round(current,2),'target_pct':round(target,2),'delta_pct':round(delta,2),
                       'message':f"{group.get('name','Grupo')}: {current:.2f}% frente al objetivo de {target:.2f}% ({delta:+.2f} pp)."})
    return alerts


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
