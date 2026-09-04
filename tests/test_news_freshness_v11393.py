from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import core.automation_health as health
import core.desk_store as desk_store
import core.market_data as market_data
import scripts.run_news_catalyst_monitor as news_worker


NY=ZoneInfo('America/New_York')


def _record(stamp,payload=None):
    return {'created_at':stamp.isoformat(),'payload':payload or {}}


def test_news_health_prefers_explicit_success_heartbeat(monkeypatch):
    now=datetime(2026,9,4,12,0,tzinfo=NY)
    records={
        'automation_heartbeat_saved_alerts':_record(now-timedelta(minutes=5)),
        'event_scan':_record(now-timedelta(minutes=5)),
        'automation_heartbeat_portfolio_news':_record(now-timedelta(minutes=10),{'status':'PARTIAL'}),
        'automation_heartbeat_watchlist_news':_record(now-timedelta(minutes=10),{'status':'PARTIAL'}),
        'news_catalyst_priority_scan':_record(now-timedelta(minutes=200)),
        'news_catalyst_scan':_record(now-timedelta(minutes=200)),
        'daily_cio_brief':_record(now.replace(hour=8,minute=0)),
    }
    monkeypatch.setattr(health,'load_latest_desk_output',lambda uid,typ:records.get(typ))
    monkeypatch.setattr(health,'load_positions',lambda user_id:pd.DataFrame([{'ticker':'TMUS'}]))
    monkeypatch.setattr(health,'load_json_snapshot',lambda name:{})
    report=health.build_automation_health('u',now=now)
    assert next(row for row in report['checks'] if row['process']=='portfolio_news')['status']=='CURRENT'
    assert next(row for row in report['checks'] if row['process']=='watchlist_news')['status']=='CURRENT'


def test_full_news_scan_marks_both_heartbeats_fresh_on_partial_provider_result(monkeypatch):
    calls=[]
    monkeypatch.setattr(news_worker,'record_automation_heartbeat',lambda uid,process,**kwargs:
                        (calls.append((process,kwargs['status'])) or {'persistence':{'status':'CURRENT'}}))
    result=news_worker._record_news_heartbeats('u','full','PARTIAL',{'stories':122},
                                               datetime(2026,9,4,12,0,tzinfo=NY))
    assert result['status']=='PARTIAL'
    assert calls==[('portfolio_news','PARTIAL'),('watchlist_news','PARTIAL')]


def test_heartbeat_reports_failed_durable_write(monkeypatch):
    monkeypatch.setattr(news_worker,'record_automation_heartbeat',lambda *args,**kwargs:
                        {'persistence':{'status':'FAILED'}})
    result=news_worker._record_news_heartbeats('u','priority','CURRENT',{},
                                               datetime(2026,9,4,12,0,tzinfo=NY))
    assert result['status']=='FAILED' and result['failures']==1


def test_desk_store_exposes_cloud_persistence_failure(tmp_path,monkeypatch):
    monkeypatch.setattr(desk_store,'DIR',tmp_path)
    monkeypatch.setattr(desk_store,'cloud_available',lambda:True)
    monkeypatch.setattr(desk_store,'ensure_production_schema',lambda:(True,'OK'))
    monkeypatch.setattr(desk_store,'execute_sql',lambda *args,**kwargs:(False,'pool unavailable'))
    record=desk_store.save_desk_output('u','news',{'ok':True},run_key='run')
    assert record['persistence']=={'status':'FAILED','message':'pool unavailable'}


def test_partial_yahoo_batch_retries_missing_ticker_without_threads(monkeypatch):
    history=pd.DataFrame({'Close':[100.0]},index=pd.to_datetime(['2026-09-03']))
    calls=[]
    monkeypatch.setattr(market_data,'_read_price_cache',lambda *args,**kwargs:None)
    monkeypatch.setattr(market_data,'_write_price_cache',lambda *args,**kwargs:None)
    monkeypatch.setattr(market_data,'_extract',lambda data,tickers:{'AAA':history.copy()})

    def download(tickers,**kwargs):
        calls.append((tickers,kwargs.get('threads')))
        return history.copy()

    monkeypatch.setattr(market_data.yf,'download',download)
    market_data.download_prices.clear()
    result=market_data.download_prices(['AAA','TMUS'],period='2y')
    market_data.download_prices.clear()
    assert set(result)=={'AAA','TMUS'}
    assert calls==[(['AAA','TMUS'],True),('TMUS',False)]
