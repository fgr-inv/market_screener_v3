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
from core.shadow_validation import load_shadow_decisions,load_shadow_outcomes,shadow_validation_summary
from core.skill_calibration import build_skill_calibration_review,load_latest_skill_calibration_review
from core.skill_governance import (build_paper_readiness_report,load_skill_governance,
                                   save_skill_governance)
from core.production_storage import storage_mode
from core.news_catalyst_data import merge_news_scan_records

hero('Investment Desk','CIO + Market/Sector + Technical + Fundamental + News/Catalysts + Portfolio/Risk + Verification · shadow mode.','Agent Desk V1')
section_note('Research only. A broad daily hunt discovers candidates, the news agent monitors portfolio + persistent watchlist, and specialists wake only for relevant events. It never sends broker orders.')
user=current_user(); uid=user['user_id']

hunt=load_latest_desk_output(uid,'daily_opportunity_hunt')
if hunt and hunt.get('payload'):
    hp=hunt['payload']; discovery=hp.get('discovery') or {}
    verified=discovery.get('verified_opportunities') or []
    shortlist=discovery.get('candidates') or []
    monitored=discovery.get('monitor_tickers') or []
    st.subheader('Daily Opportunity Hunt')
    st.caption(f"Broad scan → diversified shortlist → Technical + Fundamental + Verification · {hunt.get('created_at','N/D')} · SHADOW MODE")
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Universe screened',discovery.get('universe_rows',0))
    c2.metric('Deep-review shortlist',len(shortlist))
    c3.metric('Verified candidates',len(verified))
    c4.metric('Intraday monitored',len(monitored))
    status=hp.get('status') or discovery.get('status','N/D')
    if verified:
        st.success(f"{len(verified)} candidate(s) passed both specialist and evidence gates. Research ranking only.")
        st.dataframe(pd.DataFrame(verified),width='stretch',hide_index=True)
    elif status=='BLOCKED_STALE_OR_MISSING_SNAPSHOT':
        st.error('The hunt was blocked because the broad market snapshot was missing or stale. No stale opportunity was promoted.')
    else:
        st.info('No candidate passed every verification gate. The strongest preliminary names remain under observation; none is labeled a verified opportunity.')
    if shortlist:
        with st.expander('Diversified discovery shortlist',expanded=False):
            st.dataframe(pd.DataFrame(shortlist),width='stretch',hide_index=True)
    if monitored:
        st.caption('Persistent 15-minute watchlist: '+', '.join(monitored))

news_scan=load_latest_desk_output(uid,'news_catalyst_scan')
priority_news_scan=load_latest_desk_output(uid,'news_catalyst_priority_scan')
merged_news=merge_news_scan_records([priority_news_scan,news_scan])
if news_scan or priority_news_scan:
    stories=merged_news['stories']; actionable_news=merged_news['actionable_events']
    material_news=merged_news['material_events']; provider_rows=merged_news['provider_rows']
    st.subheader('News & Catalyst Intelligence')
    st.caption(
        f"Portfolio 30 min: {(priority_news_scan or {}).get('created_at','N/D')} · "
        f"Portfolio + watchlist 60 min: {(news_scan or {}).get('created_at','N/D')} · SHADOW MODE"
    )
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Tickers monitored',len(merged_news['monitored_tickers']))
    c2.metric('Fresh stories',len(stories))
    c3.metric('Material events',len(material_news))
    c4.metric('SEC filings',sum(row.get('source_type')=='SEC_FILING' for row in stories))
    if actionable_news:
        if material_news: st.warning('New material catalysts require review; source and thesis impact are shown below.')
        else: st.info('A lower-severity portfolio catalyst was reviewed; it did not meet the material-alert threshold.')
        rows=[]
        for event in actionable_news:
            story=((event.get('metrics') or {}).get('story') or {})
            rows.append({'Ticker':event.get('ticker'),'Published':story.get('published_at'),'Category':story.get('category'),
                         'Direction':story.get('direction'),'Severity':story.get('severity'),'Thesis Impact':story.get('thesis_impact'),
                         'Primary Source':story.get('primary_source'),'Title':story.get('title'),'Publisher':story.get('publisher'),'URL':story.get('url')})
        st.dataframe(pd.DataFrame(rows),width='stretch',hide_index=True)
    else:
        st.info('No new material catalyst was found in the latest automated scan.')
    with st.expander('Provider health',expanded=False):
        st.dataframe(pd.DataFrame(provider_rows),width='stretch',hide_index=True)

