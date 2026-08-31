import pandas as pd
import streamlit as st

from core.market_data import download_prices, get_macro_symbols, classify_symbol, get_live_price
from core.indicators import enrich_indicators
from core.asset_models import analyze_asset, normalize_asset_type, effective_asset_type, professional_framework
from core.screener_enrichment import fetch_deep_bundle, deep_bundle_cache_fresh
from core.access_control import current_user, feature_allowed, require_quota, record_usage, require_api_budget, require_job_slot, end_job
from core.news_data import get_news
from core.economic_data import institutional_macro_snapshot
from core.macro import sector_macro_score
from core.asset_fundamentals import get_asset_context
from core.crypto_data import crypto_derivatives_score
from core.crypto_professional import professional_crypto_snapshot, professional_crypto_cycle
from core.commodity_data import commodity_deep_context
from core.charts import technical_chart
from core.opportunity import normalize_sector, attach_scores
from core.confidence import confidence_score
from core.explain import explain_opportunity
from core.position_sizing import size_position
from core.storage import load_score_history
from core.ui import hero, badge, section_note
from core.utils import fmt_money, fmt_num, fmt_pct
from core.valuation import standalone_valuation_score
from core.equity_sector_model import sector_fundamental_score, professional_equity_framework
from core.professional_equity_engine import professional_equity_snapshot
from core.data_coverage import equity_data_coverage, asset_data_coverage, coverage_rows
from core.professional_research_engine import professional_research_snapshot
from core.institutional_master_engine import institutional_master_snapshot
from core.factor_model import FACTOR_PROXIES
from core.storage import load_positions
from core.portfolio_intelligence import institutional_position_size
from core.advanced_options import advanced_options_snapshot

hero(
    'Asset Analysis',
    'Análisis profesional específico por clase de activo; no aplica el mismo modelo a acciones, cripto, bonos, commodities o FX.',
    'Single Asset Workstation',
)

_user=current_user()
with st.sidebar:
    st.caption(f"Plan: **{_user['plan']}**" + (' · 👑 sin cuotas comerciales' if _user['role']=='OWNER' else ''))
    ticker=st.text_input('Símbolo','META').strip().upper()
    detected=classify_symbol(ticker) if ticker else 'Otro'
    st.caption(f'Tipo detectado: **{detected}**')
    asset_type=st.selectbox('Tipo de activo',['Auto','Acción','ETF','Índice','Cripto','Commodity','Bono/Tasa','Forex','Otro'])
    final_type=detected if asset_type=='Auto' else asset_type
    sector=st.selectbox('Sector / sensibilidad macro',[
        'Technology','Financials','Health Care','Industrials','Utilities','Energy','Materials','Real Estate',
        'Consumer Discretionary','Consumer Staples','Communication Services','Other'
    ])
    _levels=['Técnico','Fundamental']
    if feature_allowed('dcf',_user):
        _levels.append('Completo')
    analysis_level=st.selectbox('Nivel de análisis',_levels,index=0,
        help='Técnico evita llamadas profundas. Fundamental usa fundamentals/revisions. Completo agrega DCF, escenarios e investigación institucional.')
    _signature=f"{ticker}|{asset_type}|{sector}|{analysis_level}"
    _run_now=st.button('🔬 Analizar',type='primary',use_container_width=True)

if not ticker: st.stop()
if not _run_now and st.session_state.get('_asset_analysis_signature') != _signature:
    st.info('Configurá el activo y presioná Analizar.')
    st.stop()
if _run_now:
    _feature='asset_technical' if analysis_level=='Técnico' else 'asset_deep'
    _cache_free=(analysis_level!='Técnico' and deep_bundle_cache_fresh(ticker))
    if not _cache_free and not require_quota(_feature,'Asset Analysis',_user):
        st.stop()
    if not require_api_budget(_feature,_user,cache_hit=_cache_free):
        st.stop()
    _job_token=require_job_slot(_user)
    if not _job_token:
        st.stop()
    st.session_state['_asset_analysis_signature']=_signature
    st.session_state['_asset_analysis_charge']=not _cache_free
else:
    _feature='asset_technical' if analysis_level=='Técnico' else 'asset_deep'
    _cache_free=True
    _job_token=None


try:
    positions=load_positions(user_id=_user['user_id'])
except Exception:
    positions=pd.DataFrame()
