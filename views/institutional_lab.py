import pandas as pd
import streamlit as st
from core.ui import hero,section_note
from core.institutional_v10 import free_data_coverage_contracts, load_snapshots, calibration_table, probability_calibration

hero('Institutional Research Lab','Point-in-time, calibration, event validation, relative value and evidence lineage.','V10 Research Infrastructure')
st.subheader('Zero-cost institutional data map')
st.dataframe(free_data_coverage_contracts(),use_container_width=True,hide_index=True)
section_note('Regla V10: missing ≠ neutral ≠ bad. Cada métrica debe conservar source, observation date, freshness y coverage. FRED/ALFRED vintages se usan para macro point-in-time cuando hay FRED_API_KEY.')

st.subheader('Point-in-time warehouse')
ticker=st.text_input('Asset snapshot history','SPY').strip().upper()
sn=load_snapshots(ticker)
if sn.empty: st.info('Todavía no hay snapshots para este activo. La historia se construye prospectivamente sin look-ahead.')
else:
    st.metric('Snapshots',len(sn)); st.dataframe(sn.tail(100),use_container_width=True,hide_index=True)

st.subheader('Validation contract')
st.markdown('''La validación profesional usa únicamente datos conocidos en la fecha de señal. Los retornos futuros se adjuntan **después** para evaluación. Se reportan hit-rate, median/mean forward return, P10/P90, walk-forward y calibración probabilística; no se presenta una probabilidad como calibrada hasta tener muestra suficiente.''')
