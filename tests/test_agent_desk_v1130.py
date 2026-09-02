from datetime import datetime,timezone
import pandas as pd

import core.shadow_validation as shadow
from core.shadow_validation import (capture_shadow_decisions,load_shadow_decisions,evaluate_decisions,
                                    persist_shadow_outcomes,load_shadow_outcomes,shadow_validation_summary)


def _history(values,start='2026-01-05'):
    return pd.DataFrame({'Close':values},index=pd.bdate_range(start,periods=len(values)))


def _brief(state='SETUP',direction_agent='Technical Signal'):
    return {
        'decisions_needed':[{'subject':'AAA','agent':direction_agent,'state':state,'confidence':.8,
                             'summary':'test','verification_status':'VERIFIED','skill_version':'1.2'}],
        'top_opportunities':[],'events_considered':[],
    }


def test_shadow_capture_is_user_scoped_and_idempotent(tmp_path,monkeypatch):
    monkeypatch.setattr(shadow,'DATA_DIR',tmp_path)
    monkeypatch.setattr(shadow,'cloud_available',lambda:False)
    histories={'AAA':_history([98,100]),'SPY':_history([99,100])}
    first=capture_shadow_decisions('user-a','run-1',_brief(),histories)
    second=capture_shadow_decisions('user-a','run-1',_brief(),histories)
    assert first['status']=='CURRENT' and len(first['created'])==1
    assert second['created']==[] and second['skipped']==1
    assert len(load_shadow_decisions('user-a'))==1
    assert load_shadow_decisions('user-b')==[]
    row=first['created'][0]
    assert row['baseline_price']==100 and row['benchmark_price']==100
    assert row['expected_direction']=='POSITIVE' and row['shadow_mode'] is True


def test_shadow_capture_rejects_watch_and_unverified_items(tmp_path,monkeypatch):
    monkeypatch.setattr(shadow,'DATA_DIR',tmp_path); monkeypatch.setattr(shadow,'cloud_available',lambda:False)
    brief={'decisions_needed':[
        {'subject':'AAA','agent':'Technical Signal','state':'WATCH','confidence':.8,'verification_status':'VERIFIED'},
        {'subject':'BBB','agent':'Technical Signal','state':'SETUP','confidence':.8,'verification_status':'STALE_DATA'},
    ],'top_opportunities':[]}
    result=capture_shadow_decisions('u','run',brief,{})
    assert result['created']==[] and result['total_candidates']==0


def test_shadow_capture_reports_cloud_write_failure(tmp_path,monkeypatch):
    monkeypatch.setattr(shadow,'DATA_DIR',tmp_path); monkeypatch.setattr(shadow,'cloud_available',lambda:True)
    monkeypatch.setattr(shadow,'ensure_production_schema',lambda:(True,'OK'))
    monkeypatch.setattr(shadow,'query_sql',lambda *a,**k:pd.DataFrame())
    monkeypatch.setattr(shadow,'execute_sql',lambda *a,**k:(False,'database unavailable'))
    result=capture_shadow_decisions('u','run',_brief(),{'AAA':_history([100]),'SPY':_history([100])})
    assert result['status']=='FAILED'
    assert result['failures'][0]['error']=='database unavailable'


def test_forward_evaluation_uses_trading_days_and_spy_alpha():
    decision={'user_id':'u','decision_key':'d1','decision_at':'2026-01-05T15:00:00+00:00','ticker':'AAA',
              'source_agent':'Technical Signal','signal_state':'SETUP','expected_direction':'POSITIVE',
              'confidence':.8,'baseline_price':100,'benchmark_price':100}
    asset=_history([100]+list(range(101,121)))
    spy=_history([100]+[100+i*.2 for i in range(1,21)])
    outcomes=evaluate_decisions([decision],{'AAA':asset,'SPY':spy},evaluated_at=datetime.now(timezone.utc))
    assert [r['horizon_days'] for r in outcomes]==[1,5,20]
    assert all(r['status']=='MATURED' for r in outcomes)
    assert outcomes[0]['asset_return_pct']==1
    assert outcomes[0]['benchmark_return_pct']==.2
    assert outcomes[0]['signed_alpha_pct']==.8
    assert outcomes[-1]['success'] is True


def test_negative_signal_scores_falling_price_as_correct():
    decision={'user_id':'u','decision_key':'d2','decision_at':'2026-01-05','ticker':'AAA','source_agent':'Technical Signal',
              'signal_state':'BROKEN_SETUP','expected_direction':'NEGATIVE','confidence':.7,'baseline_price':100,'benchmark_price':100}
    outcomes=evaluate_decisions([decision],{'AAA':_history([100,95]),'SPY':_history([100,100])},horizons=(1,))
    assert outcomes[0]['asset_return_pct']==-5
    assert outcomes[0]['signed_return_pct']==5
    assert outcomes[0]['success'] is True


