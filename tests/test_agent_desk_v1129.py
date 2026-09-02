from datetime import datetime,timezone,timedelta
import pandas as pd

import core.event_state as event_state
import core.desk_notifications as desk_notifications
import core.desk_runner as desk_runner
from core.agent_contracts import AgentResult,Evidence,DataStatus,VerificationStatus
from core.event_detector import detect_snapshot_events,detect_market_context_events
from core.event_state import filter_actionable_events,record_event_state
from core.agent_router import route_events
from core.cio_agent import build_cio_brief
from core.intraday_monitor import select_monitor_tickers,build_intraday_overlay


def test_detector_emits_typed_price_volume_and_state_events():
    latest=pd.DataFrame([{'Ticker':'AAA','Price':108,'Rel_Volume':2.5,'Entry_Score':78,'Action':'WATCH'}])
    previous=pd.DataFrame([{'Ticker':'AAA','Price':100,'Rel_Volume':1.0,'Entry_Score':55,'Action':'AVOID'}])
    events=detect_snapshot_events(latest,previous,['AAA'])
    assert len(events)==1
    assert {'large_price_move','abnormal_volume','technical_state_change','technical_score_change'} <= set(events[0]['event_types'])
    assert events[0]['portfolio'] is True
    assert events[0]['fingerprint'] and events[0]['event_key'].startswith('AAA:')


def test_market_detector_reports_stale_without_provider_call():
    meta={'generated_at':(datetime.now(timezone.utc)-timedelta(hours=72)).isoformat()}
    events=detect_market_context_events({'Risk_Regime':'NEUTRAL','Momentum':'STABLE'},meta)
    assert events[0]['ticker']=='MARKET'
    assert 'snapshot_stale' in events[0]['event_types']


def test_router_wakes_only_relevant_specialists():
    event={'ticker':'AAA','event_types':['abnormal_volume'],'severity':2,'portfolio':False,'metrics':{}}
    plan=route_events([event])
    assert plan['ticker_agents']=={'AAA':['technical']}
    assert plan['global_agents']==[]
    extreme={'ticker':'BBB','event_types':['large_price_move'],'severity':4,'portfolio':True,'metrics':{'price_move_pct':-8}}
    plan=route_events([extreme])
    assert plan['ticker_agents']['BBB']==['fundamental','technical']
    assert plan['global_agents']==['market','portfolio']


def test_event_state_deduplicates_and_applies_cooldown(tmp_path,monkeypatch):
    monkeypatch.setattr(event_state,'STATE_DIR',tmp_path)
    monkeypatch.setattr(event_state,'cloud_available',lambda:False)
    now=datetime.now(timezone.utc)
    event={'ticker':'AAA','event_key':'AAA:large_price_move','fingerprint':'one'}
    actionable,suppressed=filter_actionable_events('u',[event],now=now)
    assert actionable==[event] and suppressed==[]
    record_event_state('u',[event],now=now)
    actionable,suppressed=filter_actionable_events('u',[event],now=now+timedelta(minutes=300))
    assert not actionable and suppressed[0]['reason']=='DUPLICATE'
    changed={**event,'fingerprint':'two'}
    actionable,suppressed=filter_actionable_events('u',[changed],now=now+timedelta(minutes=60))
    assert not actionable and suppressed[0]['reason']=='COOLDOWN'
    actionable,_=filter_actionable_events('u',[changed],now=now+timedelta(minutes=300))
    assert actionable==[changed]


def test_intraday_monitor_is_bounded_and_builds_live_overlay():
    latest=pd.DataFrame([
        {'Ticker':'AAA','Price':100,'Entry_Score':50},
        {'Ticker':'BBB','Price':100,'Entry_Score':90},
        {'Ticker':'CCC','Price':100,'Entry_Score':80},
    ])
    assert select_monitor_tickers(latest,['AAA'],max_symbols=2)==['AAA','BBB']
    idx=pd.date_range('2026-09-01 13:30',periods=4,freq='D',tz='UTC')
    bars=pd.DataFrame({'Close':[100,101,102,108],'Volume':[100,100,100,300]},index=idx)
    overlay,meta=build_intraday_overlay(latest,['AAA'],fetcher=lambda ticks:({'AAA':bars},{'status':'CURRENT','source':'TEST'}))
    assert overlay.iloc[0]['Price']==108
    assert overlay.iloc[0]['Rel_Volume']==3
    assert meta['status']=='CURRENT' and meta['received']==1