auto=load_latest_desk_output(uid,'daily_cio_brief') or load_latest_desk_output(uid,'scheduled_review')
if auto and auto.get('payload'):
    ap=auto['payload']; ab=ap.get('brief') or {}
    st.subheader('Latest automated CIO Brief')
    st.info(ab.get('headline','Automated desk output available'))
    st.caption(f"Background worker · {auto.get('created_at','N/D')} · SHADOW MODE")
    c1,c2,c3=st.columns(3)
    market_section=ab.get('market_regime') or {}
    risk_section=ab.get('principal_risk') or {}
    c1.metric('Market regime',market_section.get('state','NOT CHECKED'))
    c2.metric('Principal risk',risk_section.get('state','NOT CHECKED'))
    c3.metric('Material','YES' if ab.get('material') else 'NO')
    if market_section.get('summary'): st.caption('Market: '+market_section['summary'])
    if risk_section.get('summary'): st.caption('Risk: '+risk_section['summary'])
    if ab.get('material_reasons'):
        st.warning('Material review: '+' | '.join(ab['material_reasons']))
    top=ab.get('top_opportunities') or []
    if top:
        st.write('**Top opportunities**')
        st.dataframe(pd.DataFrame(top),width='stretch',hide_index=True)
    decisions=ab.get('decisions_needed') or []
    if decisions:
        with st.expander('Decisions needed',expanded=False):
            st.dataframe(pd.DataFrame(decisions),width='stretch',hide_index=True)
    conflicts=ab.get('avoid_or_conflicting') or []
    if conflicts:
        with st.expander('Avoid / conflicting signals',expanded=False):
            st.dataframe(pd.DataFrame(conflicts),width='stretch',hide_index=True)
    aw=ap.get('watchlist') or []
    if aw:
        with st.expander('Automated desk watchlist',expanded=False):
            st.dataframe(pd.DataFrame(aw),width='stretch',hide_index=True)
    news_items=ab.get('news_and_catalysts') or []
    if news_items:
        with st.expander('News and catalyst conclusions',expanded=True):
            st.dataframe(pd.DataFrame(news_items),width='stretch',hide_index=True)

shadow_decisions=load_shadow_decisions(uid)
shadow_outcomes=load_shadow_outcomes(uid)
shadow_summary=shadow_validation_summary(shadow_decisions,shadow_outcomes)
st.subheader('Shadow Forward Validation')
c1,c2,c3,c4=st.columns(4)
c1.metric('Decisions recorded',shadow_summary['decisions'])
c2.metric('Matured outcomes',shadow_summary['matured_outcomes'])
c3.metric('Pending outcomes',shadow_summary['pending_outcomes'])
c4.metric('Evidence status',shadow_summary['status'])
if shadow_summary['status'] in {'NO_DECISIONS','NOT_ENOUGH_DATA'}:
    st.info(f"Forward evidence: {shadow_summary['status']}. No performance conclusion until at least {shadow_summary['minimum_reliable_sample']} matured observations per horizon.")
if shadow_summary.get('unevaluated_outcomes'):
    st.caption(f"Pending includes {shadow_summary['unevaluated_outcomes']} decision/horizon observations that the daily validation worker has not evaluated yet.")
horizon_rows=pd.DataFrame(shadow_summary['horizons'])
if not horizon_rows.empty:
    st.dataframe(horizon_rows,width='stretch',hide_index=True)
