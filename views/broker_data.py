import streamlit as st
from core.ui import hero, safe_error
from core.broker_import import normalize_positions_csv,alpaca_positions
from core.storage import upsert_position
from core.access_control import current_user

hero('Broker & Execution Import','Importación read-only de posiciones; no envía órdenes.','Execution Data')
user=current_user(); uid=user['user_id']

st.subheader('CSV import')
f=st.file_uploader('Broker positions CSV',type=['csv'])
if f is not None:
    try:
        df=normalize_positions_csv(f); st.dataframe(df,width='stretch',hide_index=True)
        replace_zero=st.checkbox('Importar también posiciones con cantidad 0',value=False)
        if st.button('Importar al portfolio',type='primary'):
            imported=0
            for _,r in df.iterrows():
                if float(r['quantity'])==0 and not replace_zero: continue
                upsert_position(r['ticker'],r['quantity'],r['avg_cost'],user_id=uid); imported+=1
            st.success(f'{imported} posiciones actualizadas.')
    except Exception as exc:
        safe_error('No se pudo leer el CSV. Revisá que incluya ticker, cantidad y costo promedio.',exc,
                   event='broker_csv_preview_error')

st.subheader('Alpaca read-only')
if user.get('role')!='OWNER':
    st.info('La conexión Alpaca con credenciales del servidor está reservada al OWNER. Para usuarios, usá CSV hasta implementar OAuth/credenciales por cuenta.')
else:
    if st.button('Leer posiciones Alpaca'):
        df,msg=alpaca_positions()
        if len(df):
            st.session_state['alpaca_positions_preview']=df
            st.dataframe(df,width='stretch',hide_index=True)
        else: st.warning(msg)
    preview=st.session_state.get('alpaca_positions_preview')
    if preview is not None and len(preview):
        if st.button('Importar posiciones Alpaca al portfolio'):
            try:
                for _,r in preview.iterrows(): upsert_position(r['ticker'],r['quantity'],r['avg_cost'],user_id=uid)
                st.success(f'{len(preview)} posiciones importadas.'); st.rerun()
            except Exception as exc:
                safe_error('No se pudieron importar las posiciones de Alpaca. No se modificó ninguna orden.',exc,
                           event='alpaca_portfolio_import_error')
st.caption('No hay ejecución automática de trades. Las credenciales de broker se usan únicamente para lectura de posiciones.')
