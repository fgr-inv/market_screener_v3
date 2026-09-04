from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import core.automation_health as automation_health
from core.news_catalyst_data import merge_news_scan_records
from scripts.run_news_catalyst_monitor import news_run_key, news_scan_mode, select_news_tickers


NY=ZoneInfo('America/New_York')


def _record(stamp,payload=None):
    return {'created_at':stamp.isoformat(),'payload':payload or {}}


def _health_loader(now,stale_intraday=False):
    records={
        'automation_heartbeat_saved_alerts':_record(now-timedelta(minutes=10),{'observed_at':(now-timedelta(minutes=10)).isoformat()}),
        'event_scan':_record(now-timedelta(minutes=90 if stale_intraday else 15)),
        'news_catalyst_priority_scan':_record(now-timedelta(minutes=25)),
        'news_catalyst_scan':_record(now-timedelta(minutes=50)),
        'daily_cio_brief':_record(now.replace(hour=7,minute=30)),
    }
    return lambda uid,output_type:records.get(output_type)


def test_priority_news_keys_and_universe_are_separate(monkeypatch):
    now=datetime(2026,9,3,10,35,tzinfo=NY)
    assert news_run_key(now)=='news-2026-09-03-10'
    assert news_run_key(now,'priority')=='news-priority-2026-09-03-10-30'
    assert select_news_tickers(['AMD','META'],['META','MSFT'],'priority')==['AMD','META']
    assert select_news_tickers(['AMD','META'],['META','MSFT'],'full')==['AMD','META','MSFT']
    monkeypatch.setenv('NEWS_SCAN_MODE','priority')
    assert news_scan_mode()=='priority'


def test_full_and_priority_news_merge_without_duplicate_events():
    story={'story_id':'s1','ticker':'AMD','published_at':'2026-09-03T14:00:00+00:00','material':True}
    event={'fingerprint':'s1','ticker':'AMD','severity':5,'metrics':{'story':story}}
    priority={'created_at':'2026-09-03T14:35:00+00:00','payload':{
        'scan_mode':'priority','monitored_tickers':['AMD'],'stories':[story],
        'actionable_events':[event],'provider_status':{'providers':[{'provider':'FMP'}]}}}
    full={'created_at':'2026-09-03T14:05:00+00:00','payload':{
        'scan_mode':'full','monitored_tickers':['AMD','MSFT'],'stories':[story],
        'actionable_events':[event],'provider_status':{'providers':[{'provider':'FMP'}]}}}
    merged=merge_news_scan_records([priority,full])
    assert len(merged['stories'])==1 and len(merged['actionable_events'])==1
    assert merged['monitored_tickers']==['AMD','MSFT']
    assert len(merged['material_events'])==1
    assert {row['scan_mode'] for row in merged['provider_rows']}=={'priority','full'}


def test_health_is_current_when_due_processes_are_fresh(monkeypatch):
    now=datetime(2026,9,3,15,0,tzinfo=NY)
    monkeypatch.setattr(automation_health,'load_latest_desk_output',_health_loader(now))
    monkeypatch.setattr(automation_health,'load_positions',lambda user_id:pd.DataFrame([{'ticker':'AMD'}]))
    monkeypatch.setattr(automation_health,'load_json_snapshot',lambda name:{'generated_at':'2026-09-02T22:20:00+00:00'})
    report=automation_health.build_automation_health('u',now=now)
    assert report['status']=='HEALTHY' and report['issues']==[]
    assert next(row for row in report['checks'] if row['process']=='intraday_desk')['status']=='CURRENT'
    assert next(row for row in report['checks'] if row['process']=='daily_snapshot')['status']=='NOT_DUE'


def test_health_flags_only_stale_due_process(monkeypatch):
    now=datetime(2026,9,3,15,0,tzinfo=NY)
    monkeypatch.setattr(automation_health,'load_latest_desk_output',_health_loader(now,stale_intraday=True))
    monkeypatch.setattr(automation_health,'load_positions',lambda user_id:pd.DataFrame([{'ticker':'AMD'}]))
    monkeypatch.setattr(automation_health,'load_json_snapshot',lambda name:{})
    report=automation_health.build_automation_health('u',now=now)
    assert report['status']=='DEGRADED'
    assert [(row['process'],row['status']) for row in report['issues']]==[('intraday_desk','STALE')]