if shadow_decisions:
    recent=pd.DataFrame(shadow_decisions).sort_values('decision_at',ascending=False).head(20)
    columns=[c for c in ['decision_at','ticker','source_agent','signal_state','expected_direction','confidence','verification_status','baseline_price','baseline_status'] if c in recent]
    with st.expander('Recent recorded decisions',expanded=False):
        st.dataframe(recent[columns],width='stretch',hide_index=True)
st.caption('Forward validation is observational: 1/5/20 trading-day outcomes versus SPY. It never creates a paper or live position.')

calibration=build_skill_calibration_review(shadow_decisions,shadow_outcomes)
stored_calibration=load_latest_skill_calibration_review(uid)
governance_records=load_skill_governance(uid)
governance_by_key={str(row.get('proposal_key')):row for row in governance_records if row.get('proposal_key')}
st.subheader('Shadow Skill Calibration')
counts=calibration['recommendation_counts']
c1,c2,c3,c4=st.columns(4)
c1.metric('Eligible segments',calibration['eligible_segments'])
c2.metric('Retain',counts['RETAIN'])
c3.metric('Review',counts['REVIEW'])
c4.metric('Pause candidates',counts['PAUSE_CANDIDATE'])
if calibration['status'] in {'NO_DECISIONS','NOT_ENOUGH_DATA'}:
    policy=calibration['policy']
    st.info(f"Calibration: {calibration['status']}. Each agent/state/version needs at least "
            f"{policy['minimum_sample']} matured outcomes across {policy['minimum_unique_tickers']} tickers at its primary horizon.")
elif calibration['status']=='REVIEW_REQUIRED':
    st.warning('One or more skill segments need human review. No signal, threshold, skill file, or trading behavior was changed automatically.')
primary_rows=[row for row in calibration['segments'] if row['Governance Horizon']=='PRIMARY']
if primary_rows:
    columns=['Agent','Signal State','Skill Version','Version Role','Horizon','Recommendation','Sample','Unique Tickers',
             'Hit Rate %','Hit Rate 95% Low %','Hit Rate 95% High %','Mean Directional Alpha %','Brier Score','Reason']
    st.dataframe(pd.DataFrame(primary_rows)[columns],width='stretch',hide_index=True)
if calibration['version_comparisons']:
    with st.expander('Skill version comparisons',expanded=False):
        st.dataframe(pd.DataFrame(calibration['version_comparisons']),width='stretch',hide_index=True)
if calibration['proposals']:
    with st.expander('Human review queue',expanded=True):
        st.caption('ACKNOWLEDGE_AND_RETAIN records an explicit risk acceptance. REQUEST_REVISION keeps readiness blocked until a new skill version is validated.')
        for proposal in calibration['proposals']:
            key=str(proposal['proposal_key']); previous=governance_by_key.get(key,{})
            st.write(f"**{proposal['agent']} · {proposal['signal_state']} · skill {proposal['skill_version']} · {proposal['recommendation']}**")
            st.caption(proposal['reason'])
            options=['DEFER','ACKNOWLEDGE_AND_RETAIN','REQUEST_REVISION']
            selected=str(previous.get('resolution') or 'DEFER')
            resolution=st.selectbox('Governance decision',options,index=options.index(selected) if selected in options else 0,key=f'gov_resolution_{key}')
            note=st.text_input('Review note',value=str(previous.get('note') or ''),key=f'gov_note_{key}')
            if st.button('Save governance decision',key=f'gov_save_{key}'):
                saved=save_skill_governance(uid,proposal,resolution,note)
                append_agent_audit(uid,'skill_governance_decision',{'proposal_key':key,'resolution':resolution,
                                   'status':saved['status'],'shadow_mode':True,'automatic_change_applied':False})
                if saved['status']=='CURRENT':
                    st.success('Governance decision saved. No automatic skill change was applied.')
                    st.rerun()
                else:
                    st.error('The governance decision could not be persisted. It remains retriable.')
            st.divider()
