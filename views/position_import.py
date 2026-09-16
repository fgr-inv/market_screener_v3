import streamlit as st

from core.access_control import current_user
from core.portfolio_import import normalize_positions_csv
from core.storage import upsert_position
from core.ui import hero, safe_error


hero('Portfolio Import','Carga manual de posiciones desde CSV, sin conexión a brokers ni credenciales.','Portfolio Data')
user=current_user(); uid=user['user_id']

st.subheader('CSV import')
st.caption('Columnas requeridas: ticker/symbol y quantity/qty. El costo promedio es opcional.')
uploaded=st.file_uploader('Portfolio positions CSV',type=['csv'])
if uploaded is not None:
    try:
        frame=normalize_positions_csv(uploaded); st.dataframe(frame,width='stretch',hide_index=True)
        replace_zero=st.checkbox('Importar también posiciones con cantidad 0',value=False)
        if st.button('Importar al portfolio',type='primary'):
            imported=0
            for _,row in frame.iterrows():
                if float(row['quantity'])==0 and not replace_zero: continue
                upsert_position(row['ticker'],row['quantity'],row['avg_cost'],user_id=uid); imported+=1
            st.success(f'{imported} posiciones actualizadas.')
    except Exception as exc:
        safe_error('No se pudo leer el CSV. Revisá que incluya ticker, cantidad y costo promedio.',exc,
                   event='portfolio_csv_preview_error')

st.info('Esta pantalla solo actualiza el portfolio interno. No consulta cuentas externas ni puede enviar órdenes.')
