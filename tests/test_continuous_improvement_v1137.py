from datetime import datetime, timedelta, timezone
from pathlib import Path

import core.continuous_improvement as improvement
from core.agent_contracts import AgentResult
from core.continuous_improvement import (
    apply_improvement_policy,
    build_continuous_improvement_review,
    notify_improvement_review,
)


def _ledger(train_successes=18, validation_successes=8, sample=30, confidence=.6,
            agent='Technical Signal', state='SETUP', version='1.0', horizon=5):
    decisions=[]; outcomes=[]; start=datetime(2026,1,1,tzinfo=timezone.utc)
    train_size=sample-10
    for index in range(sample):
        key=f'd{index}'; success=(index<train_successes if index<train_size else index-train_size<validation_successes)
        decisions.append({'decision_key':key,'decision_at':(start+timedelta(days=index)).isoformat(),
                          'ticker':f'T{index%6}','source_agent':agent,'signal_state':state,
                          'skill_version':version,'confidence':confidence})
        outcomes.append({'decision_key':key,'horizon_days':horizon,'status':'MATURED',
                         'evaluated_at':(start+timedelta(days=index+30)).isoformat(),
                         'success':success,'signed_alpha_pct':1 if success else -1})
    return decisions,outcomes


def test_review_requires_forward_evidence_before_any_adjustment():
    decisions,outcomes=_ledger(sample=29,train_successes=17,validation_successes=8)
    report=build_continuous_improvement_review(decisions,outcomes,generated_at='2026-09-01')
    assert report['status']=='NOT_ENOUGH_DATA'
    assert report['automatic_promotions']==0
    assert report['candidates'][0]['status']=='NOT_ENOUGH_DATA'
    assert report['next_policy']['entries']=={}


def test_validated_challenger_is_promoted_within_narrow_bounds():
    decisions,outcomes=_ledger(train_successes=18,validation_successes=9)
    report=build_continuous_improvement_review(decisions,outcomes,generated_at='2026-09-01')
    row=report['candidates'][0]
    assert report['status']=='UPDATED' and report['automatic_promotions']==1
    assert row['status']=='AUTO_PROMOTED'
    assert row['challenger_multiplier']==1.1
    assert row['brier_improvement']>=.005
    entry=report['next_policy']['entries'][row['segment_key']]
    assert .9<=entry['confidence_multiplier']<=1.1
    assert entry['rollback_multiplier']==1.0


def test_challenger_is_held_when_recent_validation_does_not_improve():
    decisions,outcomes=_ledger(train_successes=18,validation_successes=2)
    report=build_continuous_improvement_review(decisions,outcomes,generated_at='2026-09-01')
    assert report['status']=='CHAMPION_RETAINED'
    assert report['automatic_promotions']==0
    assert report['candidates'][0]['status']=='HOLD_CHAMPION'


def test_policy_changes_only_exact_matching_confidence_and_records_provenance():
    result=AgentResult('Technical Signal','1.0','technical_entry_review','1.0','AMD','SETUP',.8,'ok')
    key='Technical Signal|SETUP|1.0'
    policy={'entries':{key:{'confidence_multiplier':.9}}}
    calibrated=apply_improvement_policy(result,policy)
    assert calibrated.confidence==.72
    meta=calibrated.metadata['continuous_improvement']
    assert meta['original_confidence']==.8 and meta['scope']=='confidence_only'
    unmatched=AgentResult('Technical Signal','1.0','technical_entry_review','1.0','AMD','WATCH',.8,'ok')
    assert apply_improvement_policy(unmatched,policy).confidence==.8


def test_weekly_discord_review_is_deduplicated(monkeypatch):
    stored={}; sent=[]
    monkeypatch.setattr(improvement,'get_user_webhook',lambda uid:'https://discord.com/api/webhooks/id/token')
    monkeypatch.setattr(improvement,'load_desk_output',lambda uid,typ,key:stored.get((typ,key)))
    def save(uid,typ,payload,run_key=None):
        stored[(typ,run_key)]={'payload':payload}; return stored[(typ,run_key)]
    monkeypatch.setattr(improvement,'save_desk_output',save)
    def sender(message,**kwargs): sent.append((message,kwargs)); return True
    report={'status':'CHAMPION_RETAINED','eligible_segments':1,'automatic_promotions':0,
            'promotions':[],'generated_at':'2026-09-01T12:00:00+00:00'}
    first=notify_improvement_review('u',report,'week',send_fn=sender)
    second=notify_improvement_review('u',report,'week',send_fn=sender)
    assert first['status']=='DELIVERED' and second['status']=='DUPLICATE'
    assert len(sent)==1 and 'Continuous Improvement' in sent[0][1]['discord_embed']['author']['name']


def test_v1137_workflow_ui_agent_and_shadow_boundaries():
    workflow=Path('.github/workflows/continuous_improvement.yml').read_text(encoding='utf-8')
    agent=Path('.github/agents/investment-desk-maintainer.agent.md').read_text(encoding='utf-8')
    worker=Path('scripts/run_continuous_improvement_review.py').read_text(encoding='utf-8')
    desk=Path('views/investment_desk.py').read_text(encoding='utf-8')
    config=Path('core/config.py').read_text(encoding='utf-8')
    assert "cron: '30 15 * * 6'" in workflow and 'contents: read' in workflow
    assert 'run_continuous_improvement_review' in workflow
    assert 'Continuous Improvement' in desk
    version=config.split('APP_VERSION = "',1)[1].split('"',1)[0]
    assert tuple(int(part) for part in version.split('.')) >= (11,37)
    assert 'Never merge' in agent and 'Never add, enable or call broker/order' in agent
    runtime=(workflow+worker).lower()
    assert all(term not in runtime for term in ('place_order','submit_order','tradingclient','alpaca'))