def test_priority_news_is_not_due_without_portfolio(monkeypatch):
    now=datetime(2026,9,3,15,0,tzinfo=NY)
    monkeypatch.setattr(automation_health,'load_latest_desk_output',_health_loader(now))
    monkeypatch.setattr(automation_health,'load_positions',lambda user_id:pd.DataFrame())
    monkeypatch.setattr(automation_health,'load_json_snapshot',lambda name:{})
    report=automation_health.build_automation_health('u',now=now)
    priority=next(row for row in report['checks'] if row['process']=='portfolio_news')
    assert priority['status']=='NOT_DUE'


def test_recent_full_news_bootstraps_priority_health(monkeypatch):
    now=datetime(2026,9,3,15,0,tzinfo=NY)
    loader=_health_loader(now)
    def without_priority(uid,output_type):
        if output_type=='news_catalyst_priority_scan': return None
        if output_type=='news_catalyst_scan': return _record(now-timedelta(minutes=30))
        return loader(uid,output_type)
    monkeypatch.setattr(automation_health,'load_latest_desk_output',without_priority)
    monkeypatch.setattr(automation_health,'load_positions',lambda user_id:pd.DataFrame([{'ticker':'AMD'}]))
    monkeypatch.setattr(automation_health,'load_json_snapshot',lambda name:{})
    report=automation_health.build_automation_health('u',now=now)
    priority=next(row for row in report['checks'] if row['process']=='portfolio_news')
    assert priority['status']=='CURRENT' and priority['max_age_minutes']==45


def test_watchdog_notifies_once_then_reports_recovery(monkeypatch):
    stored={}; sent=[]
    def load(uid,output_type,run_key):
        return {'payload':dict(stored)} if stored else None
    def save(uid,output_type,payload,run_key=None):
        stored.clear(); stored.update(payload); return {'payload':payload}
    def send(message,**kwargs):
        sent.append({'message':message,**kwargs}); return True
    monkeypatch.setattr(automation_health,'load_desk_output',load)
    monkeypatch.setattr(automation_health,'save_desk_output',save)
    monkeypatch.setattr(automation_health,'get_user_webhook',lambda uid:'https://discord.com/api/webhooks/id/token')
    degraded={'status':'DEGRADED','signature':'same','generated_at':'2026-09-03T14:00:00+00:00',
              'issues':[{'process':'intraday_desk','label':'Cartera','status':'STALE','age_minutes':90}],
              'issue_count':1,'checks':[],'shadow_mode':True}
    first=automation_health.notify_automation_health('u',degraded,datetime(2026,9,3,10,0,tzinfo=NY),send_fn=send)
    repeat=automation_health.notify_automation_health('u',degraded,datetime(2026,9,3,10,30,tzinfo=NY),send_fn=send)
    healthy={'status':'HEALTHY','signature':'healthy','generated_at':'2026-09-03T15:00:00+00:00',
             'issues':[],'issue_count':0,'checks':[],'shadow_mode':True}
    recovery=automation_health.notify_automation_health('u',healthy,datetime(2026,9,3,11,0,tzinfo=NY),send_fn=send)
    assert first['status']=='DELIVERED' and repeat['status']=='NOT_NEEDED'
    assert recovery['status']=='DELIVERED' and recovery['recovered'] is True
    assert len(sent)==2 and 'atrasada' in sent[0]['discord_embed']['title'].lower()
    assert 'recuperada' in sent[1]['discord_embed']['title'].lower()


def test_v11362_workflow_and_ui_contract():
    alerts=Path('.github/workflows/alerts.yml').read_text(encoding='utf-8')
    intraday=Path('.github/workflows/investment_desk.yml').read_text(encoding='utf-8')
    news=Path('.github/workflows/news_catalyst_monitor.yml').read_text(encoding='utf-8')
    config=Path('core/config.py').read_text(encoding='utf-8')
    view=Path('views/alerts.py').read_text(encoding='utf-8')
    assert "cron: '*/15 13-21 * * 1-5'" in alerts and "cron: '0 * * * 0,6'" in alerts
    assert 'if: always()' in alerts and 'run_automation_watchdog' in alerts
    assert "cron: '8,23,38,53 13-21 * * 1-5'" in intraday
    assert "cron: '35 11-23 * * 1-5'" in news and 'NEWS_SCAN_MODE' in news
    version=next(line.split('=',1)[1].strip().strip('"') for line in config.splitlines() if line.startswith('APP_VERSION'))
    assert tuple(int(part) for part in version.split('.')) >= (11,36,2)
    assert 'Automation health' in view and 'Portfolio news (30 min)' in view
    new_code='\n'.join(Path(path).read_text(encoding='utf-8') for path in (
        'core/automation_health.py','scripts/run_automation_watchdog.py'))
    assert all(term not in new_code.lower() for term in ('tradingclient','place_order','submit_order','alpaca'))
