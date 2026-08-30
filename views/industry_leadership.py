import pandas as pd
import streamlit as st
from core.industry import get_industry, industry_leadership
from core.ui import hero, section_note

hero('Industry Leadership','Drill-down sector → industry → stock usando el último screener.','Industry Rotation')
res=st.session_state.scan_results
if res is None or res.empty:
    st.info('Ejecutá primero Professional Screener.'); st.stop()

work=res.copy()
if 'Industry' not in work.columns:
    top_n=st.slider('Tickers a enriquecer con industria',10,min(100,len(work)),min(40,len(work)))
    if st.button('Load industries',type='primary'):
        inds=[]
        ranked=work.sort_values('Preliminary_Score',ascending=False).head(top_n)
        mapping={}
        with st.status('Loading industry metadata...',expanded=True) as status:
            for i,t in enumerate(ranked['Ticker'].tolist(),1):
                mapping[t]=get_industry(t).get('Industry','Unknown')
                st.write(f'{i}/{len(ranked)} {t}')
            status.update(label='Industry metadata loaded',state='complete',expanded=False)
        work['Industry']=work['Ticker'].map(mapping).fillna('Not loaded')
        st.session_state.scan_results=work
else:
    work=res.copy()

if 'Industry' in work.columns:
    table=industry_leadership(work[work['Industry']!='Not loaded'])
    st.dataframe(table,use_container_width=True,hide_index=True)
    section_note('Industry ranking only uses names whose industry metadata has been loaded. For full-universe production use a dedicated fundamentals/industry provider or persist metadata daily.')
