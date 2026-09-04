import pandas as pd
import streamlit as st
from core.ui import hero, section_note, badge, key_value_frame
from core.decision_engine import decision_summary
from core.storage import load_score_history
from core.model_registry import model_label

hero('Decision Center','Convierte el análisis en una decisión trazable: edge, riesgos, portfolio fit y acción.','Decision Engine')
res=st.session_state.scan_results
if res is None or res.empty:
    st.info('Ejecutá Professional Screener primero.'); st.stop()

tickers=res.sort_values('Preliminary_Score',ascending=False)['Ticker'].tolist()
ticker=st.selectbox('Ticker',tickers)
row=res[res['Ticker']==ticker].iloc[-1].to_dict()
hist=load_score_history(ticker,days=180)
edge={}
if not hist.empty and 'opportunity' in hist:
    edge['Current score history points']=len(hist)

summary=decision_summary(row,edge=edge)
st.caption(model_label())
cols=st.columns(7)
for col,(name,key) in zip(cols,[('Opportunity','Opportunity_Score'),('Confidence','Confidence_Score'),('Coverage','Model_Coverage_%'),('Quality','Quality_Score'),('Trend','Trend_Score'),('Entry','Entry_Score'),('R/R','RR_Text')]):
    v=row.get(key,'N/D'); col.metric(name,'N/D' if pd.isna(v) else v)

st.markdown(badge(summary['Action'],'good' if summary['Action']=='BUY ZONE' else 'warn'),unsafe_allow_html=True)
a,b=st.columns(2)
with a:
    st.subheader('What supports the trade')
    for x in summary['Positives'] or ['No major positive flags detected.']:
        st.write('✅',x)
with b:
    st.subheader('What can break the thesis')
    for x in summary['Negatives'] or ['No major risk flags detected.']:
        st.write('⚠️',x)

st.subheader('Score trace')
show={k:row.get(k) for k in ['Technical_Score','Trend_Score','Entry_Score','Risk_Score','Quality_Score','Valuation_Score','Revision_Score','RS_Percentile','Sector_Score','Macro_Fit','Confidence_Score','Model_Coverage_%','Available_Factors','Opportunity_Score','Event_Risk','Action']}
st.dataframe(key_value_frame(show,'Component','Value'),width='stretch',hide_index=True)
section_note('Decision Center does not auto-execute trades. It makes the final rationale explicit and auditable.')
