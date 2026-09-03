import pandas as pd
import streamlit as st
from core.access_control import current_user

from core.storage import load_positions,upsert_position,delete_position
from core.market_data import download_prices
from core.portfolio_risk import portfolio_risk,high_correlation_pairs
from core.themes import theme_exposure
from core.ui import hero, section_note

hero('Portfolio Risk','Peso, contribución al riesgo, concentración temática, correlaciones, beta, VaR y drawdown.','Risk Workstation V8')
user=current_user(); uid=user['user_id']
pos=load_positions(user_id=uid)

with st.sidebar:
    st.header('Agregar / editar posición')
    t=st.text_input('Ticker','NVDA').strip().upper()
    mode=st.radio('Modo de carga',['Porcentaje actual','Cantidad y costo'])
    if mode=='Porcentaje actual':
        allocation=st.number_input('Porcentaje de la cartera (%)',min_value=0.1,max_value=100.0,value=10.0,step=0.5)
        q=0.0; c=0.0
        st.caption('No necesitás indicar capital total ni cantidad. El porcentaje se usa directamente en todos los análisis de riesgo.')
    else:
        allocation=None
        q=st.number_input('Cantidad',min_value=0.000001,value=10.0,step=1.0,format='%.6f')
        c=st.number_input('Costo promedio',min_value=0.0,value=100.0,step=1.0)
    sec=st.text_input('Sector','Technology')
    note=st.text_input('Nota','')
    if st.button('Guardar posición',type='primary',width='stretch'):
        try:
            if allocation is not None and not pos.empty and 'allocation_pct' in pos:
                other=pos[pos['ticker'].astype(str).str.upper()!=t]['allocation_pct']
                projected=float(pd.to_numeric(other,errors='coerce').fillna(0).sum())+float(allocation)
                if projected>100.000001: raise ValueError(f'Los porcentajes sumarían {projected:.1f}%; el máximo es 100%')
            upsert_position(t,q,c,sec,note,user_id=uid,allocation_pct=allocation)
            st.rerun()
        except Exception as exc: st.error(f'No se pudo guardar: {exc}')

if pos.empty:
    st.info('Agregá posiciones desde la barra lateral.'); st.stop()

tickers=pos['ticker'].astype(str).tolist(); pm=download_prices(list(dict.fromkeys(tickers+['SPY'])),period='2y')
summary,detail,corr=portfolio_risk(pos,pm)
if summary.get('Allocation Status')=='OVER_ALLOCATED':
    st.error(f"Los porcentajes suman {summary.get('Allocation Total %',0):.1f}%. Editá las posiciones hasta que el total sea como máximo 100%.")
    st.dataframe(pos,width='stretch',hide_index=True); st.stop()
themes=theme_exposure(detail); pairs=high_correlation_pairs(corr)

metric_keys=['Market Value','Allocation Total %','Cash / Unassigned %','Annualized Vol %','1d VaR 95 $',
             '1d CVaR 95 $','Historical Max Drawdown %','Portfolio Beta','Largest Position %','Largest Sector %','Effective # Positions']
for start,size in ((0,4),(4,4),(8,3)):
    cols=st.columns(size)
    for col,key in zip(cols,metric_keys[start:start+size]):
        value=summary.get(key)
        col.metric(key,'N/D' if value is None or pd.isna(value) else f'{value:,.2f}')
st.caption(f"Allocation basis: {summary.get('Allocation Basis','N/D')}. Unassigned percentage is treated as cash with zero return in risk calculations.")

t1,t2,t3,t4=st.tabs(['Risk Contribution','Themes','Correlations','Positions'])
with t1:
    section_note('Peso de capital y contribución al riesgo no son lo mismo. Un activo volátil puede aportar mucho más riesgo que su peso.')
    cols=['Ticker','Sector','Weight %','Risk Contribution %','Risk / Weight','Standalone Vol %','Market Value','Price','Allocation Source']
    st.dataframe(detail[[c for c in cols if c in detail]].sort_values('Risk Contribution %',ascending=False),width='stretch',hide_index=True)
    if 'Risk Contribution %' in detail: st.bar_chart(detail.set_index('Ticker')['Risk Contribution %'])
with t2:
    section_note('Clasificación económica transversal: detecta concentración AI/power/crypto que GICS puede ocultar.')
    st.dataframe(themes,width='stretch',hide_index=True)
    if not themes.empty: st.bar_chart(themes.set_index('Theme')['Weight %'])
with t3:
    st.dataframe(corr.round(2),width='stretch')
    if not pairs.empty:
        st.warning('Pares con correlación ≥ 0.80')
        st.dataframe(pairs,width='stretch',hide_index=True)
with t4:
    display=pos.copy()
    if 'allocation_pct' in display:
        display['input_mode']=display['allocation_pct'].apply(lambda value:'PERCENTAGE' if pd.notna(value) and float(value)>0 else 'QUANTITY')
    st.dataframe(display,width='stretch',hide_index=True)
    kill=st.selectbox('Ticker a eliminar',['—']+tickers)
    if kill!='—' and st.button('Eliminar'):
        delete_position(kill,user_id=uid); st.rerun()

st.subheader('Risk Diagnostics')
flags=[]
if summary.get('Largest Position %',0)>20: flags.append('⚠️ Una posición supera 20% de la cartera.')
if summary.get('Largest Sector %',0)>35: flags.append('⚠️ Un sector supera 35% de la cartera.')
if pd.notna(summary.get('Portfolio Beta')) and summary.get('Portfolio Beta',0)>1.25: flags.append('⚠️ Beta de cartera elevada.')
if not pairs.empty: flags.append(f'⚠️ {len(pairs)} pares tienen correlación ≥ 0.80.')
if not detail.empty:
    high_rc=detail[detail['Risk Contribution %']>detail['Weight %']*1.75]
    if not high_rc.empty: flags.append('⚠️ Aportan riesgo desproporcionado: '+', '.join(high_rc['Ticker'].head(8)))
if not themes.empty and themes.iloc[0]['Weight %']>30: flags.append(f"⚠️ Tema dominante: {themes.iloc[0]['Theme']} ({themes.iloc[0]['Weight %']:.1f}%).")
for f in flags: st.write(f)
if not flags: st.success('No aparecen concentraciones extremas con los umbrales V8.')
