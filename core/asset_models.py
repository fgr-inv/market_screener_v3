"""Asset-class aware analysis models.

The application deliberately does not score every market with an equity template.
Each model keeps a common 0-100 language for the UI, but changes the inputs and
interpretation by asset class (equities, ETFs/indices, crypto, commodities,
fixed income/rates and FX).
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from core.scoring import analyze_symbol, pct_distance, slope_score
from core.utils import clamp
from core.technical_engine_v2 import professional_technical_snapshot


ASSET_TYPE_ALIASES = {
    'Acciones': 'Acción', 'Acción': 'Acción', 'Equity': 'Acción',
    'ETFs': 'ETF', 'ETF': 'ETF',
    'Índices': 'Índice', 'Índice': 'Índice',
    'Cripto': 'Cripto', 'Crypto': 'Cripto',
    'Commodities': 'Commodity', 'Commodity': 'Commodity',
    'Bonos / Tasas': 'Bono/Tasa', 'Bono/Tasa': 'Bono/Tasa', 'Bonds': 'Bono/Tasa',
    'Forex': 'Forex', 'FX': 'Forex',
    'Personalizado': 'Otro', 'Otro': 'Otro', 'Auto': 'Otro',
}

BOND_ETFS = {'TLT','IEF','SHY','HYG','LQD','TIP','BND','AGG','JNK','EMB','MUB'}
CREDIT_ETFS = {'HYG','LQD','JNK','EMB'}
DURATION_ETFS = {'TLT','IEF','SHY','TIP','BND','AGG'}
COMMODITY_ETFS = {'GLD','SLV','USO','UNG','DBA','DBC','PDBC'}
EQUITY_INDEX_ETFS = {'SPY','QQQ','IWM','DIA','RSP','VTI','VOO','VT','ACWI','EFA','EEM'}
YIELD_INDEXES = {'^TNX','^TYX','^FVX','^IRX'}

ENERGY_COMMODITIES = {'CL=F','BZ=F','NG=F','RB=F','HO=F','USO','UNG'}
PRECIOUS_METALS = {'GC=F','SI=F','PL=F','PA=F','GLD','SLV'}
INDUSTRIAL_METALS = {'HG=F'}
AGRICULTURE = {'ZC=F','ZW=F','ZS=F','KC=F','SB=F','CT=F','DBA'}


def normalize_asset_type(asset_type: str | None) -> str:
    return ASSET_TYPE_ALIASES.get(str(asset_type or '').strip(), str(asset_type or 'Otro').strip() or 'Otro')


def infer_etf_subtype(ticker: str) -> str:
    t=ticker.upper().strip()
    if t in CREDIT_ETFS: return 'Credit ETF'
    if t in DURATION_ETFS: return 'Duration ETF'
    if t in COMMODITY_ETFS: return 'Commodity ETF'
    if t in EQUITY_INDEX_ETFS: return 'Equity ETF'
    return 'ETF'


def effective_asset_type(ticker: str, asset_type: str) -> str:
    """Normalize UI types and route known ETFs to their economic engine."""
    typ=normalize_asset_type(asset_type)
    t=ticker.upper().strip()
    if typ=='ETF':
        subtype=infer_etf_subtype(t)
        if subtype in {'Credit ETF','Duration ETF'}: return 'Bono/Tasa'
        if subtype=='Commodity ETF': return 'Commodity'
    return typ


def professional_framework(ticker: str, asset_type: str, sector: str='Other') -> str:
    typ=effective_asset_type(ticker,asset_type); t=ticker.upper().strip()
    if typ=='Acción':
        sector_notes={
            'Technology':'growth, margins, FCF, revisions, valuation and relative strength',
            'Communication Services':'growth, monetization/margins, FCF, revisions and valuation',
            'Consumer Discretionary':'same-store/demand sensitivity, margins, FCF, leverage and valuation',
            'Consumer Staples':'organic growth, margins, pricing power, FCF, leverage and valuation',
            'Financials':'ROE, balance-sheet quality, earnings/revisions and price-to-book/valuation',
            'Real Estate':'rates, leverage, cash generation and valuation; REITs ideally require FFO/AFFO',
            'Utilities':'rates, leverage, regulated growth/cash flow and valuation',
            'Energy':'commodity cycle, FCF, balance sheet, capital discipline and valuation',
            'Materials':'cycle/growth, margins, FCF, leverage and valuation',
            'Industrials':'orders/cycle, margins, FCF, revisions and valuation',
            'Health Care':'pipeline/product growth, margins, FCF, revisions and valuation',
        }
        return 'Equity: '+sector_notes.get(sector,'quality, growth, FCF, revisions, valuation, sector leadership and technical regime')+'.'
    if typ=='Cripto': return 'Crypto: asset-specific model (BTC/ETH/L1-L2/DeFi/stablecoin/speculative) combining macro, network/on-chain, tokenomics, derivatives, relative strength and technical cycle.'
    if typ=='Commodity':
        if t in ENERGY_COMMODITIES: return 'Energy commodity: curve/inventories, supply-demand, USD, inflation/growth and positioning plus price trend.'
        if t in PRECIOUS_METALS: return 'Precious metal: real-rate/USD regime, inflation/risk hedging, positioning and trend.'
        if t in INDUSTRIAL_METALS: return 'Industrial metal: global growth, China/cycle proxy, USD, inventories/positioning and trend.'
        if t in AGRICULTURE: return 'Agriculture: weather/supply, inventories/seasonality, USD, positioning and trend.'
        return 'Commodity: supply-demand, curve/positioning, USD, macro regime and trend.'
    if typ=='Bono/Tasa':
        if t in CREDIT_ETFS: return 'Credit: spread/risk regime, growth/default risk, carry and duration plus technicals.'
        if t in YIELD_INDEXES: return 'Rates: level and direction of yields, inflation/policy expectations and curve regime; rising yield is not scored as a bond-price uptrend.'
        return 'Duration: yield direction, inflation/policy expectations, curve and real-rate regime plus total-return trend.'
    if typ=='Forex': return 'FX: relative monetary policy/carry, growth/inflation differentials, risk regime, USD factor, trend and volatility. Carry is limited when foreign rate data is unavailable.'
    if typ=='Índice': return 'Index: breadth, trend, volatility, relative strength and macro/financial-conditions regime; no company valuation is applied.'
    if typ=='ETF': return 'ETF: analyze the underlying exposure, breadth/trend, relative strength and macro regime; never apply corporate EPS/PE as if it were a company.'
    return 'Cross-asset technical model with volatility-normalized trend and explicit data-coverage limits.'


def _safe_last(df, col, default=np.nan):
    try:
        v=df[col].iloc[-1]
        return float(v) if pd.notna(v) else default
    except Exception:
        return default


def _weekly_cycle(df: pd.DataFrame) -> dict:
    """Weekly cycle diagnostics using only OHLC close; works for 24/7 and weekday markets."""
    if df is None or df.empty or 'Close' not in df:
        return {'Weekly_EMA21':np.nan,'Weekly_SMA40':np.nan,'Weekly_SMA200':np.nan,'Weekly_Cycle_Score':50}
    c=df['Close'].dropna()
    if not isinstance(c.index,pd.DatetimeIndex) or c.empty:
        return {'Weekly_EMA21':np.nan,'Weekly_SMA40':np.nan,'Weekly_SMA200':np.nan,'Weekly_Cycle_Score':50}
    w=c.resample('W').last().dropna()
    if len(w)<22:
        return {'Weekly_EMA21':np.nan,'Weekly_SMA40':np.nan,'Weekly_SMA200':np.nan,'Weekly_Cycle_Score':50}
    e21=w.ewm(span=21,adjust=False).mean(); s40=w.rolling(40).mean(); s200=w.rolling(200).mean()
    p=float(w.iloc[-1]); score=50
    if pd.notna(e21.iloc[-1]): score += 16 if p>e21.iloc[-1] else -16
    if len(e21)>5 and pd.notna(e21.iloc[-5]): score += 8 if e21.iloc[-1]>e21.iloc[-5] else -8
    if pd.notna(s40.iloc[-1]): score += 10 if p>s40.iloc[-1] else -10
    if pd.notna(s200.iloc[-1]): score += 12 if p>s200.iloc[-1] else -12
    return {'Weekly_EMA21':float(e21.iloc[-1]),'Weekly_SMA40':float(s40.iloc[-1]) if pd.notna(s40.iloc[-1]) else np.nan,
            'Weekly_SMA200':float(s200.iloc[-1]) if pd.notna(s200.iloc[-1]) else np.nan,
            'Weekly_Cycle_Score':int(clamp(score))}


def _atr_units(price: float, ref: float, atr_pct: float) -> float:
    if not all(pd.notna(x) for x in [price,ref,atr_pct]) or ref==0 or atr_pct<=0: return np.nan
    return pct_distance(price,ref)/atr_pct


def _common_output(base: dict, model: str, framework: str, trend_score: float, entry_score: float, risk_score: float, technical: float, setup: str, comment: str):
    base.update({
        'Analysis_Model':model,'Professional_Framework':framework,
        'Trend_Score':int(clamp(round(trend_score))), 'Entry_Score':int(clamp(round(entry_score))),
        'Risk_Score':int(clamp(round(risk_score))), 'Technical_Score':int(clamp(round(technical))),
        'Setup':setup,'Comment':comment,
    })
    return base


def _equity_like(ticker,df,benchmark,sector,asset_type):
    base=analyze_symbol(ticker,df,benchmark,sector)
    typ=normalize_asset_type(asset_type)
    model='Equity' if typ=='Acción' else 'Index/ETF'
    framework=professional_framework(ticker,typ,sector)
    if typ in {'ETF','Índice'}:
        # Corporate-volume data is often less informative for indices. Emphasize trend/RS/risk.
        rs=50 if pd.isna(base.get('RS_63d_%')) else clamp(50+base['RS_63d_%']*2.5)
        technical=.44*base['Trend_Score']+.25*base['Entry_Score']+.18*base['Risk_Score']+.13*rs
        base['Technical_Score']=int(clamp(technical))
        base['Analysis_Model']='Index/ETF'
        base['Professional_Framework']=framework
    else:
        base['Analysis_Model']='Equity'
        base['Professional_Framework']=framework
    return base


def _crypto(ticker,df,benchmark,sector):
    # Crypto execution is regime-aware: structural/cycle opportunity is separated from timing.
    from core.crypto_professional import professional_crypto_cycle
    base=analyze_symbol(ticker,df,benchmark,sector)
    # Keep the core scorer deterministic/offline; live derivatives/on-chain enrich the dedicated crypto views.
    cyc=professional_crypto_cycle(ticker,df,{})
    trend=cyc.get('Structural_Trend_Score',50); entry=cyc.get('Entry_Timing_Score',50)
    atrp=_safe_last(df,'ATR_%'); dd=_safe_last(df,'Drawdown_%'); risk=100
    if pd.notna(atrp): risk -= 38 if atrp>8 else 26 if atrp>6 else 16 if atrp>4.5 else 7 if atrp>3 else 0
    if pd.notna(dd): risk -= 18 if dd<-45 else 10 if dd<-30 else 4 if dd<-20 else 0
    if cyc.get('Leverage_Risk')=='HIGH': risk-=18
    elif cyc.get('Leverage_Risk')=='MODERATE': risk-=7
    risk=clamp(risk)
    technical=.34*trend+.24*entry+.18*risk+.24*cyc.get('Cycle_Score',50)
    setup=cyc.get('Entry_Type','CRYPTO WATCH')
    base['Trend']='Strong Uptrend' if trend>=78 else 'Uptrend' if trend>=62 else 'Neutral' if trend>=45 else 'Downtrend'
    # Extension is a risk flag, not an automatic trim signal in a confirmed bull regime.
    base['Scan_Extended_Trim']=bool(cyc.get('Overextension_Risk')=='HIGH' and cyc.get('Cycle_Risk')=='HIGH')
    base['Scan_Uptrend_Pullback']=bool(setup.startswith('TREND PULLBACK')); base['Scan_EMA_Buy_Zone']=base['Scan_Uptrend_Pullback']
    base['Scan_Breakout_Base']=bool(setup.startswith('BREAKOUT'))
    base.update(cyc)
    base['Weekly_Cycle_Score']=cyc.get('Cycle_Score',50)  # backwards-compatible contract
    _a=_safe_last(df,'ATR_%'); _d=cyc.get('Dist_EMA21_%',np.nan)
    base['ATR_Units_from_EMA21']=round(float(_d/_a),2) if pd.notna(_d) and pd.notna(_a) and _a>0 else np.nan
    return _common_output(base,'Crypto',professional_framework(ticker,'Cripto',sector),trend,entry,risk,technical,setup,
        'Crypto is regime-aware: cycle/structural opportunity, execution timing, overextension and leverage risk are separate. High RSI or distance from an EMA is not automatically bearish during bull expansion.')


def _commodity(ticker,df,benchmark,sector):
    base=analyze_symbol(ticker,df,benchmark,sector)
    p=_safe_last(df,'Close'); e20=_safe_last(df,'EMA20'); e50=_safe_last(df,'EMA50'); s200=_safe_last(df,'SMA200')
    atrp=_safe_last(df,'ATR_%'); rsi=_safe_last(df,'RSI14'); r20=_safe_last(df,'Ret20'); r63=_safe_last(df,'Ret63')
    se20=slope_score(df['EMA20'],10); se50=slope_score(df['EMA50'],15)
    trend=20*(p>e20)+20*(e20>e50)+16*(p>s200)+.18*se20+.14*se50+(.12*slope_score(df['SMA200'],20))
    u=_atr_units(p,e20,atrp); entry=50
    if pd.notna(u): entry += 22 if -.6<=u<=.8 else 10 if .8<u<=1.5 else -18 if u>2.5 else -5
    if pd.notna(rsi): entry += 10 if 42<=rsi<=62 else -12 if rsi>=75 else -7 if rsi<=28 else 0
    # Avoid chasing one-month commodity spikes.
    if pd.notna(r20) and pd.notna(r63) and r20>15 and r63>25: entry-=10
    risk=100
    if pd.notna(atrp): risk -= 42 if atrp>6 else 30 if atrp>4.5 else 18 if atrp>3 else 8 if atrp>2 else 0
    technical=.40*trend+.28*entry+.20*risk+.12*(50 if pd.isna(r63) else clamp(50+r63))
    pullback=trend>=68 and pd.notna(u) and -.6<=u<=1.0
    extended=(pd.notna(u) and u>2.5) or (pd.notna(rsi) and rsi>=75)
    setup='Commodity Trend Pullback' if pullback else 'Commodity Extended' if extended else 'Commodity Trend / Watch'
    base['Trend']='Strong Uptrend' if trend>=78 else 'Uptrend' if trend>=62 else 'Neutral' if trend>=45 else 'Downtrend'
    base['Scan_Uptrend_Pullback']=bool(pullback); base['Scan_Extended_Trim']=bool(extended); base['Scan_EMA_Buy_Zone']=bool(pullback)
    base['ATR_Units_from_EMA20']=round(float(u),2) if pd.notna(u) else np.nan
    return _common_output(base,'Commodity',professional_framework(ticker,'Commodity',sector),trend,entry,risk,technical,setup,
                          'Commodity score emphasizes volatility, macro/supply context and avoids treating corporate valuation as relevant.')


def _fixed_income(ticker,df,benchmark,sector):
    base=analyze_symbol(ticker,df,benchmark,sector); t=ticker.upper().strip()
    p=_safe_last(df,'Close'); e20=_safe_last(df,'EMA20'); e50=_safe_last(df,'EMA50'); s200=_safe_last(df,'SMA200')
    atrp=_safe_last(df,'ATR_%'); rsi=_safe_last(df,'RSI14')
    is_yield=t in YIELD_INDEXES
    # For yield indices, trend describes yields, not bond prices. Preserve direction explicitly.
    se20=slope_score(df['EMA20'],10); se50=slope_score(df['EMA50'],15)
    trend=24*(p>e20)+20*(e20>e50)+16*(p>s200)+.20*se20+.12*se50+.08*slope_score(df['SMA200'],20)
    trend=clamp(trend)
    u=_atr_units(p,e20,atrp); entry=50
    if pd.notna(u): entry += 20 if -.7<=u<=.7 else 8 if .7<u<=1.4 else -15 if abs(u)>2.4 else 0
    if pd.notna(rsi): entry += 8 if 42<=rsi<=60 else -10 if rsi>=72 or rsi<=28 else 0
    risk=100
    if pd.notna(atrp): risk -= 32 if atrp>3 else 20 if atrp>2 else 10 if atrp>1 else 0
    technical=.42*trend+.30*entry+.28*risk
    if is_yield:
        base['Trend']='Yield Uptrend' if trend>=62 else 'Yield Downtrend' if trend<45 else 'Yield Neutral'
        setup='Rates Trend / Repricing'
        comment='This is a yield index: a higher score means stronger/rising yield trend, not automatically a bullish bond-price signal.'
    else:
        base['Trend']='Strong Uptrend' if trend>=78 else 'Uptrend' if trend>=62 else 'Neutral' if trend>=45 else 'Downtrend'
        setup='Duration/Credit Pullback' if trend>=62 and pd.notna(u) and -.7<=u<=.8 else 'Fixed Income Watch'
        comment='Fixed income combines total-return trend with duration/credit macro context; company valuation is excluded.'
    base['Rate_Series']=bool(is_yield); base['ATR_Units_from_EMA20']=round(float(u),2) if pd.notna(u) else np.nan
    return _common_output(base,'Rates' if is_yield else ('Credit' if t in CREDIT_ETFS else 'Duration'),professional_framework(ticker,'Bono/Tasa',sector),trend,entry,risk,technical,setup,comment)


def _fx(ticker,df,benchmark,sector):
    base=analyze_symbol(ticker,df,benchmark,sector)
    p=_safe_last(df,'Close'); e20=_safe_last(df,'EMA20'); e50=_safe_last(df,'EMA50'); s200=_safe_last(df,'SMA200')
    atrp=_safe_last(df,'ATR_%'); rsi=_safe_last(df,'RSI14')
    se20=slope_score(df['EMA20'],10); se50=slope_score(df['EMA50'],15)
    trend=24*(p>e20)+18*(e20>e50)+16*(p>s200)+.18*se20+.14*se50+.10*slope_score(df['SMA200'],20)
    u=_atr_units(p,e20,atrp); entry=50
    if pd.notna(u): entry += 22 if -.5<=u<=.8 else 9 if .8<u<=1.4 else -16 if abs(u)>2.5 else 0
    if pd.notna(rsi): entry += 8 if 43<=rsi<=60 else -10 if rsi>=72 or rsi<=28 else 0
    risk=100
    if pd.notna(atrp): risk -= 32 if atrp>2.5 else 20 if atrp>1.8 else 10 if atrp>1.2 else 0
    technical=.44*trend+.30*entry+.26*risk
    base['Trend']='Strong Uptrend' if trend>=78 else 'Uptrend' if trend>=62 else 'Neutral' if trend>=45 else 'Downtrend'
    setup='FX Trend Pullback' if trend>=64 and pd.notna(u) and -.5<=u<=.9 else 'FX Trend / Watch'
    base['ATR_Units_from_EMA20']=round(float(u),2) if pd.notna(u) else np.nan
    return _common_output(base,'FX',professional_framework(ticker,'Forex',sector),trend,entry,risk,technical,setup,
                          'FX score focuses on trend/volatility and macro differentials. True carry is not fabricated when foreign policy-rate data is absent.')


def analyze_asset(ticker: str, df: pd.DataFrame, benchmark_df=None, sector: str='Other', asset_type: str='Acción', technical_depth: str='Balanceado') -> dict:
    """Main public router for asset-aware technical analysis.

    technical_depth controls local price-analysis work only; it never enables
    fundamentals/provider calls. Rápido keeps the asset-specific core, while
    Balanceado/Profundo add the professional structure/weekly/volume layer.
    """
    typ=effective_asset_type(ticker,asset_type)
    if typ=='Cripto': out=_crypto(ticker,df,benchmark_df,sector)
    elif typ=='Commodity': out=_commodity(ticker,df,benchmark_df,sector)
    elif typ=='Bono/Tasa': out=_fixed_income(ticker,df,benchmark_df,sector)
    elif typ=='Forex': out=_fx(ticker,df,benchmark_df,sector)
    else: out=_equity_like(ticker,df,benchmark_df,sector,typ)
    depth=str(technical_depth or 'Balanceado')
    out['Technical_Depth']=depth
    out['Technical_Score_Legacy']=out.get('Technical_Score',np.nan)
    if depth=='Rápido':
        # Core indicators only: fastest path for large-universe discovery.
        out['TA_Quality_Score']=np.nan
        out['TA_Data_Note']='Fast technical mode: core trend/entry/risk/RS only; no deep TA layer.'
        return out
    # Balanceado/Profundo add structure, weekly confirmation, participation,
    # volatility regime and price/volume location. These are local computations.
    ta=professional_technical_snapshot(df,typ)
    out.update(ta)
    if pd.notna(out.get('Technical_Score')):
        ta_weight=.28 if depth=='Balanceado' else .38
        out['Technical_Score']=int(clamp(round((1-ta_weight)*float(out['Technical_Score'])+ta_weight*float(ta['TA_Quality_Score']))))
    if depth=='Profundo':
        out['TA_Data_Note']=str(out.get('TA_Data_Note',''))+' Deep mode uses the longest screener history and higher weight on structure/weekly/participation confirmation.'
    return out


def suggested_history_period(asset_type: str) -> str:
    typ=normalize_asset_type(asset_type)
    if typ=='Cripto': return '5y'  # weekly cycle / 200-week context when history exists
    if typ in {'Bono/Tasa','Commodity','Forex'}: return '3y'
    return '2y'
