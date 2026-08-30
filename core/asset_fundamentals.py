import numpy as np
import pandas as pd
import requests
import streamlit as st
from core.utils import clamp
from core.fx_macro import fx_carry_context
from core.asset_models import (
    normalize_asset_type, effective_asset_type, CREDIT_ETFS, YIELD_INDEXES,
    ENERGY_COMMODITIES, PRECIOUS_METALS, INDUSTRIAL_METALS, AGRICULTURE,
)


def _close(df):
    if df is None or df.empty or 'Close' not in df: return pd.Series(dtype=float)
    return df['Close'].dropna()

def _ret(df,d):
    c=_close(df); return np.nan if len(c)<=d else float(c.iloc[-1]/c.iloc[-(d+1)]-1)

def _ratio(a,b,d):
    x,y=_close(a),_close(b); n=min(len(x),len(y))
    if n<=d: return np.nan
    return float((x.iloc[-1]/y.iloc[-1])/(x.iloc[-(d+1)]/y.iloc[-(d+1)])-1)

def _delta(df,d):
    c=_close(df); return np.nan if len(c)<=d else float(c.iloc[-1]-c.iloc[-(d+1)])

def _yield_bps(df,d=20):
    c=_close(df)
    if len(c)<=d: return np.nan
    delta=float(c.iloc[-1]-c.iloc[-(d+1)])
    # Yahoo Treasury indices (^TNX/^FVX/^IRX) are commonly quoted as yield x10.
    scale=10.0 if abs(float(c.iloc[-1]))>15 else 100.0
    return delta*scale

def _m(m,key,default=50):
    v=m.get(key,default)
    try: return float(v)
    except Exception: return float(default)

@st.cache_data(ttl=1800, show_spinner=False)
def _coingecko_global():
    try:
        r=requests.get('https://api.coingecko.com/api/v3/global',timeout=10,headers={'User-Agent':'Mozilla/5.0'}); r.raise_for_status()
        d=r.json().get('data',{})
        return {'btc_dominance':d.get('market_cap_percentage',{}).get('btc',np.nan),'mcap_change_24h':d.get('market_cap_change_percentage_24h_usd',np.nan)}
    except Exception:
        return {'btc_dominance':np.nan,'mcap_change_24h':np.nan}


def commodity_context(ticker,pm,macro):
    t=ticker.upper(); own=pm.get(ticker); dollar=pm.get('UUP'); gold=pm.get('GLD'); copper=pm.get('HG=F'); oil=pm.get('CL=F')
    score=50; r20=_ret(own,20); r63=_ret(own,63); d20=_ret(dollar,20)
    if pd.notna(r20): score += 8 if r20>.05 else -8 if r20<-.06 else 0
    if pd.notna(r63): score += 7 if r63>.10 else -7 if r63<-.12 else 0
    if pd.notna(d20): score += 7 if d20<-.02 else -7 if d20>.03 else 0
    growth=_m(macro,'Slow_Growth',_m(macro,'Growth')); infl=_m(macro,'Slow_Inflation_Pressure',_m(macro,'Inflation_Pressure')); rates=_m(macro,'Rates')

    if t in ENERGY_COMMODITIES:
        score += round((growth-50)*.15)+round((infl-50)*.18)
        framework='Energy commodity: supply-demand/inventories + curve/positioning + growth/inflation + USD + trend.'
    elif t in PRECIOUS_METALS:
        # Falling yields / softer USD tend to help precious metals; risk hedging can also matter.
        score += round((rates-50)*.18)+round((infl-50)*.10)
        framework='Precious metal: real-rate/yield regime + USD + inflation/risk hedge demand + positioning + trend.'
    elif t in INDUSTRIAL_METALS:
        cg=_ratio(copper,gold,20)
        if pd.notna(cg): score += 12 if cg>.03 else -12 if cg<-.04 else 0
        score += round((growth-50)*.25)
        framework='Industrial metal: global growth/cycle + copper/gold + USD + inventories/positioning + trend.'
    elif t in AGRICULTURE:
        # Public price-only model cannot honestly infer weather/inventories; keep macro weight modest.
        score += round((infl-50)*.10)
        framework='Agriculture: weather/supply + inventories/seasonality + USD + positioning + trend. Weather/inventory feed is not inferred from price.'
    else:
        score += round((growth-50)*.10)
        framework='Commodity: supply-demand + curve/positioning + USD + macro regime + trend.'
    return {'Asset_Context_Score':int(clamp(score)),'Framework':framework,'20d_Return':r20,'63d_Return':r63,'Dollar_20d':d20}


