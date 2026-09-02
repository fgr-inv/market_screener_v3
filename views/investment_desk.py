import pandas as pd
import streamlit as st
from core.ui import hero,section_note
from core.access_control import current_user
from core.market_data import download_prices
from core.technical_agent import analyze_technical
from core.fundamental_agent import analyze_fundamental
from core.verification_agent import verify_result
from core.cio_agent import build_cio_brief
from core.agent_audit import append_agent_audit,load_agent_audit

hero('Investment Desk','CIO + Technical + Fundamental + Verification · rate-limit-safe shadow mode.','Agent Desk V1')
section_note('Research only. Fundamentals use one shared 7-day snapshot per ticker; valuation has a separate daily cache. Missing/stale provider data is explicit and never treated as neutral.')
user=current_user(); uid=user['user_id']
source=st.session_state.get('scan_results')
defaults=[] if source is None or source.empty or 'Ticker' not in source else source['Ticker'].dropna().astype(str).head(12).tolist()
tickers=st.text_input('Tickers to review',value=', '.join(defaults or ['SPY','QQQ'])).upper()
tickers=list(dict.fromkeys(x.strip() for x in tickers.replace('\n',',').split(',') if x.strip()))[:25]
force=st.checkbox('Force fundamental refresh',False,help='Use only after earnings/filing or when you know the cached snapshot is obsolete. This can spend provider quota.')
run=st.button('Run shadow review',type='primary',disabled=not tickers)
if run:
    with st.status('Running specialists → verifier → CIO...',expanded=True) as status:
        histories=download_prices(tickers,period='2y'); verified=[]; budget_rows=[]
        for ticker in tickers:
            for result in (analyze_technical(ticker,histories.get(ticker)), analyze_fundamental(ticker,force_refresh=force)):
                result=verify_result(result); verified.append(result)
                append_agent_audit(uid,'specialist_verified',result.to_dict())
                b=result.metadata.get('data_budget') if getattr(result,'metadata',None) else None
                if b: budget_rows.append({'Ticker':ticker,'Action':b.get('action'),'Reason':b.get('reason'),'Age hours':None if b.get('age_seconds') is None else round(b['age_seconds']/3600,1),'TTL days':round(b.get('ttl_seconds',0)/86400,1)})
        brief=build_cio_brief(verified); append_agent_audit(uid,'cio_brief',brief)
        st.session_state['_agent_desk_brief']=brief; st.session_state['_agent_budget_rows']=budget_rows
        status.update(label='Shadow review complete',state='complete',expanded=False)
brief=st.session_state.get('_agent_desk_brief')
if brief:
    st.subheader('CIO Brief'); st.info(brief['headline'])
    budget_rows=st.session_state.get('_agent_budget_rows',[])
    if budget_rows:
        with st.expander('Fundamental data budget',expanded=False):
            st.dataframe(pd.DataFrame(budget_rows),use_container_width=True,hide_index=True)
            st.caption('CACHE = zero full fundamental provider refresh for that ticker. REFRESH = the shared snapshot was absent/stale or you forced it.')
    for d in brief['decisions']:
        with st.expander(f"{d['subject']} · {d['agent']} · {d['state']} · confidence {d['confidence']:.0%}",expanded=True):
            st.write(d['summary']); st.caption(f"Verification: {d['verification_status']}")
            ev=pd.DataFrame(d.get('evidence',[]))
            if not ev.empty: st.dataframe(ev[['claim','value','source','observed_at','status','note']],use_container_width=True,hide_index=True)
            if d.get('contradicting_evidence'): st.warning('Contradicting evidence: '+' | '.join(d['contradicting_evidence']))
            st.caption('Alternative explanation: '+(d.get('alternative_explanation') or 'N/D'))
    if brief['blocked_or_low_trust']:
        st.subheader('Blocked / low-trust')
        st.dataframe(pd.DataFrame([{'Ticker':x.get('subject'),'Agent':x.get('agent'),'State':x.get('state'),'Verification':x.get('verification_status'),'Confidence':x.get('confidence')} for x in brief['blocked_or_low_trust']]),use_container_width=True,hide_index=True)
st.subheader('Audit trail')
audit=load_agent_audit(uid,100)
if audit.empty: st.caption('No agent runs logged yet.')
else: st.dataframe(audit[['ts','event_type']],use_container_width=True,hide_index=True)
st.caption('SHADOW MODE: analysis → verification → CIO → human. No execution path exists.')