portfolio_tickers=list(positions['ticker'].astype(str).str.upper()) if isinstance(positions,pd.DataFrame) and not positions.empty and 'ticker' in positions else []
symbols=list(dict.fromkeys([ticker,'SPY']+list(get_macro_symbols().values())+list(FACTOR_PROXIES.values())+portfolio_tickers))
pm=download_prices(symbols,period='5y')
raw=pm.get(ticker); spy=pm.get('SPY')
if raw is None or raw.empty:
    st.error('No se pudieron obtener precios.'); st.stop()

h=enrich_indicators(raw); final_type=effective_asset_type(ticker,normalize_asset_type(final_type))
row=analyze_asset(ticker,h,spy,sector,final_type)
# Keep the displayed/valuation entry price fresh without forcing a 5-year OHLCV reload.
live_price=get_live_price(ticker)
if live_price is not None:
    row['Price']=live_price
row['Asset_Type']=final_type
macro=st.session_state.macro_snapshot or institutional_macro_snapshot(pm,breadth_level=50)
if final_type=='Acción':
    macro_fit=sector_macro_score(normalize_sector(sector),macro)
    row['Sector_Score']=50
else:
    ctx=get_asset_context(ticker,final_type,pm,macro)
    macro_fit=ctx.get('Asset_Context_Score',50)
    row['Asset_Context_Score']=ctx.get('Asset_Context_Score')
    row['Framework']=ctx.get('Framework',professional_framework(ticker,final_type,sector))
    row['Sector_Score']=float('nan')
row['Macro_Fit']=macro_fit
row['RS_Percentile']=50
# Reuse cross-sectional context from the latest screener when available.
try:
    sr=st.session_state.scan_results
    if sr is not None and not sr.empty and ticker in sr['Ticker'].values:
        rr=sr[sr['Ticker']==ticker].iloc[-1]
        row['Sector_Score']=rr.get('Sector_Score',50)
        row['RS_Percentile']=rr.get('RS_Percentile',50)
except Exception:
    pass

fund=None; analyst=None; event=None; eq={}
if final_type=='Acción' and analysis_level!='Técnico':
    # Reuse the same persistent, TTL-aware deep cache as the screeners. This avoids
    # session caches keeping stale fundamentals forever and prevents duplicate
    # Yahoo/FMP/SEC/analyst/event calls for the same ticker across pages/users.
    with st.spinner('Consultando fundamentales...'):
        bundle=fetch_deep_bundle(ticker)
    fund=bundle.get('fundamentals') or {}
    analyst=bundle.get('analyst') or {}
    event=bundle.get('event') or {'risk':'UNKNOWN','days_to_earnings':None}
    if fund and not fund.get('error'):
        st.session_state.fundamentals_cache[ticker]=fund
    if not fund.get('error'):
        company_sector=normalize_sector(fund.get('Sector')) if pd.notna(fund.get('Sector')) and str(fund.get('Sector')).strip() else normalize_sector(sector)
        # Corporate classification uses the reported sector/industry when available;
        # the sidebar remains a fallback for macro sensitivity.
        row['Sector']=company_sector
        row['Macro_Fit']=sector_macro_score(company_sector,macro)
        macro_fit=row['Macro_Fit']
        eq=professional_equity_snapshot(fund,company_sector,fund.get('Industry',''),ticker)
        row['Quality_Score']=eq.get('Quality_Score',fund.get('Fundamental_Score'))
        row['Fundamental_Coverage_%']=eq.get('Fundamental_Coverage_%',0)
        row['Valuation_Score']=eq.get('Valuation_Score')
        row['Valuation_Coverage_%']=eq.get('Valuation_Coverage_%',0)
        row['Equity_Model']=eq.get('Equity_Model')
        row['Equity_Model_Key']=eq.get('Equity_Model_Key')
        row['Peer_Group']=eq.get('Peer_Group')
        row['Sector_Model_Limitation']='Quality and valuation use only observed free-data fields; specialist KPIs remain missing when not reported by public feeds.'
    else:
        eq={}
        row['Quality_Score']=None
        row['Valuation_Score']=None
    row['Revision_Score']=analyst.get('EPS_Revision_Score')
    row['Event_Risk']=event.get('risk')

