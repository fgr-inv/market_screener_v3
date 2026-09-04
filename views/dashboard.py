import pandas as pd
import streamlit as st

from core.refresh import build_market_snapshot
from core.storage import load_latest_snapshot, load_json_snapshot, load_score_history
from core.change_detection import latest_changes
from core.ui import hero, section_note, badge, traffic_tone
from core.utils import fmt_num
from core.data_quality import freshness_score,quality_label

hero('Market Dashboard','Snapshot-first + cambios materiales + calidad/frescura de datos.','Daily Market Intelligence V8')

with st.sidebar:
    st.caption('Lee snapshots persistidos primero. La actualización completa reconstruye breadth, macro y screener.')
    refresh=st.button('🔄 Actualizar mercado ahora',type='primary',width='stretch')

if st.session_state.scan_results is None:
    cached=load_latest_snapshot('latest_screener'); sectors=load_latest_snapshot('latest_sectors'); breadth=load_latest_snapshot('latest_breadth')
    macro=load_json_snapshot('latest_macro'); meta=load_json_snapshot('latest_meta')
    if not cached.empty: st.session_state.scan_results=cached
    if not sectors.empty: st.session_state.sector_snapshot=sectors
    if not breadth.empty: st.session_state.macro_breadth_detail=breadth
    if macro: st.session_state.macro_snapshot=macro
    if meta: st.session_state.last_refresh_label=meta.get('generated_at','snapshot')

if refresh:
    with st.status('Actualizando mercado completo...',expanded=True) as status:
        st.write('Reconstruyendo breadth, macro y screener. Los siguientes accesos vuelven a usar snapshot.')
        snap=build_market_snapshot(scan_limit=220)
        st.session_state.scan_results=snap['results']; st.session_state.sector_snapshot=snap['sectors']
        st.session_state.macro_breadth_detail=snap['breadth']; st.session_state.macro_snapshot=snap['macro']
        st.session_state.scan_price_map=snap['price_map']; st.session_state.last_refresh_label=snap['meta']['generated_at']
        status.update(label='Mercado actualizado',state='complete',expanded=False)

m=st.session_state.macro_snapshot; results=st.session_state.scan_results; sectors=st.session_state.sector_snapshot
if m is None or results is None or results.empty:
    st.warning('No existe snapshot. Ejecutá **Actualizar mercado ahora** o el workflow Daily market snapshot.'); st.stop()

fresh=freshness_score(st.session_state.last_refresh_label,max_age_hours=36)
coverage=float(results['Confidence_Score'].mean()) if 'Confidence_Score' in results and results['Confidence_Score'].notna().any() else 0
c1,c2,c3,c4,c5,c6=st.columns(6)
c1.metric('Institutional Macro',f'{m.get("Macro_Score",50)}/100')
c2.metric('Risk Regime',m.get('Institutional_Regime',m.get('Risk_Regime','N/D')))
c3.metric('Breadth',f'{float(m.get("Breadth",50)):.0f}/100')
c4.metric('VIX',fmt_num(m.get('VIX')))
c5.metric('Snapshot Freshness',f'{fresh}/100')
c6.metric('Avg Confidence',f'{coverage:.0f}/100')

st.markdown(
    badge(m.get('Momentum','N/D'),'good' if m.get('Momentum')=='IMPROVING' else 'bad' if m.get('Momentum')=='DETERIORATING' else 'neutral')+
    badge(m.get('Economic_Regime_Slow',m.get('Economic_Regime','N/D')),'warn')+
    badge(f'DATA {quality_label(round(.6*fresh+.4*coverage))}',traffic_tone(.6*fresh+.4*coverage)),unsafe_allow_html=True)

st.subheader('⚡ What Changed?')
section_note('Cambios materiales entre los dos últimos snapshots: evita releer toda la terminal para detectar qué cambió.')
changes=latest_changes(load_score_history(days=10),min_abs_delta=5,limit=20)
if changes.empty: st.info('Se necesitan al menos dos días de snapshots para calcular cambios materiales.')
else: st.dataframe(changes,width='stretch',hide_index=True)

st.subheader('🧭 Sector leadership')
section_note('Fuerza + entrada + macro fit. Liderazgo no equivale automáticamente a compra.')
if sectors is not None and not sectors.empty: st.dataframe(sectors,width='stretch',hide_index=True)

st.subheader('🔥 Best setups from snapshot')
rank_col='Preliminary_Score' if 'Preliminary_Score' in results else 'Technical_Score'
top=results.sort_values([rank_col,'Entry_Score'],ascending=False).head(20)
cols=['Ticker','Sector',rank_col,'Trend_Score','Entry_Score','RS_Percentile','Sector_Score','Macro_Fit','Risk_Score','Confidence_Score','Model_Coverage_%','RR_Text','Setup','Action']
st.dataframe(top[[c for c in cols if c in top]],width='stretch',hide_index=True)
st.caption(f'Último snapshot: {st.session_state.last_refresh_label}')
