import streamlit as st
from core.ui import hero
from core.broker_import import normalize_positions_csv,alpaca_positions
from core.storage import upsert_position

hero('Broker & Execution Import','Importación read-only de posiciones; no envía órdenes.','Execution Data')

st.subheader('CSV import')
f=st.file_uploader('Broker positions CSV',type=['csv'])
if f is not None:
    try:
        df=normalize_positions_csv(f); st.dataframe(df,use_container_width=True,hide_index=True)
        if st.button('Importar al portfolio local'):
            for _,r in df.iterrows(): upsert_position(r['ticker'],r['quantity'],r['avg_cost'])
            st.success('Portfolio actualizado.')
    except Exception as e: st.error(str(e))

st.subheader('Alpaca read-only')
if st.button('Leer posiciones Alpaca'):
    df,msg=alpaca_positions()
    if len(df): st.dataframe(df,use_container_width=True,hide_index=True)
    else: st.warning(msg)
st.caption('No hay ejecución automática de trades en esta versión. La integración es deliberadamente read-only.')
