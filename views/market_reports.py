"""Human-readable, evidence-grounded daily and weekly market reports."""
import pandas as pd
import streamlit as st

from core.access_control import current_user
from core.desk_store import load_latest_desk_output
from core.macro_sector_strategist import render_market_report_markdown
from core.ui import arrow_safe_frame, hero, key_value_frame, section_note


hero('Market Reports',
     'Análisis desarrollado de la situación macro y de los once sectores, con evidencia y verificación.',
     'Market Strategist · Research Only')
user=current_user(); uid=user['user_id']


def _show_report(frequency):
    record=load_latest_desk_output(uid,f'market_analysis_{frequency}') or {}
    report=record.get('payload') or {}
    if not report:
        st.info('Todavía no existe un informe para este período. Se generará automáticamente después del próximo snapshot.')
        return
    verification=report.get('verification') or {}; packet=report.get('evidence_packet') or {}
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Estado',verification.get('status','N/D'))
    c2.metric('Sectores',verification.get('sector_count',0))
    c3.metric('Edad del snapshot',f"{verification.get('snapshot_age_hours','N/D')} h")
    c4.metric('Cobertura macro',f"{(packet.get('coverage') or {}).get('macro_quality_pct','N/D')}%")
    if verification.get('status')=='VERIFIED': st.success('Informe verificado contra el paquete de evidencia.')
    elif verification.get('status')=='PARTIALLY_VERIFIED': st.warning('Informe utilizable con limitaciones: '+', '.join(report.get('limitations') or []))
    else: st.error('El informe no superó el control de evidencia y no debe utilizarse para decisiones.')
    st.markdown(render_market_report_markdown(report))
    with st.expander('Ver paquete de evidencia'):
        st.caption(f"Snapshot: {report.get('snapshot_generated_at','N/D')} · Informe: {report.get('generated_at','N/D')}")
        st.dataframe(key_value_frame(packet.get('macro') or {},'Variable macro','Valor'),width='stretch',hide_index=True)
        sector_rows=pd.DataFrame(packet.get('sectors') or [])
        if not sector_rows.empty:
            columns=['sector','etf','rank','strength','macro_fit','uptrend_pct','above_sma200_pct',
                     'median_rs63_pct','strength_change','leaders']
            st.dataframe(arrow_safe_frame(sector_rows[[c for c in columns if c in sector_rows]]),
                         width='stretch',hide_index=True)
    st.caption('Research y simulación interna. No constituye recomendación ni puede generar órdenes.')


daily,weekly=st.tabs(['Diario','Semanal'])
with daily: _show_report('daily')
with weekly: _show_report('weekly')
section_note('El redactor no consulta fuentes por su cuenta: interpreta un snapshot congelado. Un verificador separado controla vigencia, cobertura y referencias antes de publicar.')