# Explicit data-quality layer: scores are never presented as equally reliable when
# specialist industry/asset data are missing.
if final_type=='Acción':
    data_cov=equity_data_coverage(None if not fund or fund.get('error') else fund, row.get('Sector',normalize_sector(sector)), '' if not fund else fund.get('Industry',''), ticker)
else:
    coverage_ctx=dict(ctx) if 'ctx' in locals() and isinstance(ctx,dict) else {}
    if final_type=='Cripto':
        try:
            _cg_score,_cg_deep=crypto_derivatives_score('BTCUSDT' if ticker.startswith('BTC') else 'ETHUSDT' if ticker.startswith('ETH') else 'BTCUSDT')
            coverage_ctx.update(_cg_deep)
            coverage_ctx.update(professional_crypto_snapshot(ticker))
        except Exception:
            pass
    if final_type=='Commodity':
        try:
            coverage_ctx.update(commodity_deep_context(ticker))
        except Exception:
            pass
    data_cov=asset_data_coverage(ticker,final_type,coverage_ctx,macro)
row.update({k:v for k,v in data_cov.items() if k not in {'Available_Data','Missing_Critical_Data','Missing_Useful_Data','Recommended_Data_Sources'}})

conf,conf_reasons=confidence_score(row,fundamentals=None if not fund or fund.get('error') else fund,macro=macro)
row['Confidence_Score']=conf
try:
    scored=attach_scores(pd.DataFrame([row])).iloc[0]
    row.update(scored.to_dict())
except Exception:
    pass

# Institutional-style research layer: peers, revisions, catalysts and explicit
# bear/base/bull scenario analysis are kept separate from the core factor score.
research=None
research_news=pd.DataFrame()
if final_type=='Acción' and analysis_level=='Completo' and fund and not fund.get('error'):
    try:
        research_news=research_news if final_type=='Acción' and not research_news.empty else get_news(ticker,12)
    except Exception:
        research_news=pd.DataFrame()
    try:
        peer_universe=st.session_state.scan_results if getattr(st.session_state,'scan_results',None) is not None else None
        research=professional_research_snapshot(row,fund,analyst,event,eq,peer_universe,research_news)
        scen=research.get('Scenarios',{})
        row['Bear_Case_Price']=scen.get('Bear_Price')
        row['Base_Case_Price']=scen.get('Base_Price')
        row['Bull_Case_Price']=scen.get('Bull_Price')
        row['Scenario_Expected_Return_%']=scen.get('Expected_Return_%')
        row['Scenario_Coverage_%']=scen.get('Scenario_Coverage_%')
        peers=research.get('Peers',{})
        row['Peer_Rank_Score']=peers.get('Peer_Rank_Score')
    except Exception:
        research=None

# V9 institutional master layer. It composes valuation/forensics/macro/commodity/factor/portfolio
# evidence without feeding unavailable observations as neutral or fabricated values.
if analysis_level=='Completo':
    try:
        institutional=institutional_master_snapshot(ticker,final_type,row,fund,macro,pm,positions,research,eq if final_type=='Acción' else {})
    except Exception as _inst_exc:
        institutional={'error':str(_inst_exc)[:180]}
else:
    institutional={}

options_intel=None
if analysis_level=='Completo' and final_type in {'Acción','ETF','Índice'}:
    try:
        options_intel=advanced_options_snapshot(ticker,max_expiries=4)
    except Exception:
        options_intel=None

if _run_now:
    # Cache-served deep analyses are logged for observability with zero quota units.
    _units=1 if st.session_state.get('_asset_analysis_charge',True) else 0
    record_usage(_feature,units=_units,cache_hit=bool(_cache_free),metadata={'ticker':ticker,'level':analysis_level},user=_user)
    end_job(_job_token,_user)

c1,c2,c3,c4,c5,c6,c7,c8=st.columns(8)
c1.metric('Trend',row['Trend']); c2.metric('Technical',row['Technical_Score']); c3.metric('Entry',row['Entry_Score'])
c4.metric('Risk',row['Risk_Score']); c5.metric('Macro Fit',macro_fit); c6.metric('Confidence',f'{conf}/100'); c7.metric('Model Coverage',f"{row.get('Model_Coverage_%',0):.0f}%"); c8.metric('Data Coverage',f"{data_cov.get('Data_Coverage_Score',0)}/100")
if pd.notna(row.get('Opportunity_Score')):
    st.metric('Opportunity Score',f"{int(row['Opportunity_Score'])}/100")