def test_missing_future_bars_stay_pending_not_zero():
    decision={'user_id':'u','decision_key':'d3','decision_at':'2026-01-05','ticker':'AAA','source_agent':'Technical Signal',
              'signal_state':'SETUP','expected_direction':'POSITIVE','confidence':.7,'baseline_price':100,'benchmark_price':100}
    outcome=evaluate_decisions([decision],{'AAA':_history([100,101]),'SPY':_history([100,101])},horizons=(5,))[0]
    assert outcome['status']=='PENDING'
    assert outcome['asset_return_pct'] is None and outcome['success'] is None


def test_stale_baseline_is_never_scored_as_current():
    decision={'user_id':'u','decision_key':'d4','decision_at':'2026-01-05','ticker':'AAA','source_agent':'Technical Signal',
              'signal_state':'SETUP','expected_direction':'POSITIVE','confidence':.7,'baseline_price':100,
              'benchmark_price':100,'baseline_status':'STALE'}
    outcome=evaluate_decisions([decision],{'AAA':_history([100,110]),'SPY':_history([100,101])},horizons=(1,))[0]
    assert outcome['status']=='STALE'
    assert outcome['asset_return_pct'] is None and outcome['success'] is None


def test_outcome_persistence_upserts_same_decision_horizon(tmp_path,monkeypatch):
    monkeypatch.setattr(shadow,'DATA_DIR',tmp_path); monkeypatch.setattr(shadow,'cloud_available',lambda:False)
    pending={'user_id':'u','decision_key':'d','horizon_days':1,'evaluated_at':'2026-01-06','status':'PENDING'}
    matured={**pending,'evaluated_at':'2026-01-07','status':'MATURED','success':True}
    persist_shadow_outcomes('u',[pending]); persist_shadow_outcomes('u',[matured])
    rows=load_shadow_outcomes('u')
    assert len(rows)==1 and rows[0]['status']=='MATURED'


def test_outcome_persistence_reports_cloud_write_failure(tmp_path,monkeypatch):
    monkeypatch.setattr(shadow,'DATA_DIR',tmp_path); monkeypatch.setattr(shadow,'cloud_available',lambda:True)
    monkeypatch.setattr(shadow,'ensure_production_schema',lambda:(True,'OK'))
    monkeypatch.setattr(shadow,'query_sql',lambda *a,**k:pd.DataFrame())
    monkeypatch.setattr(shadow,'execute_sql',lambda *a,**k:(False,'write failed'))
    row={'user_id':'u','decision_key':'d','horizon_days':1,'evaluated_at':'2026-01-06','status':'PENDING'}
    result=persist_shadow_outcomes('u',[row])
    assert result['status']=='FAILED' and result['failures'][0]['error']=='write failed'


def test_summary_refuses_early_performance_conclusion():
    decisions=[{'decision_key':'d'}]
    outcomes=[{'decision_key':'d','horizon_days':1,'status':'MATURED','success':True,'confidence':.8,
               'signed_return_pct':2,'signed_alpha_pct':1}]
    summary=shadow_validation_summary(decisions,outcomes)
    assert summary['status']=='NOT_ENOUGH_DATA'
    assert summary['horizons'][0]['Sample']==1
    assert summary['horizons'][0]['Status']=='NOT_ENOUGH_DATA'


def test_summary_becomes_current_only_at_minimum_sample():
    decisions=[{'decision_key':str(i)} for i in range(20)]
    outcomes=[{'decision_key':str(i),'horizon_days':1,'status':'MATURED','success':i<12,'confidence':.6,
               'signed_return_pct':1 if i<12 else -1,'signed_alpha_pct':.5 if i<12 else -.5} for i in range(20)]
    summary=shadow_validation_summary(decisions,outcomes)
    assert summary['status']=='CURRENT'
    assert summary['horizons'][0]['Hit Rate %']==60


def test_shadow_worker_and_schema_remain_non_executing():
    workflow=open('.github/workflows/shadow_validation.yml',encoding='utf-8').read()
    schema=open('core/production_storage.py',encoding='utf-8').read()
    runner=open('core/desk_runner.py',encoding='utf-8').read()
    assert 'contents: read' in workflow
    assert 'evaluate_shadow_decisions' in workflow
    assert 'alpaca' not in workflow.lower() and 'order' not in workflow.lower()
    assert 'user_shadow_decisions' in schema and 'user_shadow_outcomes' in schema
    assert 'capture_shadow_decisions' in runner
