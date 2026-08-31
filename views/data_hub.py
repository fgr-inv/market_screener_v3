from pathlib import Path
import pandas as pd
import streamlit as st
from core.access_control import current_user
from core.ui import hero,section_note
from core.institutional_providers import provider_capabilities
from core.point_in_time import premium_data_contracts, point_in_time_status
from core.production_storage import cloud_available

hero('Institutional Data Hub','Conectores premium, datasets point-in-time y persistencia de producción.','Data Infrastructure')
user=current_user()
if user.get('role')!='OWNER':
    st.error('🔒 Esta página es solo para OWNER / administración.')
    st.stop()

st.subheader('Provider capabilities')
st.dataframe(provider_capabilities(),use_container_width=True,hide_index=True)

st.subheader('Point-in-time datasets')
section_note('Sin estos históricos, revisiones/short/options/backtests pueden tener survivorship o look-ahead bias.')
contracts=premium_data_contracts()
st.dataframe(pd.DataFrame([{'File':k,'Required columns':', '.join(v)} for k,v in contracts.items()]),use_container_width=True,hide_index=True)

st.write(point_in_time_status('SP500')['note'])

uploaded=st.file_uploader('Subir dataset premium CSV',type=['csv'])
kind=st.selectbox('Guardar como',list(contracts.keys()))
if uploaded is not None and st.button('Guardar dataset'):
    df=pd.read_csv(uploaded)
    required=contracts[kind]
    missing=[c for c in required if c not in df.columns]
    if missing: st.error('Faltan columnas: '+', '.join(missing))
    else:
        target=Path(__file__).resolve().parents[1]/'data'/'premium'/('point_in_time' if 'constituents' in kind or 'historical_' in kind else '')/kind
        target.parent.mkdir(parents=True,exist_ok=True); df.to_csv(target,index=False)
        st.success(f'Guardado: {target.name}')

st.subheader('Cloud persistence')
st.metric('DATABASE_URL', 'CONFIGURED' if cloud_available() else 'LOCAL ONLY')
st.caption('DuckDB sigue siendo el fallback local. Para producción multiusuario configurá DATABASE_URL (Postgres/Supabase compatible).')
