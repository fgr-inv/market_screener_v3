from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import core.skill_calibration as calibration
from core.skill_calibration import (build_skill_calibration_review, load_skill_calibration_review,
                                    save_skill_calibration_review)


def _ledger(sample=20, successes=12, alpha=.5, version='1.0', agent='Technical Signal',
            state='SETUP', horizon=5, ticker_count=6, date_prefix='2026-01'):
    decisions=[]; outcomes=[]
    for i in range(sample):
        key=f'{agent}-{state}-{version}-{horizon}-{i}'
        decisions.append({'user_id':'u','decision_key':key,'decision_at':f'{date_prefix}-{(i%20)+1:02d}T15:00:00+00:00',
                          'ticker':f'T{i%ticker_count}','source_agent':agent,'signal_state':state,
                          'skill_version':version,'confidence':.6})
        success=i<successes
        outcomes.append({'user_id':'u','decision_key':key,'horizon_days':horizon,'status':'MATURED',
                         'evaluated_at':'2026-06-01T20:00:00+00:00','success':success,
                         'signed_return_pct':1 if success else -1,'signed_alpha_pct':alpha})
    return decisions,outcomes


def test_calibration_refuses_conclusion_before_minimum_sample():
    decisions,outcomes=_ledger(sample=19,successes=15)
    review=build_skill_calibration_review(decisions,outcomes)
    row=review['segments'][0]
    assert review['status']=='NOT_ENOUGH_DATA'
    assert row['Recommendation']=='INSUFFICIENT_EVIDENCE'
    assert row['Sample']==19


def test_calibration_requires_ticker_diversity():
    decisions,outcomes=_ledger(sample=20,successes=15,ticker_count=1)
    row=build_skill_calibration_review(decisions,outcomes)['segments'][0]
    assert row['Recommendation']=='INSUFFICIENT_EVIDENCE'
    assert 'unique tickers' in row['Reason']


def test_positive_primary_segment_is_retained():
    decisions,outcomes=_ledger(sample=20,successes=12,alpha=.5)
    review=build_skill_calibration_review(decisions,outcomes)
    row=review['segments'][0]
    assert review['status']=='CURRENT'
    assert row['Recommendation']=='RETAIN'
    assert row['Hit Rate %']==60
    assert row['Mean Directional Alpha %']==.5
    assert row['Brier Score']==.24


def test_weak_segment_enters_human_review_without_automatic_change():
    decisions,outcomes=_ledger(sample=20,successes=9,alpha=-.2)
    review=build_skill_calibration_review(decisions,outcomes)
    assert review['status']=='REVIEW_REQUIRED'
    assert review['segments'][0]['Recommendation']=='REVIEW'
    assert review['proposals'][0]['approval_status']=='PENDING_HUMAN_REVIEW'
    assert review['proposals'][0]['automatic_change_applied'] is False


def test_pause_candidate_requires_stronger_sample_and_bad_interval():
    decisions,outcomes=_ledger(sample=40,successes=8,alpha=-1,ticker_count=8)
    row=build_skill_calibration_review(decisions,outcomes)['segments'][0]
    assert row['Recommendation']=='PAUSE_CANDIDATE'
    assert row['Hit Rate 95% High %']<50


def test_versions_are_scored_separately():
    d1,o1=_ledger(sample=20,successes=8,alpha=-.5,version='1.0',date_prefix='2026-01')
    d2,o2=_ledger(sample=20,successes=14,alpha=.7,version='1.1',date_prefix='2026-02')
    review=build_skill_calibration_review(d1+d2,o1+o2)
    rows={row['Skill Version']:row for row in review['segments']}
    assert rows['1.0']['Recommendation']=='REVIEW'
    assert rows['1.1']['Recommendation']=='RETAIN'
    assert len(review['version_comparisons'])==1
    assert review['version_comparisons'][0]['Preferred']=='LATEST'


def test_fundamental_agent_uses_20_day_primary_horizon():
    d5,o5=_ledger(agent='Fundamental & Catalyst',horizon=5,version='2.0')
    d20,o20=_ledger(agent='Fundamental & Catalyst',horizon=20,version='2.0')
    review=build_skill_calibration_review(d5+d20,o5+o20)
    rows={row['Horizon']:row for row in review['segments']}
    assert rows['5d']['Recommendation']=='CONTEXT_ONLY'
    assert rows['20d']['Governance Horizon']=='PRIMARY'
    assert rows['20d']['Recommendation']=='RETAIN'


def test_missing_spy_alpha_blocks_governance_conclusion():
    decisions,outcomes=_ledger()
    for row in outcomes: row['signed_alpha_pct']=None
    row=build_skill_calibration_review(decisions,outcomes)['segments'][0]
    assert row['Recommendation']=='INSUFFICIENT_EVIDENCE'
    assert 'SPY-relative' in row['Reason']


def test_retry_outcomes_are_deduplicated_by_latest_evaluation():
    decisions,outcomes=_ledger(sample=20,successes=12)
    duplicate={**outcomes[0],'evaluated_at':'2026-06-02T20:00:00+00:00','success':False,'signed_alpha_pct':-.5}
    review=build_skill_calibration_review(decisions,outcomes+[duplicate])
    assert review['segments'][0]['Sample']==20
    assert review['segments'][0]['Hit Rate %']==55


def test_local_reviews_are_user_scoped_and_idempotent(tmp_path,monkeypatch):
    monkeypatch.setattr(calibration,'DATA_DIR',tmp_path)
    monkeypatch.setattr(calibration,'cloud_available',lambda:False)
    payload={'status':'NOT_ENOUGH_DATA','manual_review_required':False}
    first=save_skill_calibration_review('user-a','2026-W35',payload)
    second=save_skill_calibration_review('user-a','2026-W35',payload)
    assert first['status']=='CURRENT' and second['status']=='CURRENT'
    assert load_skill_calibration_review('user-a','2026-W35')['payload']==payload
    assert load_skill_calibration_review('user-b','2026-W35') is None
    assert len(list(tmp_path.glob('user-a_*.json')))==2


def test_cloud_schema_failure_keeps_review_retriable(tmp_path,monkeypatch):
    monkeypatch.setattr(calibration,'DATA_DIR',tmp_path)
    monkeypatch.setattr(calibration,'cloud_available',lambda:True)
    monkeypatch.setattr(calibration,'ensure_production_schema',lambda:(False,'database unavailable'))
    result=save_skill_calibration_review('u','week',{'status':'CURRENT'})
    assert result['status']=='FAILED'
    assert result['failures']==['database unavailable']


def test_v1131_worker_schema_and_ui_remain_non_executing():
    workflow=Path('.github/workflows/skill_calibration.yml').read_text(encoding='utf-8')
    worker=Path('scripts/run_skill_calibration_review.py').read_text(encoding='utf-8')
    schema=Path('core/production_storage.py').read_text(encoding='utf-8')
    view=Path('views/investment_desk.py').read_text(encoding='utf-8')
    config=Path('core/config.py').read_text(encoding='utf-8')
    assert 'contents: read' in workflow
    assert 'run_skill_calibration_review' in workflow
    assert 'download_prices' not in worker and 'yfinance' not in worker
    assert all(term not in (workflow+worker).lower() for term in ('alpaca','place_order','broker'))
    assert 'user_skill_calibration_reviews' in schema
    assert 'Human review queue' in view and 'automatic' in view
    version=next(line.split('=',1)[1].strip().strip('"') for line in config.splitlines() if line.startswith('APP_VERSION'))
    assert tuple(int(part) for part in version.split('.')) >= (11,31)
