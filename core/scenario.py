import numpy as np
import pandas as pd
from core.portfolio_positions import resolve_position_allocations

DEFAULT_SCENARIOS = {
    'Nasdaq -10% / VIX shock': {'QQQ': -0.10, 'SPY': -0.07, 'IWM': -0.08, 'TLT': 0.03, 'GLD': 0.02, 'BTC-USD': -0.18},
    'Rates +100 bps': {'QQQ': -0.09, 'SPY': -0.05, 'IWM': -0.05, 'TLT': -0.12, 'GLD': -0.04, 'XLF': 0.01, 'XLRE': -0.10, 'XLU': -0.08},
    'Recession shock': {'SPY': -0.12, 'QQQ': -0.10, 'IWM': -0.18, 'HYG': -0.10, 'TLT': 0.10, 'GLD': 0.05, 'CL=F': -0.20},
    'Inflation / Oil +25%': {'CL=F': 0.25, 'XLE': 0.15, 'SPY': -0.04, 'QQQ': -0.07, 'TLT': -0.08, 'GLD': 0.07},
    'BTC -30%': {'BTC-USD': -0.30, 'ETH-USD': -0.38, 'MSTR': -0.35, 'COIN': -0.28, 'SPY': -0.02, 'QQQ': -0.03},
}


def _beta(asset, proxy, window=126):
    a=asset['Close'].pct_change().rename('a'); p=proxy['Close'].pct_change().rename('p')
    x=pd.concat([a,p],axis=1).dropna().tail(window)
    if len(x)<30 or x['p'].var()<=0: return np.nan
    return float(x.cov().loc['a','p']/x['p'].var())


def stress_portfolio(positions, price_map, scenario_name, scenario=None):
    if positions is None or positions.empty:
        return {}, pd.DataFrame()
    shocks = scenario or DEFAULT_SCENARIOS.get(scenario_name, {})
    proxy_order = [k for k in ['QQQ','SPY','IWM','XLE','XLRE','XLU','TLT','GLD','BTC-USD','CL=F'] if k in shocks]
    resolved,allocation=resolve_position_allocations(positions,price_map)
    if allocation.get('status')!='CURRENT': return {'Allocation Status':allocation.get('status')},pd.DataFrame()
    rows=[]; total=allocation.get('dollar_total'); pnl=0 if total is not None else np.nan; impact=0
    for _,p in resolved.iterrows():
        t=str(p['Ticker']).upper(); raw=price_map.get(t)
        if raw is None or raw.empty: continue
        value=p.get('Market Value'); weight=float(p.get('Weight %',0) or 0)/100
        if t in shocks:
            shock=float(shocks[t]); method='direct'
        else:
            best=None
            for proxy in proxy_order:
                pr=price_map.get(proxy)
                if pr is None or pr.empty: continue
                b=_beta(raw,pr)
                if pd.notna(b):
                    candidate=(abs(b),proxy,b)
                    if best is None or candidate[0]>best[0]: best=candidate
            if best:
                _,proxy,b=best; shock=float(b)*float(shocks[proxy]); method=f'beta to {proxy}'
            else:
                shock=float(shocks.get('SPY',-0.05)); method='fallback SPY'
        impact+=weight*shock
        est=(float(value)*shock if pd.notna(value) and allocation.get('basis')=='QUANTITY' else np.nan)
        if pd.notna(pnl) and pd.notna(est): pnl+=est
        rows.append({'Ticker':t,'Weight %':weight*100,'Value':value,'Estimated Shock %':shock*100,'Estimated P&L $':est,'Method':method})
    summary={'Scenario':scenario_name,'Portfolio Value':np.nan if total is None else total,
             'Estimated P&L $':pnl,'Estimated Portfolio %':impact*100}
    return summary,pd.DataFrame(rows).sort_values('Estimated Shock %') if rows else pd.DataFrame()