st.markdown(
    badge(row['Setup'],'good' if row['Entry_Score']>=70 else 'warn')+
    badge(final_type,'neutral')+
    badge(row.get('Event_Risk','NORMAL'),'bad' if row.get('Event_Risk')=='HIGH' else 'warn' if row.get('Event_Risk')=='ELEVATED' else 'neutral'),
    unsafe_allow_html=True,
)

st.plotly_chart(technical_chart(h,ticker),use_container_width=True)

st.subheader('📍 Setup & Risk')
x1,x2,x3,x4,x5=st.columns(5)
x1.metric('Entrada ideal',row['Entry_Zone']); x2.metric('Invalidación',row['Invalidation']); x3.metric('Target',row['Target']); x4.metric('R/R',row['RR_Text']); x5.metric('Dist EMA62',fmt_pct(row['Dist_EMA62_%']))
st.write(row['Comment'])

# Professional technical diagnostics: observations are shown separately from the score.
st.subheader('📐 Professional Technical Diagnostics')
ta_keys=['Market_Structure','Weekly_State','FourH_State','Participation','Volatility_Regime','Technical_Location',
         'Anchored_VWAP','Dist_AVWAP_%','Volume_Profile_POC_Proxy','Relative_Volume_20d','Up_Down_Volume_20d','ATR_Percentile_1y']
ta_table=pd.DataFrame([[k,row.get(k,'N/D')] for k in ta_keys],columns=['Technical dimension','Reading'])
st.dataframe(ta_table,use_container_width=True,hide_index=True)
st.caption(row.get('TA_Data_Note',''))

if final_type=='Acción' and research:
    st.subheader('🧭 Professional Research Workstation')
    rev=research.get('Revisions',{}); peers=research.get('Peers',{}); cats=research.get('Catalysts',{}); scen=research.get('Scenarios',{})
    r1,r2,r3,r4=st.columns(4)
    r1.metric('Revision Momentum',rev.get('Revision_Momentum','N/D'))
    r2.metric('Peer Rank','N/D' if pd.isna(peers.get('Peer_Rank_Score')) else f"{int(peers.get('Peer_Rank_Score'))}/100")
    r3.metric('Scenario EV Return','N/D' if pd.isna(scen.get('Expected_Return_%')) else f"{scen.get('Expected_Return_%'):.1f}%")
    r4.metric('Scenario Coverage',f"{scen.get('Scenario_Coverage_%',0)}%")

    st.markdown('**Bear / Base / Bull scenario map**')
    if isinstance(scen.get('Scenarios'),pd.DataFrame) and not scen['Scenarios'].empty:
        st.dataframe(scen['Scenarios'],use_container_width=True,hide_index=True)
    st.caption(scen.get('Scenario_Method',''))
    st.caption(scen.get('Scenario_Note',''))

    st.markdown('**Estimate revisions & earnings evidence**')
    rev_rows=[[k,v] for k,v in rev.items() if k not in {'Revision_Evidence'}]
    st.dataframe(pd.DataFrame(rev_rows,columns=['Revision dimension','Reading']),use_container_width=True,hide_index=True)
    if rev.get('Revision_Evidence'): st.caption(' · '.join(rev['Revision_Evidence']))

    st.markdown('**True business-model peer benchmark**')
    st.caption(f"Comparable model: {row.get('Equity_Model','N/D')} · peers in current universe: {peers.get('Peer_Count',0)} · {peers.get('Peer_Summary','')}")
    peer_metrics=pd.DataFrame([[k,peers.get(k)] for k in ['Peer_Quality_Percentile','Peer_Valuation_Percentile','Peer_Revisions_Percentile','Peer_RS_Percentile']],columns=['Peer dimension','Percentile'])
    st.dataframe(peer_metrics,use_container_width=True,hide_index=True)
    if isinstance(peers.get('Peer_Table'),pd.DataFrame) and not peers['Peer_Table'].empty:
        st.dataframe(peers['Peer_Table'],use_container_width=True,hide_index=True)

    st.markdown('**Catalyst / risk map**')
    cat_table=pd.DataFrame([
        ['Structural catalysts',', '.join(cats.get('Structural_Catalysts',[])) or 'N/D'],
        ['Structural risks',', '.join(cats.get('Structural_Risks',[])) or 'N/D'],
        ['Near-term catalyst risk',cats.get('Near_Term_Catalyst_Risk','N/D')],
        ['Catalyst coverage',f"{cats.get('Catalyst_Coverage_%',0)}%"],
    ],columns=['Catalyst dimension','Reading'])
    st.dataframe(cat_table,use_container_width=True,hide_index=True)
    if cats.get('Dated_Catalysts'): st.dataframe(pd.DataFrame(cats['Dated_Catalysts']),use_container_width=True,hide_index=True)