def crypto_context(ticker,pm,macro):
    own=pm.get(ticker); spy=pm.get('SPY'); dollar=pm.get('UUP'); btc=pm.get('BTC-USD')
    score=50; r20=_ret(own,20); r63=_ret(own,63); rel_spy=_ratio(own,spy,63); d20=_ret(dollar,20)
    rel_btc=np.nan if ticker.upper().startswith('BTC') else _ratio(own,btc,63)
    if pd.notna(r20): score += 9 if r20>.10 else -9 if r20<-.12 else 0
    if pd.notna(r63): score += 8 if r63>.20 else -8 if r63<-.18 else 0
    if pd.notna(rel_spy): score += 6 if rel_spy>.10 else -6 if rel_spy<-.10 else 0
    if pd.notna(rel_btc): score += 8 if rel_btc>.08 else -8 if rel_btc<-.10 else 0
    score += round((_m(macro,'Risk_Appetite')-50)*.16)+round((_m(macro,'Liquidity')-50)*.20)
    if pd.notna(d20): score += 6 if d20<-.02 else -6 if d20>.03 else 0
    cg=_coingecko_global()
    if pd.notna(cg['mcap_change_24h']): score += 3 if cg['mcap_change_24h']>2 else -3 if cg['mcap_change_24h']<-2 else 0
    return {'Asset_Context_Score':int(clamp(score)),'Framework':'Crypto: liquidity + risk appetite + USD + BTC-relative strength for alts + market breadth/derivatives + weekly cycle.',
            '20d_Return':r20,'63d_Return':r63,'RS_vs_SPY_63d':rel_spy,'RS_vs_BTC_63d':rel_btc,'BTC_Dominance':cg['btc_dominance'],'Crypto_MCap_24h_%':cg['mcap_change_24h']}


def bond_context(ticker,pm,macro):
    t=ticker.upper(); own=pm.get(ticker); r20=_ret(own,20); r63=_ret(own,63); tnx=pm.get('^TNX'); y20bps=_yield_bps(tnx,20)
    score=50
    if t in YIELD_INDEXES:
        ownbps=_yield_bps(own,20)
        # Context score here is strength of the rates move, not attractiveness of duration.
        if pd.notna(ownbps): score += 16 if ownbps>15 else -16 if ownbps<-15 else 0
        score += round((_m(macro,'Slow_Inflation_Pressure',_m(macro,'Inflation_Pressure'))-50)*.12)
        return {'Asset_Context_Score':int(clamp(score)),'Framework':'Rates index: yield level/direction + inflation/policy expectations + curve. Score describes yield regime, not bond-price attractiveness.',
                'Yield_20d_bps':ownbps,'US10Y_20d_bps':y20bps}
    if pd.notna(r20): score += 7 if r20>.025 else -7 if r20<-.025 else 0
    if t in CREDIT_ETFS:
        credit=_m(macro,'Credit'); growth=_m(macro,'Slow_Growth',_m(macro,'Growth'))
        score += round((credit-50)*.30)+round((growth-50)*.12)
        hyg_ief=_ratio(pm.get('HYG'),pm.get('IEF'),20)
        if pd.notna(hyg_ief): score += 8 if hyg_ief>.01 else -8 if hyg_ief<-.02 else 0
        fw='Credit bond: spreads/credit conditions + growth/default risk + carry/duration + total-return trend.'
    else:
        rates=_m(macro,'Rates'); infl=_m(macro,'Slow_Inflation_Pressure',_m(macro,'Inflation_Pressure')); policy=_m(macro,'Slow_Policy',50)
        score += round((rates-50)*.28)+round((50-infl)*.12)+round((policy-50)*.10)
        if pd.notna(y20bps): score += 9 if y20bps<-12 else -9 if y20bps>12 else 0
        fw='Duration bond: yield direction + inflation/policy expectations + curve/real-rate regime + total-return trend.'
    return {'Asset_Context_Score':int(clamp(score)),'Framework':fw,'20d_Return':r20,'63d_Return':r63,'US10Y_20d_bps':y20bps}


