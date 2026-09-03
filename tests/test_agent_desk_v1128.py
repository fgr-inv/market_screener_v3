import pandas as pd
from core.event_detector import detect_snapshot_events
from core.cio_agent import build_cio_brief

def test_event_detector_is_snapshot_only_and_prioritizes_holdings():
    latest=pd.DataFrame([
        {'Ticker':'AAA','Entry_Score':80,'Opportunity_Score':77,'Action':'WATCH'},
        {'Ticker':'BBB','Entry_Score':55,'Opportunity_Score':50,'Action':'WATCH'},
    ])
    previous=pd.DataFrame([
        {'Ticker':'AAA','Entry_Score':60,'Opportunity_Score':60,'Action':'HOLD'},
        {'Ticker':'BBB','Entry_Score':55,'Opportunity_Score':50,'Action':'WATCH'},
    ])
    events=detect_snapshot_events(latest,previous,['AAA'])
    assert events and events[0]['ticker']=='AAA'
    assert events[0]['portfolio'] is True
    assert any('moved' in x for x in events[0]['reasons'])

def test_event_detector_no_signal_is_valid():
    latest=pd.DataFrame([{'Ticker':'AAA','Entry_Score':50,'Opportunity_Score':50,'Action':'WATCH'}])
    assert detect_snapshot_events(latest,latest,[])==[]

def test_background_workflow_exists_and_is_shadow_only():
    text=open('.github/workflows/investment_desk.yml',encoding='utf-8').read()
    assert '*/15 13-21' in text
    assert 'run_investment_desk' in text
    daily=open('.github/workflows/daily_cio_brief.yml',encoding='utf-8').read()
    assert 'run_daily_cio_brief' in daily
    assert 'alpaca' not in text.lower()
