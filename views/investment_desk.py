import pandas as pd
import streamlit as st
from core.ui import hero,section_note
from core.access_control import current_user
from core.market_data import download_prices
from core.storage import load_positions,load_json_snapshot,load_latest_snapshot
from core.technical_agent import analyze_technical
from core.fundamental_agent import analyze_fundamental
from core.portfolio_risk_agent import analyze_portfolio_risk
from core.market_regime_agent import analyze_market_regime
from core.watchlist_engine import build_watchlist
from core.verification_agent import verify_result
from core.cio_agent import build_cio_brief
from core.agent_audit import append_agent_audit,load_agent_audit
from core.desk_store import load_latest_desk_output

hero('Investment Desk','CIO + Market Regime/Sector + Technical + Fundamental + Portfolio/Risk + Verification · shadow mode.','Agent Desk V1')
section_note('Research only. The desk reuses central market snapshots and shared price/fundamental caches, reads your saved portfolio automatically, ranks a watchlist, and never sends broker orders.')
user=current_user(); uid=user['user_id']

auto=load_latest_desk_output(uid,'daily_cio_brief') or load_latest_desk_output(uid,'scheduled_review')
if auto and auto.get('payload'):
    ap=auto['payload']; ab=ap.get('brief') or {}
    st.subheader('Latest automated CIO Brief')
    st.info(ab.get('headline','Automated desk output available'))
    st.caption(f"Background worker · {auto.get('created_at','N/D')} · SHADOW MODE")
    aw=ap.get('watchlist') or []
    if aw:
        with st.expander('Automated desk watchlist',expanded=False):
            st.dataframe(pd.DataFrame(aw),use_container_width=True,hide_index=True)
pos=load_positions(user_id=uid)
source=st.session_state.get('scan_results')
defaults=[] if source is None or source.empty or 'Ticker' not in source else source['Ticker'].dropna().astype(str).head(12).tolist()
position_ticks=[] if pos.empty else pos['ticker'].dropna().astype(str).str.upper().tolist()
seed=list(dict.fromkeys(defaults + position_ticks))[:25]
tickers=st.text_input('Tickers to review',value=', '.join(seed or ['SPY','QQQ'])).upper()
tickers=list(dict.fromkeys(x.strip() for x in tickers.replace('\n',',').split(',') if x.strip()))[:25]
force=st.checkbox('Force fundamental refresh',False,help='Use only after earnings/filing or when you know the cached snapshot is obsolete. This can spend provider quota.')
run=st.button('Run shadow review',type='primary',disabled=not tickers)

if run:
    with st.status('Running specialists → portfolio risk → verifier → CIO...',expanded=True) as status:
        all_price_ticks=list(dict.fromkeys(tickers+position_ticks))
        histories=download_prices(all_price_ticks,period='2y')
        verified=[]; budget_rows=[]

        # Market agent consumes the central daily snapshots only: zero extra FRED/provider calls here.
        macro_snapshot=load_json_snapshot('latest_macro')
        snapshot_meta=load_json_snapshot('latest_meta')
        sector_snapshot=load_latest_snapshot('latest_sectors')
        market_result=verify_result(analyze_market_regime(macro_snapshot,sector_snapshot,snapshot_meta))
        verified.append(market_result)
        append_agent_audit(uid,'market_regime_verified',market_result.to_dict())

        portfolio_result=verify_result(analyze_portfolio_risk(pos,histories))
        verified.append(portfolio_result)
        append_agent_audit(uid,'portfolio_risk_verified',portfolio_result.to_dict())

        for ticker in tickers:
            for result in (analyze_technical(ticker,histories.get(ticker)), analyze_fundamental(ticker,force_refresh=force)):
                result=verify_result(result); verified.append(result)
                append_agent_audit(uid,'specialist_verified',result.to_dict())
                b=result.metadata.get('data_budget') if getattr(result,'metadata',None) else None
                if b: budget_rows.append({'Ticker':ticker,'Action':b.get('action'),'Reason':b.get('reason'),'Age hours':None if b.get('age_seconds') is None else round(b['age_seconds']/3600,1),'TTL days':round(b.get('ttl_seconds',0)/86400,1)})

        sectors={}
        if not pos.empty:
            sectors.update({str(r['ticker']).upper():str(r.get('sector','Unknown') or 'Unknown') for _,r in pos.iterrows()})
        if source is not None and not source.empty and 'Ticker' in source and 'Sector' in source:
            sectors.update({str(r['Ticker']).upper():str(r.get('Sector','Unknown') or 'Unknown') for _,r in source.iterrows()})
        watchlist=build_watchlist(verified,portfolio_result,sectors=sectors,limit=15,market_result=market_result)
        brief=build_cio_brief(verified)
        append_agent_audit(uid,'watchlist_ranked',{'rows':watchlist,'shadow_mode':True})
        append_agent_audit(uid,'cio_brief',brief)
        st.session_state['_agent_desk_brief']=brief
        st.session_state['_agent_budget_rows']=budget_rows
        st.session_state['_agent_watchlist']=watchlist
        st.session_state['_agent_portfolio_result']=portfolio_result.to_dict()
        st.session_state['_agent_market_result']=market_result.to_dict()
        status.update(label='Shadow review complete',state='complete',expanded=False)

market_view=st.session_state.get('_agent_market_result')
if market_view:
    st.subheader('Market Regime & Sector Agent')
    mm=market_view.get('metadata') or {}
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Regime',market_view.get('state','N/D'))
    c2.metric('Macro score','N/D' if mm.get('macro_score') is None else f"{mm.get('macro_score'):.0f}/100")
    c3.metric('Momentum',mm.get('momentum','N/D'))
    c4.metric('Verification',market_view.get('verification_status','N/D'))
    st.caption(market_view.get('summary',''))
    if mm.get('leaders'):
        st.write('**Sector leaders:** '+', '.join(mm.get('leaders',[])))
    if mm.get('laggards'):
        st.write('**Sector laggards:** '+', '.join(mm.get('laggards',[])))
    if market_view.get('contradicting_evidence'):
        st.warning('Cross-checks: '+' | '.join(market_view['contradicting_evidence']))
    age=mm.get('snapshot_age_hours')
    st.caption('Data policy: central daily snapshots only; this agent makes no direct FRED/provider requests.' + ('' if age is None else f' Snapshot age: {age:.1f}h.'))

portfolio_view=st.session_state.get('_agent_portfolio_result')
if portfolio_view:
    st.subheader('Portfolio & Risk Agent')
    c1,c2,c3=st.columns(3)
    c1.metric('State',portfolio_view.get('state','N/D'))
    weights=(portfolio_view.get('metadata') or {}).get('weights',{}) or {}
    c2.metric('Positions valued',len(weights))
    c3.metric('Verification',portfolio_view.get('verification_status','N/D'))
    st.caption(portfolio_view.get('summary',''))
    if portfolio_view.get('contradicting_evidence'):
        st.warning('Risk flags: '+' | '.join(portfolio_view['contradicting_evidence']))

watchlist=st.session_state.get('_agent_watchlist',[])
if watchlist:
    st.subheader('Desk Watchlist')
    st.dataframe(pd.DataFrame(watchlist)[['Rank','Ticker','Priority Score','Technical','Fundamental','Portfolio Fit','Market Fit','Verified Specialists','Contradictions','Portfolio Note']],use_container_width=True,hide_index=True)
    st.caption('Priority combines verified specialist evidence with portfolio fit and a small market/sector context weight. It is a research ranking, not a buy list.')

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
st.caption('SHADOW MODE: analysis → portfolio context → verification → CIO → human. No execution path exists.')