def fx_context(ticker,pm,macro):
    t=ticker.upper(); own=pm.get(ticker); r20=_ret(own,20); r63=_ret(own,63); d20=_ret(pm.get('UUP'),20)
    score=50
    if pd.notna(r20): score += 9 if r20>.02 else -9 if r20<-.02 else 0
    if pd.notna(r63): score += 7 if r63>.04 else -7 if r63<-.04 else 0
    # USD factor direction depends on whether USD is base or quote currency.
    if pd.notna(d20):
        if t.startswith('USD'): score += 8 if d20>.02 else -8 if d20<-.02 else 0
        elif 'USD' in t: score += 8 if d20<-.02 else -8 if d20>.02 else 0
    risk=_m(macro,'Risk_Appetite')
    if t.startswith(('AUD','NZD')): score += round((risk-50)*.10)
    if t.startswith(('JPY','CHF')): score += round((50-risk)*.08)
    carry=fx_carry_context(ticker)
    if carry.get('available'):
        spread=carry.get('Carry_Spread_pp',np.nan)
        if pd.notna(spread): score += int(clamp(spread*3,-10,10))
    return {'Asset_Context_Score':int(clamp(score)),'Framework':'FX: relative policy/carry + growth/inflation differentials + USD/risk factor + trend/volatility.',
            '20d_Return':r20,'63d_Return':r63,'Dollar_20d':d20,
            'Base_Policy_Rate':carry.get('Base_Policy_Rate',np.nan),'Quote_Policy_Rate':carry.get('Quote_Policy_Rate',np.nan),
            'Carry_Differential':carry.get('Carry_Spread_pp',np.nan),'Carry_Score':carry.get('Carry_Score',np.nan),
            'Carry_Data':('LIVE / '+str(carry.get('Base_Rate_Source',''))+' + '+str(carry.get('Quote_Rate_Source',''))) if carry.get('available') else 'N/A (foreign policy/yield feed unavailable)'}


def etf_context(ticker,pm,macro):
    own=pm.get(ticker); r20=_ret(own,20); r63=_ret(own,63); score=50
    if pd.notna(r20): score += 10 if r20>.03 else -10 if r20<-.03 else 0
    if pd.notna(r63): score += 10 if r63>.08 else -10 if r63<-.08 else 0
    score += round((_m(macro,'Macro_Score')-50)*.20)
    return {'Asset_Context_Score':int(clamp(score)),'Framework':'ETF/index: underlying exposure + breadth/trend + relative strength + macro regime. Corporate ratios are not applied to the fund/index itself.','20d_Return':r20,'63d_Return':r63}




def equity_context_score(row):
    """Observed market-context score for an equity.

    This is deliberately separate from corporate fundamentals. It combines the
    stock's sector backdrop, macro fit, relative strength and trend using only
    fields already computed by the screener, so it adds no external API calls.
    Missing components are ignored and the remaining weights are renormalized.
    """
    components=[
        ('Sector_Score',0.35),
        ('Macro_Fit',0.35),
        ('RS_Percentile',0.20),
        ('Trend_Score',0.10),
    ]
    vals=[]
    for key,w in components:
        try:
            v=float(row.get(key,np.nan))
            if pd.notna(v): vals.append((v,w))
        except Exception:
            pass
    if not vals:
        return {'Asset_Context_Score':np.nan,'Framework':'Equity context unavailable: no observed sector, macro, RS or trend inputs.'}
    denom=sum(w for _,w in vals)
    score=sum(v*w for v,w in vals)/denom
    return {
        'Asset_Context_Score':int(np.floor(clamp(score)+0.5)),
        'Framework':'Equity market context: sector strength + sector macro fit + relative strength + trend. Corporate quality/valuation are scored separately.',
        'Context_Inputs':','.join(key for key,w in components if any(k==key for k,_w in components) and pd.notna(row.get(key,np.nan)))
    }

def get_asset_context(ticker,asset_type,pm,macro):
    typ=effective_asset_type(ticker,normalize_asset_type(asset_type))
    if typ=='Commodity': return commodity_context(ticker,pm,macro)
    if typ=='Cripto': return crypto_context(ticker,pm,macro)
    if typ=='Bono/Tasa': return bond_context(ticker,pm,macro)
    if typ=='Forex': return fx_context(ticker,pm,macro)
    if typ in {'ETF','Índice'}: return etf_context(ticker,pm,macro)
    return {'Asset_Context_Score':np.nan,'Framework':'Corporate fundamentals are handled by the sector-aware equity model.'}
