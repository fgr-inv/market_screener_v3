import pandas as pd
import streamlit as st
from core.ui import hero,section_note
from core.advanced_options import advanced_options_snapshot
from core.institutional_providers import polygon_short_interest,finnhub_insider_transactions
from core.free_market_providers import free_crypto_derivatives_snapshot

hero('Advanced Derivatives & Positioning','IV term structure, unusual options, crowding y datos públicos/free-first.','Derivatives Intelligence')
ticker=st.text_input('Ticker','NVDA').upper().strip()
if not ticker: st.stop()

with st.spinner('Analizando opciones...'):
    opt=advanced_options_snapshot(ticker)
a,b,c,d=st.columns(4)
a.metric('ATM IV term proxy', 'N/D' if opt['term_structure'].empty else f"{opt['term_structure'].iloc[0]['atm_iv_%']:.1f}%")
b.metric('IV Rank proxy', 'N/D' if opt.get('iv_rank_proxy_%')!=opt.get('iv_rank_proxy_%') else f"{opt['iv_rank_proxy_%']:.0f}%")
c.metric('Max Pain proxy', 'N/D' if opt.get('max_pain')!=opt.get('max_pain') else f"${opt['max_pain']:.2f}")
d.metric('Unusual contracts',len(opt.get('unusual_flow',[])))
st.caption(opt.get('note',''))
st.dataframe(opt['term_structure'],width='stretch',hide_index=True)
with st.expander('Unusual options heuristic'):
    st.dataframe(opt['unusual_flow'],width='stretch',hide_index=True)

st.subheader('Positioning / optional enrichments')
short=polygon_short_interest(ticker)
if short.get('available'):
    s1,s2,s3,s4=st.columns(4)
    s1.metric('Short interest',f"{float(short.get('short_interest')):,.0f}" if pd.notna(short.get('short_interest')) else 'N/D')
    s2.metric('Days to cover',f"{float(short.get('days_to_cover')):.2f}" if pd.notna(short.get('days_to_cover')) else 'N/D')
    s3.metric('Average daily volume',f"{float(short.get('avg_daily_volume')):,.0f}" if pd.notna(short.get('avg_daily_volume')) else 'N/D')
    s4.metric('Settlement date',short.get('settlement_date') or 'N/D')
    st.caption(f"Fuente: {short.get('provider','Polygon')}.")
else:
    reason=str(short.get('reason') or '')
    if 'Missing POLYGON_API_KEY' in reason:
        st.info('Short interest no disponible: POLYGON_API_KEY no está configurada.')
    else:
        st.info('Short interest no disponible temporalmente. El detalle técnico quedó registrado en los logs.')
ins=finnhub_insider_transactions(ticker)
if len(ins): st.dataframe(ins.head(50),width='stretch',hide_index=True)
else: st.info('Insider premium feed not configured or unavailable.')

if ticker in {'BTC','ETH','BTC-USD','ETH-USD'}:
    st.subheader('Crypto derivatives — free multi-exchange')
    crypto=free_crypto_derivatives_snapshot('BTC' if ticker.startswith('BTC') else 'ETH')
    c1,c2,c3,c4=st.columns(4)
    funding=crypto.get('Funding_Rate_OI_Weighted_%')
    oi=crypto.get('Open_Interest_USD')
    oi_change=crypto.get('Open_Interest_24h_%')
    basis=crypto.get('Perp_Basis_OI_Weighted_%')
    c1.metric('Funding OI-weighted','N/D' if pd.isna(funding) else f'{float(funding):.4f}%')
    c2.metric('Open interest','N/D' if pd.isna(oi) else f'${float(oi):,.0f}')
    c3.metric('Open interest 24h','N/D' if pd.isna(oi_change) else f'{float(oi_change):+.2f}%')
    c4.metric('Perpetual basis','N/D' if pd.isna(basis) else f'{float(basis):+.4f}%')
    components=[]
    for provider,payload in (crypto.get('Components') or {}).items():
        components.append({
            'Proveedor':provider,
            'Estado':'Disponible' if payload.get('available') else 'No disponible',
            'Funding %':payload.get('Funding_Rate_%'),
            'Open Interest $':payload.get('Open_Interest_USD'),
            'Basis %':payload.get('Perp_Basis_%'),
            'Long/Short':payload.get('Long_Short_Ratio'),
        })
    if components:
        st.dataframe(pd.DataFrame(components),width='stretch',hide_index=True)
    st.caption(crypto.get('Coverage_Note',''))
