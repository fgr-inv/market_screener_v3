import streamlit as st
import pandas as pd
from core.free_sources_v11 import free_source_catalog
from core.point_in_time import zero_cost_point_in_time_contracts

st.title('🧩 Free-Data Professional Coverage')
st.caption('V11 master map: what is implemented with public/free sources, what is prospectively accumulated, and what must remain missing when no reliable free source exists.')

st.subheader('Free/public provider catalog')
st.dataframe(free_source_catalog(),use_container_width=True,hide_index=True)

st.subheader('Point-in-time warehouse contracts')
rows=[]
for name,cols in zero_cost_point_in_time_contracts().items():rows.append({'Dataset':name,'Fields':', '.join(cols)})
st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

st.subheader('Professional rule')
st.info('Missing data ≠ neutral data. Missing specialist fields reduce coverage/confidence and are never fabricated. Historical fields are only called point-in-time when they were actually captured or come from a vintage-aware official source.')

st.subheader('Coverage domains')
st.markdown('''
**Equities:** fundamentals, acceleration, forensics, capital allocation, moat proxies, revisions, insiders/13F filing discovery, short-volume contracts, peers, valuation, technical, events, portfolio fit.  
**ETF:** look-through, concentration/effective holdings, holdings-history contract, factor/sector aggregation.  
**Commodities:** physical-energy data, COT history, futures-curve regime, agriculture/weather source contracts, macro transmission.  
**Crypto:** network/on-chain community metrics, stablecoin liquidity, token dilution, derivatives, TVL, BTC mining/mempool.  
**Rates/credit:** curve regimes, real yields/breakevens/credit-spread inputs, macro vintages.  
**FX:** rate/real-rate/growth/carry/COT/risk/trend framework.  
**Portfolio/quant:** walk-forward validation, probability calibration, attribution, drift, correlation regimes, stress testing, execution quality, source reconciliation and lineage.
''')