# V9 Institutional multi-asset evidence layer
st.subheader('🏛️ V9 Institutional Research Layer')
macro_v9=institutional.get('Macro_Regime',{}) if isinstance(institutional,dict) else {}
mi1,mi2,mi3,mi4=st.columns(4)
mi1.metric('Macro Regime',macro_v9.get('Macro_Regime','N/D'))
mi2.metric('Global Liquidity Proxy',f"{macro_v9.get('Global_Liquidity_Proxy_Score',50)}/100")
fit=institutional.get('Portfolio_Fit',{}) if isinstance(institutional,dict) else {}
mi3.metric('Portfolio Fit',f"{fit.get('Portfolio_Fit_Score','N/D')}/100" if fit else 'N/D')
mi4.metric('Ann. Volatility','N/D' if pd.isna(fit.get('Annualized_Volatility_%',float('nan'))) else f"{fit.get('Annualized_Volatility_%'):.1f}%")
st.caption(macro_v9.get('Regime_Note',''))

if final_type=='Acción' and isinstance(institutional,dict):
    val=institutional.get('Valuation',{}); forensic=institutional.get('Forensics',{})
    st.markdown('**Institutional valuation / expectations**')
    vv1,vv2,vv3,vv4=st.columns(4)
    revdcf=val.get('Reverse_DCF',{}); dcf=val.get('DCF',{})
    vv1.metric('Reverse DCF implied FCF growth','N/D' if not revdcf.get('available') else f"{revdcf.get('Implied_FCF_Growth_%'):.1f}%")
    vv2.metric('DCF scenario upside','N/D' if not dcf.get('available') else f"{dcf.get('Fair_Value_Upside_%'):.1f}%")
    vv3.metric('Earnings Quality',f"{forensic.get('Earnings_Quality_Score','N/D')}/100")
    vv4.metric('Financial Resilience',f"{forensic.get('Financial_Resilience_Score','N/D')}/100")
    if dcf.get('available') and isinstance(dcf.get('Scenarios'),pd.DataFrame):
        st.dataframe(dcf['Scenarios'],use_container_width=True,hide_index=True)
    st.caption(val.get('Historical_Valuation_Note',''))
    st.dataframe(pd.DataFrame([[k,v] for k,v in forensic.items() if k not in {'Evidence','Note'}],columns=['Financial-quality dimension','Reading']),use_container_width=True,hide_index=True)
    st.caption(forensic.get('Note',''))

if final_type=='Commodity' and isinstance(institutional,dict):
    ci=institutional.get('Commodity',{})
    st.markdown('**Physical market / curve / positioning**')
    st.dataframe(pd.DataFrame([[k,v] for k,v in ci.items() if k!='Raw_Context'],columns=['Commodity dimension','Reading']),use_container_width=True,hide_index=True)
    st.caption(ci.get('Coverage_Note',''))

fx=institutional.get('Factor_Exposure') if isinstance(institutional,dict) else None
if isinstance(fx,pd.DataFrame) and not fx.empty:
    st.markdown('**Factor exposure (market proxies)**')
    st.dataframe(fx,use_container_width=True,hide_index=True)

if options_intel and options_intel.get('available'):
    st.markdown('**Options intelligence**')
    oi1,oi2,oi3=st.columns(3)
    oi1.metric('IV rank proxy','N/D' if pd.isna(options_intel.get('iv_rank_proxy_%')) else f"{options_intel.get('iv_rank_proxy_%'):.0f}%")
    oi2.metric('Max pain proxy','N/D' if pd.isna(options_intel.get('max_pain')) else f"${options_intel.get('max_pain'):.2f}")
    term=options_intel.get('term_structure')
    oi3.metric('Expiries analyzed',len(term) if isinstance(term,pd.DataFrame) else 0)
    if isinstance(term,pd.DataFrame) and not term.empty: st.dataframe(term,use_container_width=True,hide_index=True)
    st.caption(options_intel.get('note',''))

