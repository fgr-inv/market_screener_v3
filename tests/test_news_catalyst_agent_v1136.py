from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import core.news_catalyst_data as news_data
from core.agent_router import route_events
from core.news_catalyst_agent import (analyze_news_catalyst, catalyst_story_event,
                                        classify_catalyst_story)
from core.news_catalyst_data import fetch_fmp_stories, fetch_sec_filings, normalize_story
from core.verification_agent import verify_result
from scripts.run_daily_cio_brief import _recent_news_context
from scripts.run_news_catalyst_monitor import news_run_key, should_fetch_sec, story_lookback_hours


NOW=datetime(2026,9,3,14,0,tzinfo=timezone.utc)


def _story(**overrides):
    base={'ticker':'AMD','title':'AMD raises guidance after earnings beat','summary':'Revenue beat estimates.',
          'publisher':'AMD','published_at':'2026-09-03T13:00:00+00:00','url':'https://example.test/amd',
          'provider':'FMP','source_type':'PRESS_RELEASE','primary_source':True,'story_id':'story-1'}
    base.update(overrides); return base


def test_classifier_identifies_material_guidance_and_thesis_match():
    classified=classify_catalyst_story(_story(),portfolio=True,
        thesis={'catalysts':'Revenue growth and raised guidance','invalidation':'Margin collapse'})
    assert classified['category']=='GUIDANCE'
    assert classified['direction']=='POSITIVE'
    assert classified['severity']==5 and classified['material'] is True
    assert classified['thesis_impact']=='CATALYST_MATCH'


def test_negative_capital_raise_is_not_presented_as_positive():
    classified=classify_catalyst_story(_story(title='Company announces public stock offering',summary='',primary_source=False),portfolio=False)
    assert classified['category']=='CAPITAL_STRUCTURE'
    assert classified['direction']=='NEGATIVE'
    assert classified['severity']==4


def test_sec_form_materiality_uses_form_and_items():
    classified=classify_catalyst_story(_story(source_type='SEC_FILING',form='8-K',items='2.02, 9.01',title='8-K filing — AMD'))
    assert classified['category']=='EARNINGS' and classified['severity']==4


def test_news_event_has_story_identity_and_routes_news_plus_fundamental():
    event=catalyst_story_event(classify_catalyst_story(_story()))
    plan=route_events([event])
    assert plan['ticker_agents']['AMD']==['fundamental','news']
    assert event['event_key']=='NEWS:AMD:story-1'
    assert event['fingerprint']=='story-1'


def test_media_only_material_story_is_only_partially_verified():
    story=_story(source_type='NEWS',provider='FMP',publisher='News outlet',primary_source=False)
    result=verify_result(analyze_news_catalyst('AMD',[story]))
    assert result.state=='MATERIAL_POSITIVE'
    assert result.verification_status.value=='PARTIALLY_VERIFIED'
    assert result.metadata['primary_source_observed'] is False


def test_primary_story_is_verified_and_preserves_url_and_date():
    result=verify_result(analyze_news_catalyst('AMD',[_story()]))
    assert result.verification_status.value=='VERIFIED'
    assert result.metadata['articles'][0]['url']=='https://example.test/amd'
    assert result.metadata['articles'][0]['published_at'].startswith('2026-09-03')


def test_fmp_batch_parses_news_and_press_release(monkeypatch):
    monkeypatch.setenv('FMP_API_KEY','test-key')
    calls=[]
    def fake(url,params=None,headers=None):
        calls.append((url,params))
        if url.endswith('/news/stock'):
            return [{'symbol':'AMD','title':'AMD earnings beat','text':'Results','site':'Outlet',
                     'publishedDate':'2026-09-03 13:00:00','url':'https://example.test/news'}]
        if url.endswith('/news/press-releases'):
            return [{'symbol':'AMD','title':'AMD announces results','text':'Release','site':'AMD',
                     'publishedDate':'2026-09-03 13:05:00','url':'https://example.test/release'}]
        return []
    stories,status=fetch_fmp_stories(['AMD'],get_json=fake)
    assert len(stories)==2 and status['status']=='CURRENT'
    assert any(row['source_type']=='PRESS_RELEASE' and row['primary_source'] for row in stories)
    assert len(calls)==2 and all(call[1]['symbols']=='AMD' for call in calls)


