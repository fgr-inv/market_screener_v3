import pandas as pd, streamlit as st
from core.market_data import download_prices, get_macro_symbols
from core.indicators import enrich_indicators
from core.asset_models import analyze_asset
from core.asset_fundamentals import crypto_context
from core.crypto_data import crypto_derivatives_score
from core.crypto_professional import professional_crypto_snapshot, professional_crypto_cycle
from core.economic_data import institutional_macro_snapshot
from core.charts import technical_chart
from core.ui import hero, section_note, key_value_frame

hero('Crypto','Modelos separados para BTC, ETH, L1/L2, DeFi, stablecoins y tokens especulativos: macro + red/on-chain + tokenomics + derivados + técnico.','Digital Assets')
watch=[('BTC-USD','Bitcoin'),('ETH-USD','Ethereum'),('SOL-USD','Solana'),('AAVE-USD','Aave')]
pm=download_prices(list(dict.fromkeys([x[0] for x in watch]+['SPY']+list(get_macro_symbols().values()))),period='5y'); spy=pm.get('SPY')
macro=st.session_state.macro_snapshot or institutional_macro_snapshot(pm,breadth_level=50)
rows=[]
for sym,name in watch:
    raw=pm.get(sym)
    if raw is None or raw.empty: continue
    h=enrich_indicators(raw); r=analyze_asset(sym,h,spy,name,'Cripto'); ctx=crypto_context(sym,pm,macro); pro=professional_crypto_snapshot(sym); cyc=professional_crypto_cycle(sym,h,pro)
    deriv,_=crypto_derivatives_score(sym.replace('-USD','USDT'))
    rows.append({'Asset':name,'Model':pro.get('Crypto_Model'),'Price':r['Price'],'Trend':r['Trend'],'Technical':r['Technical_Score'],'Regime':cyc.get('Crypto_Regime'),'Long-Term Opportunity':cyc.get('Long_Term_Opportunity_Score'),'Entry Timing':cyc.get('Entry_Timing_Score'),'Overextension':cyc.get('Overextension_Risk'),'Leverage Risk':cyc.get('Leverage_Risk'),'Risk':r['Risk_Score'],'Context':ctx.get('Asset_Context_Score'),'Derivatives':deriv,'Specialist Coverage %':pro.get('Professional_Data_Coverage_%'),'Setup':r['Setup']})
st.dataframe(pd.DataFrame(rows),width='stretch',hide_index=True)
section_note('Entry Timing no es Long-Term Opportunity. Un bull market confirmado puede estar algo extendido sin convertirse automáticamente en una mala oportunidad. BTC no se trata como una altcoin: incorpora seguridad de red, dificultad, minería, emisión y supply. ETH prioriza staking/issuance/burn/L2; L1/L2 priorizan actividad de red y tokenomics; DeFi prioriza economía del protocolo.')
choice=st.selectbox('Deep crypto model',[x[0] for x in watch])
pro=professional_crypto_snapshot(choice)
_h=enrich_indicators(pm[choice]) if choice in pm and pm[choice] is not None else pd.DataFrame()
cyc=professional_crypto_cycle(choice,_h,pro)
st.subheader('Cycle, Regime & Execution')
st.dataframe(key_value_frame(cyc,'Decision dimension','Reading'),width='stretch',hide_index=True)
st.info(cyc.get('Crypto_Verdict',''))
st.caption(cyc.get('Scenario_Note',''))
st.info(pro.get('Framework',''))
score_rows=[[k,v] for k,v in pro.items() if str(k).endswith('_Score')]
if score_rows: st.dataframe(pd.DataFrame(score_rows,columns=['Component','Score']),width='stretch',hide_index=True)
st.dataframe(key_value_frame([(k,v) for k,v in pro.items() if k not in {'Missing_Professional_Data','Framework'} and not str(k).endswith('_Score')]),width='stretch',hide_index=True)
if pro.get('Missing_Professional_Data'): st.warning('Missing specialist fields (not fabricated): '+', '.join(pro['Missing_Professional_Data']))
if choice in pm and pm[choice] is not None: st.plotly_chart(technical_chart(enrich_indicators(pm[choice]),choice),width='stretch')
