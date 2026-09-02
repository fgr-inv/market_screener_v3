import pandas as pd
import streamlit as st
from core.ui import hero,section_note
from core.access_control import current_user
from core.market_data import download_prices
from core.technical_agent import analyze_technical
from core.verification_agent import verify_result
from core.cio_agent import build_cio_brief
from core.agent_audit import append_agent_audit,load_agent_audit

hero('Investment Desk','CIO + Technical Signal + Verification · Phase 1 shadow mode.','Agent Desk V1')
section_note('Research only. No agent can place, modify or cancel an order. CURRENT / STALE / NOT_CHECKED / UNAVAILABLE / FAILED remain explicit.')
user=current_user(); uid=user['user_id']
source=st.session_state.get('scan_results')
defaults=[] if source is None or source.empty or 'Ticker' not in source else source['Ticker'].dropna().astype(str).head(12).tolist()
tickers=st.text_input('Tickers to review',value=', '.join(defaults or ['SPY','QQQ'])).upper()
tickers=list(dict.fromkeys(x.strip() for x in tickers.replace('\n',',').split(',') if x.strip()))[:25]
run=st.button('Run shadow review',type='primary',disabled=not tickers)
if run:
    with st.status('Running specialist → verifier → CIO...',expanded=True) as status:
        histories=download_prices(tickers,period='2y')
        verified=[]
        for ticker in tickers:
            result=analyze_technical(ticker,histories.get(ticker))
            result=verify_result(result); verified.append(result)
            append_agent_audit(uid,'specialist_verified',result.to_dict())
        brief=build_cio_brief(verified)
        append_agent_audit(uid,'cio_brief',brief)
        st.session_state['_agent_desk_brief']=brief
        status.update(label='Shadow review complete',state='complete',expanded=False)
brief=st.session_state.get('_agent_desk_brief')
if brief:
    st.subheader('CIO Brief'); st.info(brief['headline'])
    for d in brief['decisions']:
        with st.expander(f"{d['subject']} · {d['state']} · confidence {d['confidence']:.0%}",expanded=True):
            st.write(d['summary']); st.caption(f"Verification: {d['verification_status']}")
            ev=pd.DataFrame(d.get('evidence',[]))
            if not ev.empty: st.dataframe(ev[['claim','value','source','observed_at','status','note']],use_container_width=True,hide_index=True)
            if d.get('contradicting_evidence'): st.warning('Contradicting evidence: '+' | '.join(d['contradicting_evidence']))
            st.caption('Alternative explanation: '+(d.get('alternative_explanation') or 'N/D'))
    if brief['blocked_or_low_trust']:
        st.subheader('Blocked / low-trust')
        st.dataframe(pd.DataFrame([{'Ticker':x.get('subject'),'State':x.get('state'),'Verification':x.get('verification_status'),'Confidence':x.get('confidence')} for x in brief['blocked_or_low_trust']]),use_container_width=True,hide_index=True)
st.subheader('Audit trail')
audit=load_agent_audit(uid,100)
if audit.empty: st.caption('No agent runs logged yet.')
else: st.dataframe(audit[['ts','event_type']],use_container_width=True,hide_index=True)
st.caption('Phase 1 is intentionally SHADOW MODE: analysis → verification → CIO → human. No execution path exists.')