def test_sec_submissions_parser_uses_official_document_url():
    def fake(url,params=None,headers=None):
        if url==news_data.SEC_TICKERS_URL: return {'0':{'ticker':'AMD','cik_str':2488}}
        return {'name':'ADVANCED MICRO DEVICES INC','filings':{'recent':{
            'form':['8-K'],'filingDate':['2026-09-03'],'acceptanceDateTime':['2026-09-03T12:30:00.000Z'],
            'accessionNumber':['0000002488-26-000001'],'primaryDocument':['amd-20260903.htm'],
            'primaryDocDescription':['Current report'],'items':['2.02,9.01']}}}
    stories,status=fetch_sec_filings(['AMD'],get_json=fake,pause_seconds=0,now=NOW)
    assert status['status']=='CURRENT' and len(stories)==1
    assert stories[0]['form']=='8-K' and stories[0]['primary_source'] is True
    assert stories[0]['url'].startswith('https://www.sec.gov/Archives/edgar/data/2488/')


def test_normalizer_rejects_story_without_title():
    assert normalize_story({'symbol':'AMD','publishedDate':'2026-09-03'}) is None


def test_news_schedule_and_run_key_are_deterministic():
    local=pd.Timestamp('2026-09-03 07:05',tz='America/New_York').to_pydatetime()
    assert should_fetch_sec(local) is True
    assert news_run_key(local)=='news-2026-09-03-07'


def test_monday_first_scan_bridges_weekend():
    monday=pd.Timestamp('2026-09-07 07:05',tz='America/New_York').to_pydatetime()
    assert story_lookback_hours(monday)==84
    assert story_lookback_hours(monday.replace(hour=9))==36


def test_syndicated_duplicate_prefers_primary_press_release():
    media=_story(story_id='media',source_type='NEWS',primary_source=False,publisher='Outlet',
                 url='https://example.test/media')
    release=_story(story_id='release',source_type='PRESS_RELEASE',primary_source=True,publisher='AMD',
                   url='https://example.test/release')
    rows=news_data._deduplicate([media,release])
    assert len(rows)==1 and rows[0]['story_id']=='release'


def test_news_agent_uses_five_day_governance_horizon():
    from core.skill_calibration import PRIMARY_HORIZON_BY_AGENT
    assert PRIMARY_HORIZON_BY_AGENT['News & Catalyst']==5


def test_ui_counts_only_material_news_events():
    desk=Path('views/investment_desk.py').read_text(encoding='utf-8')
    alerts=Path('views/alerts.py').read_text(encoding='utf-8')
    worker=Path('scripts/run_news_catalyst_monitor.py').read_text(encoding='utf-8')
    assert "'material_events':material_events" in worker
    assert "len(material_news)" in desk and "len(material_news)" in alerts


def test_premarket_brief_reuses_recent_material_stories(monkeypatch):
    record={'created_at':'2026-09-03T13:30:00+00:00','payload':{'stories':[{**_story(),'material':True,'category':'GUIDANCE','severity':4,'direction':'POSITIVE','thesis_impact':'POTENTIAL_THESIS_SUPPORT'}]}}
    monkeypatch.setattr('scripts.run_daily_cio_brief.load_latest_desk_output',lambda *args:record)
    events,grouped=_recent_news_context('u',pd.Timestamp('2026-09-03T14:00:00+00:00'))
    assert len(events)==1 and list(grouped)==['AMD']


def test_v1136_workflow_ui_and_shadow_boundary():
    workflow=Path('.github/workflows/news_catalyst_monitor.yml').read_text(encoding='utf-8')
    worker=Path('scripts/run_news_catalyst_monitor.py').read_text(encoding='utf-8')
    desk=Path('views/investment_desk.py').read_text(encoding='utf-8')
    config=Path('core/config.py').read_text(encoding='utf-8')
    assert "cron: '5 11-23 * * 1-5'" in workflow
    assert 'FMP_API_KEY' in workflow and 'SEC_USER_AGENT' in workflow
    assert 'News & Catalyst Intelligence' in desk
    assert 'APP_VERSION = "11.36"' in config
    assert all(term not in worker.lower() for term in ('tradingclient','place_order','submit_order','alpaca'))
    assert 'use_container_width' not in '\n'.join(path.read_text(encoding='utf-8') for path in Path('views').glob('*.py'))