thesis=institutional.get('Thesis',{}) if isinstance(institutional,dict) else {}
if thesis:
    st.markdown('**Investment thesis / invalidation / execution**')
    thesis_df=pd.DataFrame([
        ['Why now',' · '.join(thesis.get('Why_Now',[]))],
        ['What market may be missing',' · '.join(thesis.get('What_Market_May_Be_Missing',[]))],
        ['Catalysts',', '.join(thesis.get('Catalysts',[])) or 'N/D'],
        ['Risks',', '.join(thesis.get('Risks',[])) or 'N/D'],
        ['Invalidation',thesis.get('Invalidation','N/D')],
        ['Recommended execution',thesis.get('Recommended_Execution','N/D')],
    ],columns=['Thesis dimension','Reading'])
    st.dataframe(thesis_df,use_container_width=True,hide_index=True)
    st.caption(thesis.get('Thesis_Note',''))

# Position sizing
with st.expander('💰 Position Sizing'):
    capital=st.number_input('Capital de cartera',min_value=100.0,value=100000.0,step=1000.0)
    risk_pct=st.number_input('Riesgo máximo por trade (%)',min_value=0.1,max_value=5.0,value=1.0,step=0.1)
    max_pos=st.number_input('Máximo tamaño de posición (%)',min_value=1.0,max_value=100.0,value=20.0,step=1.0)
    # Parse numeric levels from generated strings using actual calculated approximations.
    entry=float(row['Price'])
    try: stop=float(row['Invalidation'].replace('< $','').replace(',',''))
    except Exception: stop=entry*(1-0.05)
    sizing=size_position(capital,risk_pct,entry,stop,max_pos)
    a,b,c,d=st.columns(4)
    a.metric('Shares',sizing['shares']); b.metric('Position $',f"${sizing['position_value']:,.0f}"); c.metric('Actual Risk $',f"${sizing['actual_risk']:,.0f}"); d.metric('Portfolio %',f"{sizing['position_pct']:.1f}%")
    fit_score=fit.get('Portfolio_Fit_Score',70) if isinstance(fit,dict) else 70
    vol=fit.get('Annualized_Volatility_%',float('nan')) if isinstance(fit,dict) else float('nan')
    conviction=row.get('Opportunity_Score',row.get('Long_Term_Opportunity_Score',70))
    inst_size=institutional_position_size(capital,entry,stop,conviction if pd.notna(conviction) else 70,vol,fit_score,max_position_pct=max_pos)
    st.caption(f"Institutional risk-budget suggestion: {inst_size.get('position_pct',0):.1f}% position · initial tranche {inst_size.get('initial_tranche_pct',0):.1f}% · risk budget {inst_size.get('risk_budget_pct',0):.2f}% of portfolio.")

