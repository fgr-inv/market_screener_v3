from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import core.skill_governance as governance
from core.skill_calibration import build_skill_calibration_review
from core.skill_governance import (build_paper_readiness_report, load_skill_governance,
                                   proposal_key, save_skill_governance)


def _proposal(recommendation='REVIEW',version='1.0'):
    proposal={'agent':'Technical Signal','signal_state':'SETUP','skill_version':version,
              'recommendation':recommendation,'reason':'Evidence gate failed.'}
    return {**proposal,'proposal_key':proposal_key(proposal)}


def _ready_evidence():
    decisions=[]
    for i in range(100):
        decisions.append({'decision_key':f'd{i}','decision_at':f"2026-{1+(i//28):02d}-{1+(i%28):02d}T15:00:00+00:00",
                          'ticker':f'T{i%10}'})
    outcomes=[{'decision_key':f'd{i}','horizon_days':20,'status':'MATURED',
               'outcome_at':'2026-05-15T20:00:00+00:00'} for i in range(50)]
    calibration={'eligible_segments':2,'proposals':[]}
    return decisions,outcomes,calibration


def test_proposal_identity_is_stable_and_version_specific():
    first=_proposal(version='1.0')
    same=_proposal(version='1.0')
    newer=_proposal(version='1.1')
    assert first['proposal_key']==same['proposal_key']
    assert first['proposal_key']!=newer['proposal_key']


def test_governance_rejects_invalid_resolution(tmp_path,monkeypatch):
    monkeypatch.setattr(governance,'DATA_DIR',tmp_path)
    monkeypatch.setattr(governance,'cloud_available',lambda:False)
    result=save_skill_governance('u',_proposal(),'AUTO_PROMOTE')
    assert result['status']=='FAILED'
    assert result['failures']==['invalid resolution']


def test_governance_rejects_non_reviewable_segment(tmp_path,monkeypatch):
    monkeypatch.setattr(governance,'DATA_DIR',tmp_path)
    monkeypatch.setattr(governance,'cloud_available',lambda:False)
    result=save_skill_governance('u',_proposal('RETAIN'),'DEFER')
    assert result['status']=='FAILED'
    assert result['failures']==['proposal is not reviewable']


def test_local_governance_is_user_scoped_and_idempotent(tmp_path,monkeypatch):
    monkeypatch.setattr(governance,'DATA_DIR',tmp_path)
    monkeypatch.setattr(governance,'cloud_available',lambda:False)
    proposal=_proposal()
    first=save_skill_governance('user-a',proposal,'DEFER','wait')
    second=save_skill_governance('user-a',proposal,'ACKNOWLEDGE_AND_RETAIN','reviewed')
    assert first['status']=='CURRENT' and second['status']=='CURRENT'
    rows=load_skill_governance('user-a')
    assert len(rows)==1 and rows[0]['resolution']=='ACKNOWLEDGE_AND_RETAIN'
    assert rows[0]['automatic_change_applied'] is False and rows[0]['paper_mode_enabled'] is False
    assert load_skill_governance('user-b')==[]


def test_cloud_schema_failure_keeps_governance_retriable(tmp_path,monkeypatch):
    monkeypatch.setattr(governance,'DATA_DIR',tmp_path)
    monkeypatch.setattr(governance,'cloud_available',lambda:True)
    monkeypatch.setattr(governance,'ensure_production_schema',lambda:(False,'database unavailable'))
    monkeypatch.setattr(governance,'query_sql',lambda *a,**k:pd.DataFrame())
    result=save_skill_governance('u',_proposal(),'DEFER')
    assert result['status']=='FAILED'
    assert result['failures']==['database unavailable']


def test_readiness_starts_in_evidence_building_and_never_enables_paper():
    report=build_paper_readiness_report([],[],{'eligible_segments':0,'proposals':[]},[],'LOCAL_DUCKDB')
    assert report['status']=='EVIDENCE_BUILDING'
    assert report['paper_mode_enabled'] is False
    assert report['automatic_transition'] is False


def test_readiness_passes_only_to_human_review():
    decisions,outcomes,calibration=_ready_evidence()
    report=build_paper_readiness_report(decisions,outcomes,calibration,[],'POSTGRES')
    assert report['status']=='READY_FOR_PAPER_REVIEW'
    assert report['passed_gates']==report['total_gates']==8
    assert report['ready_for_human_review'] is True
    assert report['paper_mode_enabled'] is False


