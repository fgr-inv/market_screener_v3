from datetime import datetime,timezone
from pathlib import Path

import pandas as pd

import core.data_budget as data_budget
from core.agent_contracts import AgentResult,DataStatus,Evidence,VerificationStatus
from core.fundamental_agent import analyze_fundamental
from core.grounded_narrator import apply_grounded_narrator
from core.journal_agent import build_journal_review
from core.market_report_delivery import notify_market_report
from core.verification_agent import verify_result
from core.agent_registry import AGENT_REGISTRY,validate_agent_registry


def test_verifier_downgrades_current_evidence_without_value_source_or_timestamp():
    result=AgentResult('A','1','s','1','X','WATCH',.9,'x',[
        Evidence('missing value',None,'source',status=DataStatus.CURRENT),
        Evidence('missing source',1,'',status=DataStatus.CURRENT),
        Evidence('missing timestamp',1,'source',observed_at='',status=DataStatus.CURRENT),
    ])
    checked=verify_result(result)
    assert checked.verification_status==VerificationStatus.NOT_CHECKED
    assert checked.confidence<=.49
    assert checked.metadata['verification']['current_evidence']==0


def test_fundamental_zero_score_is_not_replaced_with_neutral(monkeypatch,tmp_path):
    class Budget:
        ttl_seconds=604800
        def to_dict(self): return {'ttl_seconds':self.ttl_seconds}
    fake={'Fundamentals_Available':True,'Fundamental_Score':0,'Revenue_Growth':0,
          'Earnings_Growth':0,'Profit_Margin':0,'ROE':0,'FCF':0,'Fundamentals_Source':'TEST'}
    monkeypatch.setattr('core.fundamental_agent.shared_fundamental_snapshot',lambda *a,**k:(fake.copy(),Budget(),False))
    monkeypatch.setattr('core.fundamental_agent.get_market_valuation_snapshot',lambda *a,**k:{})
    result=analyze_fundamental('ZERO')
    assert result.state=='DETERIORATING'
    score=next(row.value for row in result.evidence if row.claim=='Fundamental score')
    assert score==0


def test_cloud_snapshot_cache_survives_worker_filesystem(monkeypatch,tmp_path):
    stored={}
    monkeypatch.setattr(data_budget,'ROOT',tmp_path); monkeypatch.setattr(data_budget,'FUND_DIR',tmp_path/'fundamentals')
    monkeypatch.setattr(data_budget,'cloud_available',lambda:True)
    monkeypatch.setattr(data_budget,'ensure_production_schema',lambda:(True,'OK'))
    def execute(sql,params): stored.update(params); return True,'OK'
    def query(sql,params):
        if not stored: return pd.DataFrame()
        return pd.DataFrame([{'refreshed_at':stored['refreshed_at'],'payload_json':stored['payload']}])
    monkeypatch.setattr(data_budget,'execute_sql',execute); monkeypatch.setattr(data_budget,'query_sql',query)
    calls=[]
    first=data_budget.shared_fundamental_snapshot('ABC',lambda ticker:(calls.append(ticker) or {'Fundamentals_Available':True}))
    local=data_budget.snapshot_path('ABC'); local.unlink()
    second=data_budget.shared_fundamental_snapshot('ABC',lambda ticker:(calls.append(ticker) or {}))
    assert first[2] is True and second[2] is False and calls==['ABC']


def test_grounded_narrator_falls_back_on_invented_number():
    packet={'macro':{'VIX':18},'sectors':[{'sector':'Technology'}]}
    report={'executive_summary':'base','macro_analysis':['base'],'sector_analysis':[{'sector':'Technology','analysis':'base'}],
            'scenarios':{},'evidence_refs':['macro:regime','sector:Technology']}
    def narrator(base,evidence):
        return {'executive_summary':'VIX 999','macro_analysis':['VIX 999'],
                'sector_analysis':[{'sector':'Technology','analysis':'999'}],
                'evidence_refs':['macro:regime','sector:Technology']}
    result=apply_grounded_narrator(report,packet,narrator)
    assert result['executive_summary']=='base'
    assert result['narrative_adapter']['status']=='DETERMINISTIC_FALLBACK'


def test_journal_agent_surfaces_repeated_weakness_without_changing_rules():
    decisions=[]; outcomes=[]
    for index in range(4):
        key=f'k{index}'
        decisions.append({'decision_key':key,'source_agent':'Technical Signal','signal_state':'SETUP','ticker':f'T{index}','confidence':.8})
        outcomes.append({'decision_key':key,'horizon_days':5,'status':'MATURED','success':index==0,
                         'signed_alpha_pct':-1,'mae_pct':-3,'evaluated_at':'2026-09-01'})
    review=build_journal_review(decisions,outcomes)
    assert review['status']=='REVIEW_REQUIRED' and len(review['recurring_patterns'])==1
    assert review['automatic_rule_changes']==0 and review['no_execution'] is True


def test_report_delivery_resumes_only_missing_parts(monkeypatch):
    report={'report_type':'daily','title':'R','schema_version':'1','generated_at':datetime.now(timezone.utc).isoformat(),
            'executive_summary':'x','macro_analysis':['m'],'sector_analysis':[],
            'scenarios':{},'verification':{'status':'VERIFIED','sector_count':11}}
    state={'payload':{'delivered':False,'delivered_parts':[1]}}; sent=[]
    monkeypatch.setattr('core.market_report_delivery.load_desk_output',lambda *a,**k:state)
    monkeypatch.setattr('core.market_report_delivery.save_desk_output',lambda *a,**k:{})
    monkeypatch.setattr('core.market_report_delivery.get_user_webhook',lambda uid:'https://discord.com/api/webhooks/a/b')
    result=notify_market_report('u',report,'run',send_fn=lambda *a,**k:(sent.append(k) or True))
    assert result['delivered'] is True and sent==[]


def test_all_workflows_use_the_shared_python_setup():
    workflows=list(Path('.github/workflows').glob('*.yml'))
    assert workflows
    for path in workflows:
        text=path.read_text(encoding='utf-8')
        assert 'uses: ./.github/actions/setup-python' in text


def test_agent_registry_has_explicit_non_execution_boundaries():
    assert validate_agent_registry() is True
    assert {'technical','fundamental','news','market','portfolio','verification','cio','strategist','journal'}==set(AGENT_REGISTRY)
    assert all(spec.may_execute is False for spec in AGENT_REGISTRY.values())
