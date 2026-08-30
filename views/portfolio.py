from datetime import date
import pandas as pd
import streamlit as st

from core.market_data import download_prices, classify_symbol
from core.indicators import enrich_indicators
from core.asset_models import analyze_asset
from core.storage import load_positions,load_theses,upsert_thesis,delete_thesis
from core.github_sync import push_file
from core.ui import hero,section_note

hero('Portfolio / Watchlist','Monitoreo de activos + tesis de inversión e invalidaciones.','Portfolio Research')

watch,thesis_tab=st.tabs(['Watchlist','Thesis Tracker'])
with watch:
    text=st.text_area('Tickers separados por coma',value=','.join(st.session_state.portfolio_tickers),height=90)
    if st.button('Actualizar watchlist',type='primary'):
        st.session_state.portfolio_tickers=[x.strip().upper() for x in text.replace('\n',',').split(',') if x.strip()]
    ticks=st.session_state.portfolio_tickers
    pm=download_prices(list(dict.fromkeys(ticks+['SPY'])),period='2y'); spy=pm.get('SPY')
    rows=[]
    for t in ticks:
        try:
            raw=pm.get(t)
            if raw is None or raw.empty: continue
            typ=classify_symbol(t); r=analyze_asset(t,enrich_indicators(raw),spy,'Portfolio',typ)
            action='BUY ZONE' if r['Entry_Score']>=75 and r['Trend_Score']>=65 and (pd.isna(r['RR']) or r['RR']>=1.5) else 'EXTENDED / TRIM' if r['Scan_Extended_Trim'] else 'WATCH' if r['Entry_Score']>=58 else 'HOLD / WAIT'
            rows.append({'Ticker':t,'Type':typ,'Model':r.get('Analysis_Model'),'Price':r['Price'],'Trend':r['Trend'],'Trend Score':r['Trend_Score'],'Entry Score':r['Entry_Score'],'Risk Score':r['Risk_Score'],'R/R':r['RR_Text'],'Setup':r['Setup'],'Action':action})
        except Exception as e:
            st.caption(f'{t}: datos incompletos ({type(e).__name__})')
    st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

with thesis_tab:
    section_note('Guardá por qué compraste, qué debería ocurrir y qué invalida la tesis. Evita reescribir la historia después.')
    pos=load_positions(); default_tickers=pos['ticker'].astype(str).tolist() if not pos.empty else st.session_state.portfolio_tickers
    ticker=st.selectbox('Ticker',list(dict.fromkeys(default_tickers)) or ['GEV'])
    existing=load_theses(ticker)
    old=existing.iloc[0].to_dict() if not existing.empty else {}
    thesis=st.text_area('Tesis',value=str(old.get('thesis','') or ''),height=100)
    catalysts=st.text_area('Catalizadores',value=str(old.get('catalysts','') or ''),height=80)
    invalidation=st.text_area('Invalidación',value=str(old.get('invalidation','') or ''),height=80)
    c1,c2,c3=st.columns(3)
    target=c1.text_input('Target / valoración objetivo',value=str(old.get('target','') or ''))
    status=c2.selectbox('Estado',['ACTIVE','WATCH','TRIM','CLOSED'],index=['ACTIVE','WATCH','TRIM','CLOSED'].index(str(old.get('status','ACTIVE'))) if str(old.get('status','ACTIVE')) in ['ACTIVE','WATCH','TRIM','CLOSED'] else 0)
    review=c3.date_input('Próxima revisión',value=date.today())
    note=st.text_input('Nota',value=str(old.get('note','') or ''))
    c1,c2=st.columns(2)
    if c1.button('Guardar tesis',type='primary',use_container_width=True):
        upsert_thesis(ticker,thesis,catalysts,invalidation,target,review,status,note)
        push_file('data/investment_theses.csv','data/investment_theses.csv','chore: update investment theses')
        st.success('Tesis guardada.'); st.rerun()
    if c2.button('Eliminar tesis',use_container_width=True):
        delete_thesis(ticker); push_file('data/investment_theses.csv','data/investment_theses.csv','chore: update investment theses'); st.rerun()
    all_theses=load_theses()
    if not all_theses.empty:
        st.subheader('Tesis guardadas'); st.dataframe(all_theses,use_container_width=True,hide_index=True)