if final_type=='Acción':
    st.subheader('🏢 Corporate Fundamentals & Revisions')
    if fund and fund.get('error'):
        st.warning(fund['error'])
    elif fund:
        a,b,c,d=st.columns(4)
        a.metric('Professional Quality',f"{int(row.get('Quality_Score',fund['Fundamental_Score']))}/100"); b.metric('Valuation', 'N/D' if pd.isna(row.get('Valuation_Score')) else f"{int(row.get('Valuation_Score'))}/100")
        c.metric('Revenue Growth',fmt_pct(fund['Revenue_Growth'])); d.metric('Earnings Growth',fmt_pct(fund['Earnings_Growth']))
        e,f,g,i=st.columns(4)
        e.metric('Profit Margin',fmt_pct(fund['Profit_Margin'])); f.metric('ROE',fmt_pct(fund['ROE'])); g.metric('Debt / Equity',fmt_num(fund['Debt_Equity'])); i.metric('FCF',fmt_money(fund['FCF']))
        if fund.get('Premium_Fundamentals_Source'):
            st.caption('Fundamental data source: '+str(fund.get('Premium_Fundamentals_Source')))
        premium_metrics={k:fund.get(k) for k in ['ROIC','FCF_Yield','Piotroski_Score','Altman_Z_Score'] if k in fund and pd.notna(fund.get(k))}
        if premium_metrics:
            st.dataframe(pd.DataFrame(list(premium_metrics.items()),columns=['Premium fundamental metric','Value']),use_container_width=True,hide_index=True)
        st.info(professional_equity_framework(row.get('Sector',normalize_sector(sector)),fund.get('Industry',''),ticker))
        if eq:
            m1,m2,m3,m4=st.columns(4)
            m1.metric('Industry Model',eq.get('Equity_Model','N/D')); m2.metric('Quality Coverage',f"{eq.get('Fundamental_Coverage_%',0):.0f}%")
            m3.metric('Valuation Coverage',f"{eq.get('Valuation_Coverage_%',0):.0f}%"); m4.metric('Specialist KPI Coverage',f"{eq.get('Specialist_KPI_Coverage_%',0):.0f}%")
            st.caption('Peer group: '+str(eq.get('Peer_Group','N/D')))
            qrows=[[k,v] for k,v in eq.get('Quality_Pillars',{}).items()]
            if qrows: st.dataframe(pd.DataFrame(qrows,columns=['Quality pillar','Score']),use_container_width=True,hide_index=True)
            research=pd.DataFrame([
                ['Preferred valuation',', '.join(eq.get('Preferred_Valuation_Methods',[]))],
                ['Key catalysts',', '.join(eq.get('Key_Catalysts',[]))],
                ['Key risks',', '.join(eq.get('Key_Risks',[]))],
                ['Observed specialist KPIs',', '.join(eq.get('Observed_Specialist_KPIs',[])) or 'None'],
                ['Missing specialist KPIs',', '.join(eq.get('Missing_Specialist_KPIs',[])) or 'None'],
            ],columns=['Professional research dimension','Reading'])
            st.dataframe(research,use_container_width=True,hide_index=True)
            st.caption(eq.get('Valuation_Note',''))
        if row.get('Sector_Model_Limitation'): st.caption(row['Sector_Model_Limitation'])

    if analyst:
        st.subheader('📈 Analyst / EPS Revisions')
        a,b,c,d=st.columns(4)
        a.metric('Revision Score',f"{analyst['EPS_Revision_Score']}/100" if pd.notna(analyst['EPS_Revision_Score']) else 'N/D')
        b.metric('Direction',analyst['Revision_Direction']); c.metric('Target Upside',fmt_pct(analyst['Price_Target_Upside_%']))
        d.metric('Analysts',fmt_num(analyst['Analyst_Count'],0))
        if not analyst['Revision_Detail'].empty:
            st.dataframe(analyst['Revision_Detail'],use_container_width=True,hide_index=True)

    if event:
        st.subheader('📅 Event Risk')
        st.write(f"Next earnings: **{event['next_earnings']}** · Days: **{event['days_to_earnings']}** · Risk: **{event['risk']}**")

