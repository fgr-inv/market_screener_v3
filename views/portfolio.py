from datetime import date
import pandas as pd
import streamlit as st

from core.market_data import download_prices, classify_symbol
from core.indicators import enrich_indicators
from core.asset_models import analyze_asset
from core.storage import load_positions, load_theses, upsert_thesis, delete_thesis
from core.access_control import current_user
from core.ui import hero, section_note

hero('Portfolio / Thesis','Posiciones, watchlist y tesis de inversión en un solo lugar.','Portfolio Research')
user=current_user(); uid=user['user_id']
pos=load_positions(user_id=uid)

positions_tab,watch,thesis_tab=st.tabs(['Positions','Watchlist','Thesis Tracker'])

with positions_tab:
    if pos.empty:
        st.info('No hay posiciones guardadas. Agregalas desde Portfolio Risk o Broker Import.')
    else:
        ticks=pos['ticker'].astype(str).str.upper().tolist()
        pm=download_prices(ticks,period='1y')
        rows=[]
        for _,p in pos.iterrows():
            t=str(p['ticker']).upper(); raw=pm.get(t)
            if raw is None or raw.empty: continue
            px=float(raw['Close'].dropna().iloc[-1]); qty=float(p['quantity']); cost=float(p['avg_cost'])
            value=qty*px; invested=qty*cost; pnl=value-invested; pnl_pct=(px/cost-1)*100 if cost>0 else None
            rows.append({'Ticker':t,'Quantity':qty,'Avg Cost':cost,'Price':px,'Market Value':value,'Unrealized P&L $':pnl,
                         'Unrealized P&L %':pnl_pct,'Sector':p.get('sector','Unknown'),'Note':p.get('note','')})
        out=pd.DataFrame(rows)
        if out.empty:
            st.warning('No se pudieron obtener precios para las posiciones guardadas.')
        else:
            total=float(out['Market Value'].sum()); invested=float((out['Quantity']*out['Avg Cost']).sum()); pnl=total-invested
            c1,c2,c3,c4=st.columns(4)
            c1.metric('Market Value',f'${total:,.0f}')
            c2.metric('Cost Basis',f'${invested:,.0f}')
            c3.metric('Unrealized P&L',f'${pnl:,.0f}',delta=f'{(total/invested-1)*100:+.1f}%' if invested>0 else None)
            c4.metric('Positions',len(out))
            out['Weight %']=out['Market Value']/total*100 if total>0 else 0
            st.dataframe(out.sort_values('Market Value',ascending=False),use_container_width=True,hide_index=True)

with watch:
    saved_ticks=pos['ticker'].astype(str).tolist() if not pos.empty else []
    initial=list(dict.fromkeys(st.session_state.portfolio_tickers or saved_ticks))
    text=st.text_area('Tickers separados por coma',value=','.join(initial),height=90)
    if st.button('Actualizar watchlist',type='primary'):
        st.session_state.portfolio_tickers=[x.strip().upper() for x in text.replace('\n',',').split(',') if x.strip()]
        st.rerun()
    ticks=st.session_state.portfolio_tickers or initial
    if ticks:
        pm=download_prices(list(dict.fromkeys(ticks+['SPY'])),period='2y'); spy=pm.get('SPY')
        rows=[]
        for t in ticks:
            try:
                raw=pm.get(t)
                if raw is None or raw.empty: continue
                typ=classify_symbol(t); r=analyze_asset(t,enrich_indicators(raw),spy,'Portfolio',typ)
                action='BUY ZONE' if r['Entry_Score']>=75 and r['Trend_Score']>=65 and (pd.isna(r['RR']) or r['RR']>=1.5) else 'EXTENDED / TRIM' if r['Scan_Extended_Trim'] else 'WATCH' if r['Entry_Score']>=58 else 'HOLD / WAIT'
                rows.append({'Ticker':t,'Type':typ,'Price':r['Price'],'Trend':r['Trend'],'Trend Score':r['Trend_Score'],'Entry Score':r['Entry_Score'],'Risk Score':r['Risk_Score'],'R/R':r['RR_Text'],'Setup':r['Setup'],'Action':action})
            except Exception as e:
                st.caption(f'{t}: datos incompletos ({type(e).__name__})')
        if rows: st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    else:
        st.info('Agregá tickers para construir la watchlist.')

with thesis_tab:
    section_note('Guardá por qué compraste, qué debería ocurrir y qué invalida la tesis. Las tesis son privadas por usuario.')
    default_tickers=pos['ticker'].astype(str).tolist() if not pos.empty else st.session_state.portfolio_tickers
    ticker=st.selectbox('Ticker',list(dict.fromkeys(default_tickers)) or ['GEV'])
    existing=load_theses(ticker,user_id=uid)
    old=existing.iloc[0].to_dict() if not existing.empty else {}
    thesis=st.text_area('Tesis',value=str(old.get('thesis','') or ''),height=100)
    catalysts=st.text_area('Catalizadores',value=str(old.get('catalysts','') or ''),height=80)
    invalidation=st.text_area('Invalidación',value=str(old.get('invalidation','') or ''),height=80)
    c1,c2,c3=st.columns(3)
    target=c1.text_input('Target / valoración objetivo',value=str(old.get('target','') or ''))
    statuses=['ACTIVE','WATCH','TRIM','CLOSED']; old_status=str(old.get('status','ACTIVE') or 'ACTIVE')
    status=c2.selectbox('Estado',statuses,index=statuses.index(old_status) if old_status in statuses else 0)
    old_review=pd.to_datetime(old.get('review_date'),errors='coerce')
    review=c3.date_input('Próxima revisión',value=(old_review.date() if pd.notna(old_review) else date.today()))
    note=st.text_input('Nota',value=str(old.get('note','') or ''))
    c1,c2=st.columns(2)
    if c1.button('Guardar tesis',type='primary',use_container_width=True):
        try:
            upsert_thesis(ticker,thesis,catalysts,invalidation,target,review,status,note,user_id=uid)
            st.success('Tesis guardada.'); st.rerun()
        except Exception as exc: st.error(f'No se pudo guardar: {exc}')
    if c2.button('Eliminar tesis',use_container_width=True):
        try:
            delete_thesis(ticker,user_id=uid); st.rerun()
        except Exception as exc: st.error(f'No se pudo eliminar: {exc}')
    all_theses=load_theses(user_id=uid)
    if not all_theses.empty:
        st.subheader('Tesis guardadas'); st.dataframe(all_theses,use_container_width=True,hide_index=True)
