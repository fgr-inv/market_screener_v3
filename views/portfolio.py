from datetime import date
import pandas as pd
import streamlit as st

from core.market_data import download_prices, classify_symbol
from core.indicators import enrich_indicators
from core.asset_models import analyze_asset
from core.storage import load_positions, load_theses, upsert_position, upsert_thesis, delete_thesis
from core.portfolio_positions import resolve_position_allocations
from core.portfolio_metadata import infer_position_sectors, sector_is_missing
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
        out,allocation=resolve_position_allocations(pos,pm)
        if not out.empty:
            out['Unrealized P&L $']=out.apply(lambda row:(row['Market Value']-row['Quantity']*row['Avg Cost']) if pd.notna(row['Market Value']) and row['Avg Cost']>0 else None,axis=1)
            out['Unrealized P&L %']=out.apply(lambda row:(row['Price']/row['Avg Cost']-1)*100 if pd.notna(row['Price']) and row['Avg Cost']>0 else None,axis=1)
        if out.empty:
            st.warning('No se pudieron obtener precios para las posiciones guardadas.')
        elif allocation['status']=='OVER_ALLOCATED':
            st.error(f"Los porcentajes cargados suman {allocation['allocation_total_pct']:.1f}%. Deben sumar como máximo 100%.")
            st.dataframe(out,width='stretch',hide_index=True)
        else:
            unknown_count=int(pos['sector'].apply(sector_is_missing).sum()) if 'sector' in pos else len(pos)
            if unknown_count:
                st.warning(f'{unknown_count} posiciones no tienen sector. Esto distorsiona Portfolio Fit y la concentración sectorial.')
                if st.button('Completar sectores automáticamente',type='primary'):
                    with st.spinner('Clasificando posiciones...'):
                        inferred=infer_position_sectors(pos,live_fallback=True)
                        for _,saved in pos.iterrows():
                            ticker=str(saved['ticker']).upper()
                            if ticker not in inferred: continue
                            allocation_pct=None if pd.isna(saved.get('allocation_pct')) else float(saved.get('allocation_pct'))
                            upsert_position(ticker,float(saved.get('quantity',0) or 0),float(saved.get('avg_cost',0) or 0),
                                            inferred[ticker],str(saved.get('note','') or ''),user_id=uid,allocation_pct=allocation_pct)
                    if inferred:
                        st.success(f'Se actualizaron {len(inferred)} sectores.'); st.rerun()
                    else: st.error('No se pudo clasificar ninguna posición con las fuentes disponibles.')
            c1,c2,c3,c4=st.columns(4)
            coverage_note=None
            if allocation['basis']=='QUANTITY':
                total=float(allocation['dollar_total'])
                covered=(out['Quantity']>0)&(out['Avg Cost']>0)&out['Market Value'].notna()
                covered_value=float(out.loc[covered,'Market Value'].sum())
                invested=float((out.loc[covered,'Quantity']*out.loc[covered,'Avg Cost']).sum())
                pnl=covered_value-invested
                coverage=covered_value/total*100 if total>0 else 0
                c1.metric('Market Value',f'${total:,.0f}')
                if coverage>=99.999:
                    c2.metric('Cost Basis',f'${invested:,.0f}')
                    c3.metric('Unrealized P&L',f'${pnl:,.0f}',delta=f'{(covered_value/invested-1)*100:+.1f}%' if invested>0 else None)
                elif coverage>0:
                    c2.metric('Covered Cost Basis',f'${invested:,.0f}')
                    c3.metric('Covered P&L',f'${pnl:,.0f}',delta=f'{(covered_value/invested-1)*100:+.1f}%' if invested>0 else None)
                    coverage_note=f'Costo conocido para {coverage:.1f}% del valor de la cartera; el P&L se calcula solamente sobre esa parte.'
                else:
                    c2.metric('Cost Basis','N/D')
                    c3.metric('Unrealized P&L','N/D')
                    coverage_note='No hay costos promedio cargados. Se omite el P&L para no tratar el valor de mercado como ganancia.'
            else:
                c1.metric('Allocated',f"{allocation['allocation_total_pct']:.1f}%")
                c2.metric('Cash / unassigned',f"{allocation['cash_pct']:.1f}%")
                c3.metric('Input mode',allocation['basis'])
            c4.metric('Positions',len(out))
            if coverage_note: st.caption(coverage_note)
            st.dataframe(out.sort_values('Weight %',ascending=False),width='stretch',hide_index=True)
            if allocation['basis']=='QUANTITY':
                st.caption('Podés conservar cantidades o guardar estos pesos actuales como porcentajes para que el análisis no dependa del capital total.')
                if st.button('Convertir pesos actuales a porcentajes'):
                    for _,row in out.iterrows():
                        saved=pos[pos['ticker'].astype(str).str.upper()==str(row['Ticker']).upper()].iloc[0]
                        upsert_position(row['Ticker'],float(saved.get('quantity',0) or 0),float(saved.get('avg_cost',0) or 0),
                                        str(saved.get('sector','Unknown') or 'Unknown'),str(saved.get('note','') or ''),
                                        user_id=uid,allocation_pct=float(row['Weight %']))
                    st.success('Los pesos actuales quedaron guardados como porcentajes.'); st.rerun()

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
        if rows: st.dataframe(pd.DataFrame(rows),width='stretch',hide_index=True)
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
    if c1.button('Guardar tesis',type='primary',width='stretch'):
        try:
            upsert_thesis(ticker,thesis,catalysts,invalidation,target,review,status,note,user_id=uid)
            st.success('Tesis guardada.'); st.rerun()
        except Exception as exc: st.error(f'No se pudo guardar: {exc}')
    if c2.button('Eliminar tesis',width='stretch'):
        try:
            delete_thesis(ticker,user_id=uid); st.rerun()
        except Exception as exc: st.error(f'No se pudo eliminar: {exc}')
    all_theses=load_theses(user_id=uid)
    if not all_theses.empty:
        st.subheader('Tesis guardadas'); st.dataframe(all_theses,width='stretch',hide_index=True)
