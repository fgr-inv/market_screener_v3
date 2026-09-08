"""Transparent proxy-factor diagnostics for portfolio and candidate risk."""
from __future__ import annotations

import math
import pandas as pd


FACTOR_PROXIES={'MARKET':'SPY','GROWTH_TECH':'QQQ','SMALL_CAP':'IWM',
                'DURATION':'TLT','USD':'UUP','CREDIT':'HYG'}


def _close(frame):
    if frame is None or frame.empty or 'Close' not in frame: return pd.Series(dtype=float)
    values=pd.to_numeric(frame['Close'],errors='coerce').dropna()
    return values[~values.index.duplicated(keep='last')].sort_index()


def _finite(value):
    try:
        number=float(value)
        return number if math.isfinite(number) else None
    except Exception: return None


def factor_profile(ticker, histories, lookback=126):
    asset=_close(histories.get(str(ticker).upper())).pct_change().rename('asset')
    exposures={}; correlations={}
    for factor,proxy in FACTOR_PROXIES.items():
        benchmark=_close(histories.get(proxy)).pct_change().rename('factor')
        joined=pd.concat([asset,benchmark],axis=1).dropna().tail(lookback)
        if len(joined)<30: exposures[factor]=None; correlations[factor]=None; continue
        variance=float(joined['factor'].var())
        beta=None if variance<=0 else float(joined.cov().loc['asset','factor']/variance)
        exposures[factor]=None if beta is None else round(beta,3)
        correlation=_finite(joined.corr().loc['asset','factor'])
        correlations[factor]=None if correlation is None else round(correlation,3)
    candidates={key:abs(value) for key,value in correlations.items() if value is not None and key!='MARKET'}
    dominant=max(candidates,key=candidates.get) if candidates else 'UNCLASSIFIED'
    return {'ticker':str(ticker).upper(),'lookback_sessions':lookback,
            'market_beta':exposures.get('MARKET'),'dominant_factor':dominant,
            'factor_betas':exposures,'factor_correlations':correlations,
            'method':'Liquid ETF proxies; descriptive risk diagnostics, not causal factor attribution.'}


def build_factor_risk_context(portfolio_rows, histories):
    rows=list(portfolio_rows or []); aggregate={key:0.0 for key in FACTOR_PROXIES}; known=0.0
    factor_weights={key:0.0 for key in FACTOR_PROXIES}
    profiles={}
    for row in rows:
        ticker=str(row.get('ticker','')).upper(); weight=float(row.get('planned_weight_pct') or 0)
        if not ticker or weight<=0: continue
        profile=factor_profile(ticker,histories); profiles[ticker]=profile; known+=weight
        for factor,beta in profile['factor_betas'].items():
            if beta is not None: aggregate[factor]+=weight*beta/100
        dominant=profile['dominant_factor']
        if dominant in factor_weights: factor_weights[dominant]+=weight
    return {'profiles':profiles,'portfolio_factor_betas':{key:round(value,3) for key,value in aggregate.items()},
            'dominant_factor_weights_pct':{key:round(value,2) for key,value in factor_weights.items()},
            'known_weight_pct':round(known,2),'proxy_warning':'ETF proxy exposures can overlap and do not sum to 100%.'}