if governance_records:
    with st.expander('Governance history',expanded=False):
        columns=['updated_at','agent','signal_state','skill_version','recommendation','resolution','note','automatic_change_applied']
        history=pd.DataFrame(governance_records).sort_values('updated_at',ascending=False)
        st.dataframe(history[[c for c in columns if c in history]],width='stretch',hide_index=True)
if stored_calibration:
    st.caption(f"Latest persisted weekly review: {stored_calibration.get('created_at','N/D')}.")
st.caption('Governance only: Technical/News use 5d; Fundamental/CIO use 20d. Secondary horizons remain context. Correlated signals can reduce effective sample size. Reviews never rewrite skills or place trades.')

paper_readiness=build_paper_readiness_report(shadow_decisions,shadow_outcomes,calibration,governance_records,storage_mode())
st.subheader('Paper Readiness Gate')
c1,c2,c3=st.columns(3)
c1.metric('Readiness',paper_readiness['status'])
c2.metric('Gates passed',f"{paper_readiness['passed_gates']}/{paper_readiness['total_gates']}")
c3.metric('Paper Mode','DISABLED')
if paper_readiness['status']=='READY_FOR_PAPER_REVIEW':
    st.success('Evidence gates permit a human architecture review. Paper Mode is still disabled and requires a separate approved release.')
elif paper_readiness['status']=='BLOCKED_REVIEW':
    st.warning('Evidence quantity is sufficient, but calibration/governance issues still block Paper Mode review.')
else:
    st.info('The desk is still building forward evidence. This is the expected state until every readiness gate passes.')
st.dataframe(pd.DataFrame(paper_readiness['gates']),width='stretch',hide_index=True)
st.caption(paper_readiness['approval_boundary'])

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
        brief=build_cio_brief(verified,watchlist=watchlist)
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
    st.dataframe(pd.DataFrame(watchlist)[['Rank','Ticker','Priority Score','Technical','Fundamental','Portfolio Fit','Market Fit','Verified Specialists','Contradictions','Portfolio Note']],width='stretch',hide_index=True)
    st.caption('Priority combines verified specialist evidence with portfolio fit and a small market/sector context weight. It is a research ranking, not a buy list.')

brief=st.session_state.get('_agent_desk_brief')
if brief:
    st.subheader('CIO Brief'); st.info(brief['headline'])
    budget_rows=st.session_state.get('_agent_budget_rows',[])
    if budget_rows:
        with st.expander('Fundamental data budget',expanded=False):
            st.dataframe(pd.DataFrame(budget_rows),width='stretch',hide_index=True)
            st.caption('CACHE = zero full fundamental provider refresh for that ticker. REFRESH = the shared snapshot was absent/stale or you forced it.')
    for d in brief['decisions']:
        with st.expander(f"{d['subject']} · {d['agent']} · {d['state']} · confidence {d['confidence']:.0%}",expanded=True):
            st.write(d['summary']); st.caption(f"Verification: {d['verification_status']}")
            ev=pd.DataFrame(d.get('evidence',[]))
            if not ev.empty: st.dataframe(ev[['claim','value','source','observed_at','status','note']],width='stretch',hide_index=True)
            if d.get('contradicting_evidence'): st.warning('Contradicting evidence: '+' | '.join(d['contradicting_evidence']))
            st.caption('Alternative explanation: '+(d.get('alternative_explanation') or 'N/D'))
    if brief['blocked_or_low_trust']:
        st.subheader('Blocked / low-trust')
        st.dataframe(pd.DataFrame([{'Ticker':x.get('subject'),'Agent':x.get('agent'),'State':x.get('state'),'Verification':x.get('verification_status'),'Confidence':x.get('confidence')} for x in brief['blocked_or_low_trust']]),width='stretch',hide_index=True)

st.subheader('Audit trail')
audit=load_agent_audit(uid,100)
if audit.empty: st.caption('No agent runs logged yet.')
else: st.dataframe(audit[['ts','event_type']],width='stretch',hide_index=True)
st.caption('SHADOW MODE: analysis → portfolio context → verification → CIO → human. No execution path exists.')