def _verified(agent,subject,state,confidence=.8,contradictions=None):
    result=AgentResult(agent,'1','skill','1',subject,state,confidence,'summary',
                       [Evidence('fact',1,'test',status=DataStatus.CURRENT)],contradictions or [])
    result.verification_status=VerificationStatus.VERIFIED
    return result


def test_cio_brief_has_decision_sections_and_materiality():
    portfolio=_verified('Portfolio & Risk','PORTFOLIO','HIGH_RISK',.9,['Concentration'])
    market=_verified('Market Regime & Sector','MARKET','NEUTRAL',.8)
    brief=build_cio_brief([portfolio,market],events=[{'ticker':'AAA','severity':4,'reasons':['Price moved -8%']}])
    expected={'market_regime','principal_risk','top_opportunities','portfolio_items','thesis_changes',
              'avoid_or_conflicting','decisions_needed','material','material_reasons'}
    assert expected <= set(brief)
    assert brief['material'] is True
    assert brief['principal_risk']['state']=='HIGH_RISK'


def test_material_notification_is_not_sent_for_non_material(monkeypatch):
    monkeypatch.setattr(desk_notifications,'get_user_webhook',lambda uid:'https://example.test/hook')
    calls=[]
    out=desk_notifications.notify_material_brief('u',{'material':False},'run',send_fn=lambda *a,**k:calls.append(1))
    assert out['status']=='NOT_MATERIAL' and calls==[]


def test_failed_material_notification_remains_retriable(monkeypatch):
    saved={}
    monkeypatch.setattr(desk_notifications,'get_user_webhook',lambda uid:'https://example.test/hook')
    monkeypatch.setattr(desk_notifications,'load_desk_output',lambda uid,typ,key:saved.get(key))
    monkeypatch.setattr(desk_notifications,'save_desk_output',lambda uid,typ,payload,run_key=None:saved.update({run_key:{'payload':payload}}))
    calls=[]
    send=lambda *a,**k: calls.append(1) and False
    brief={'material':True,'headline':'Review','material_reasons':['Move']}
    assert desk_notifications.notify_material_brief('u',brief,'run',send_fn=send)['status']=='FAILED'
    assert desk_notifications.notify_material_brief('u',brief,'run',send_fn=send)['status']=='FAILED'
    assert len(calls)==2


def test_routed_runner_does_not_wake_unrequested_fundamental(monkeypatch):
    result=_verified('Technical Signal','AAA','WATCH',.7)
    monkeypatch.setattr(desk_runner,'load_positions',lambda user_id=None:pd.DataFrame())
    monkeypatch.setattr(desk_runner,'download_prices',lambda *a,**k:{'AAA':pd.DataFrame({'Close':[1]})})
    monkeypatch.setattr(desk_runner,'analyze_technical',lambda *a,**k:result)
    monkeypatch.setattr(desk_runner,'analyze_fundamental',lambda *a,**k:(_ for _ in ()).throw(AssertionError('must not run')))
    monkeypatch.setattr(desk_runner,'append_agent_audit',lambda *a,**k:None)
    monkeypatch.setattr(desk_runner,'save_desk_output',lambda *a,**k:None)
    plan={'ticker_agents':{'AAA':['technical']},'global_agents':[],'verification':True,'cio':True,'shadow_mode':True}
    out=desk_runner.run_desk_review('u',['AAA'],agent_plan=plan)
    assert out['agents_invoked']==[{'agent':'Technical Signal','subject':'AAA'}]


def test_production_schema_contains_event_state_table():
    text=open('core/production_storage.py',encoding='utf-8').read()
    assert 'CREATE TABLE IF NOT EXISTS user_agent_event_state' in text
    assert 'PRIMARY KEY (user_id,event_key)' in text


def test_private_agent_state_is_gitignored():
    ignore=open('.gitignore',encoding='utf-8').read()
    assert 'data/agent_event_state/' in ignore
    assert 'data/agent_outputs/' in ignore
    assert 'data/alerts.csv' in ignore