else:
    st.subheader('🧩 Asset-Specific Fundamentals / Context')
    section_note('No se usan BPA/PER/ROE cuando el activo no es una empresa. Cada clase usa drivers propios.')
    st.info(row.get('Professional_Framework',professional_framework(ticker,final_type,sector)))
    ctx=get_asset_context(ticker,final_type,pm,macro)
    a,b=st.columns([1,3]); a.metric('Asset Context Score','N/D' if pd.isna(ctx.get('Asset_Context_Score')) else f"{ctx['Asset_Context_Score']}/100"); b.info(ctx.get('Framework','N/D'))
    detail=pd.DataFrame([[k,v] for k,v in ctx.items() if k not in {'Asset_Context_Score','Framework'}],columns=['Metric','Value'])
    st.dataframe(detail,use_container_width=True,hide_index=True)

    if final_type=='Cripto':
        score,deep=crypto_derivatives_score('BTCUSDT' if ticker.startswith('BTC') else 'ETHUSDT' if ticker.startswith('ETH') else ticker.replace('-USD','')+'USDT')
        pro=professional_crypto_snapshot(ticker)
        cyc=professional_crypto_cycle(ticker,h,pro)
        st.subheader('₿ Professional Crypto Model')
        cc=st.columns(5)
        cc[0].metric('Regime',cyc.get('Crypto_Regime','N/D')); cc[1].metric('Cycle',f"{cyc.get('Cycle_Score',0)}/100"); cc[2].metric('Long-Term Opp.',f"{cyc.get('Long_Term_Opportunity_Score',0)}/100"); cc[3].metric('Entry Timing',f"{cyc.get('Entry_Timing_Score',0)}/100"); cc[4].metric('Leverage Risk',cyc.get('Leverage_Risk','N/D'))
        st.success(cyc.get('Crypto_Verdict','')) if cyc.get('Long_Term_Opportunity_Score',0)>=75 else st.info(cyc.get('Crypto_Verdict',''))
        st.caption(cyc.get('Scenario_Note',''))
        st.dataframe(pd.DataFrame([[k,v] for k,v in cyc.items() if k not in {'Crypto_Verdict','Scenario_Note'}],columns=['Cycle / execution dimension','Reading']),use_container_width=True,hide_index=True)
        a,b,c=st.columns(3)
        a.metric('Model',pro.get('Crypto_Model','N/D')); b.metric('Derivatives Context',f'{score}/100'); c.metric('Specialist Coverage',f"{pro.get('Professional_Data_Coverage_%',0)}%")
        st.info(pro.get('Framework',''))
        score_rows=[[k,v] for k,v in pro.items() if str(k).endswith('_Score')]
        if score_rows: st.dataframe(pd.DataFrame(score_rows,columns=['Model component','Score']),use_container_width=True,hide_index=True)
        st.dataframe(pd.DataFrame([[k,v] for k,v in pro.items() if k not in {'Missing_Professional_Data','Framework'} and not str(k).endswith('_Score')],columns=['Professional crypto metric','Value']),use_container_width=True,hide_index=True)
        if pro.get('Missing_Professional_Data'): st.warning('Professional fields still unavailable from reliable free feeds: '+', '.join(pro['Missing_Professional_Data']))

    if final_type=='Commodity':
        deep=commodity_deep_context(ticker)
        st.subheader('⛏️ Commodity Deep Data')
        st.metric('Deep Data Score',f"{deep['Deep_Data_Score']}/100")
        st.dataframe(pd.DataFrame([[k,v] for k,v in deep.items() if k!='Notes'],columns=['Metric','Value']),use_container_width=True,hide_index=True)
        if deep['Notes']: st.info(' '.join(deep['Notes']))

# Data quality / coverage
st.subheader('🧾 Data Coverage & Missing Professional Inputs')
st.dataframe(coverage_rows(data_cov),use_container_width=True,hide_index=True)
if data_cov.get('Missing_Critical_Data'):
    st.warning('Missing critical/specialist data: ' + ', '.join(map(str,data_cov['Missing_Critical_Data'])))
else:
    st.success('No critical data gaps detected for the active coverage template.')
if data_cov.get('Missing_Useful_Data'):
    st.caption('Missing useful core fields: ' + ', '.join(map(str,data_cov['Missing_Useful_Data'])))
if data_cov.get('Recommended_Data_Sources'):
    st.info('Recommended sources to improve coverage: ' + ' · '.join(map(str,data_cov['Recommended_Data_Sources'])))
st.caption(data_cov.get('Coverage_Note',''))

# Explainability
st.subheader('🧠 Why this score?')
parts,penalty=explain_opportunity(row)
exp=pd.DataFrame(parts,columns=['Component','Weighted Contribution'])
if penalty: exp.loc[len(exp)]=['R/R + Event/Extension adjustments',penalty]
st.dataframe(exp,use_container_width=True,hide_index=True)
if conf_reasons: st.caption('Confidence deductions: '+', '.join(conf_reasons))

# Score history
st.subheader('🕒 Score History')
hist=load_score_history(ticker,days=180)
if hist.empty:
    st.info('Todavía no hay snapshots históricos para este ticker. Se empiezan a acumular con los scans/daily refresh.')
else:
    show=[c for c in ['ts','price','technical','trend','entry','quality','opportunity','confidence','action'] if c in hist]
    st.dataframe(hist[show].sort_values('ts',ascending=False).head(60),use_container_width=True,hide_index=True)
    chart=hist.set_index('ts')[[c for c in ['technical','trend','entry','opportunity','confidence'] if c in hist]].dropna(how='all')
    if not chart.empty: st.line_chart(chart)

# News / catalysts
st.subheader('📰 Recent Catalysts / News')
news=get_news(ticker,12)
if news.empty: st.caption('No news returned by provider.')
else: st.dataframe(news,use_container_width=True,hide_index=True)