def test_ephemeral_storage_blocks_otherwise_ready_evidence():
    decisions,outcomes,calibration=_ready_evidence()
    report=build_paper_readiness_report(decisions,outcomes,calibration,[],'LOCAL_DUCKDB')
    assert report['status']=='EVIDENCE_BUILDING'
    assert report['gates'][0]['Status']=='BLOCKED'


def test_unresolved_review_blocks_readiness():
    decisions,outcomes,calibration=_ready_evidence(); proposal=_proposal()
    calibration['proposals']=[proposal]
    report=build_paper_readiness_report(decisions,outcomes,calibration,[],'POSTGRES')
    assert report['status']=='BLOCKED_REVIEW'
    assert report['unresolved_proposals'][0]['recorded_resolution']=='NONE'


def test_human_retain_can_resolve_review_but_not_pause_candidate():
    decisions,outcomes,calibration=_ready_evidence(); review=_proposal('REVIEW')
    retained={'proposal_key':review['proposal_key'],'resolution':'ACKNOWLEDGE_AND_RETAIN'}
    calibration['proposals']=[review]
    assert build_paper_readiness_report(decisions,outcomes,calibration,[retained],'POSTGRES')['status']=='READY_FOR_PAPER_REVIEW'
    pause=_proposal('PAUSE_CANDIDATE')
    calibration['proposals']=[pause]
    retained={'proposal_key':pause['proposal_key'],'resolution':'ACKNOWLEDGE_AND_RETAIN'}
    report=build_paper_readiness_report(decisions,outcomes,calibration,[retained],'POSTGRES')
    assert report['status']=='BLOCKED_REVIEW'
    assert len(report['unresolved_proposals'])==1


def test_request_revision_keeps_review_blocked_until_new_version():
    decisions,outcomes,calibration=_ready_evidence(); proposal=_proposal()
    calibration['proposals']=[proposal]
    record={'proposal_key':proposal['proposal_key'],'resolution':'REQUEST_REVISION'}
    report=build_paper_readiness_report(decisions,outcomes,calibration,[record],'POSTGRES')
    assert report['status']=='BLOCKED_REVIEW'


def test_historical_weak_version_does_not_block_validated_successor():
    decisions=[]; outcomes=[]
    for version,month,successes,alpha in [('1.0',1,8,-.5),('1.1',2,14,.7)]:
        for i in range(20):
            key=f'{version}-{i}'
            decisions.append({'decision_key':key,'decision_at':f'2026-{month:02d}-{(i%20)+1:02d}T15:00:00+00:00',
                              'ticker':f'T{i%6}','source_agent':'Technical Signal','signal_state':'SETUP',
                              'skill_version':version,'confidence':.6})
            outcomes.append({'decision_key':key,'horizon_days':5,'status':'MATURED','evaluated_at':'2026-06-01',
                             'success':i<successes,'signed_return_pct':1 if i<successes else -1,
                             'signed_alpha_pct':alpha})
    review=build_skill_calibration_review(decisions,outcomes)
    rows={row['Skill Version']:row for row in review['segments']}
    assert rows['1.0']['Version Role']=='HISTORICAL'
    assert rows['1.0']['Recommendation']=='REVIEW'
    assert rows['1.1']['Version Role']=='CURRENT'
    assert rows['1.1']['Recommendation']=='RETAIN'
    assert review['status']=='CURRENT' and review['proposals']==[]


def test_v1132_worker_schema_and_ui_have_no_execution_path():
    worker=Path('scripts/run_skill_calibration_review.py').read_text(encoding='utf-8')
    schema=Path('core/production_storage.py').read_text(encoding='utf-8')
    view=Path('views/investment_desk.py').read_text(encoding='utf-8')
    module=Path('core/skill_governance.py').read_text(encoding='utf-8')
    config=Path('core/config.py').read_text(encoding='utf-8')
    assert 'build_paper_readiness_report' in worker
    assert 'download_prices' not in worker and 'yfinance' not in worker
    assert 'user_skill_governance' in schema
    assert 'Paper Readiness Gate' in view and "'DISABLED'" in view
    assert 'paper_mode_enabled' in module and 'automatic_transition' in module
    assert all(term not in worker.lower() for term in ('alpaca','place_order','broker'))
    version=config.split('APP_VERSION = "',1)[1].split('"',1)[0]
    assert tuple(int(x) for x in version.split('.')) >= (11,32)
