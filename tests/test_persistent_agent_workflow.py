from types import SimpleNamespace

import pandas as pd

from core.agent_contracts import AgentResult, DataStatus, Evidence, VerificationStatus
from core.desk_workflow import (WorkflowLedger, build_research_packet,
                                compare_cio_briefs, handoff_from_result)
from core.thesis_memory import build_thesis_memory


def _context():
    bars = pd.DataFrame({'Close': [100, 102], 'Volume': [10, 12]})
    return SimpleNamespace(
        positions=pd.DataFrame([{'ticker': 'NVDA', 'allocation_pct': 8}]),
        theses=pd.DataFrame([{'ticker': 'NVDA', 'thesis': 'Durable AI demand'}]),
        histories={'NVDA': bars},
        macro={'Growth': 55},
        meta={'generated_at': pd.Timestamp.now(tz='UTC').isoformat(), 'sources': ['FRED', 'prices']},
        sectors=pd.DataFrame([{'Sector': 'Technology'}]),
        screener=pd.DataFrame([{'Ticker': 'NVDA', 'Entry_Score': 72}]),
    )


def test_research_packet_is_versioned_bounded_and_asset_specific():
    packet = build_research_packet('run-1', _context(), {'NVDA': ['technical', 'fundamental']}, ['portfolio'])
    assert packet['packet_version'] == '1.0'
    assert packet['packet_digest']
    assert packet['asset_types']['NVDA']
    assert packet['manifests']['histories']['NVDA']['rows'] == 2
    assert 'Close' not in packet  # the manifest proves context without duplicating raw bars
    assert packet['no_execution'] is True


def test_handoff_and_workflow_make_partial_evidence_explicit():
    result = AgentResult(
        'Technical Signal', '1', 'technical', '1', 'NVDA', 'SETUP', .72, 'Constructive pullback',
        [Evidence('structure', 'uptrend', 'prices', status=DataStatus.CURRENT)],
    )
    result.verification_status = VerificationStatus.PARTIALLY_VERIFIED
    handoff = handoff_from_result('run-1', result).to_dict()
    assert handoff['status'] == 'PARTIAL'
    assert handoff['next_owner'] == 'cio'
    ledger = WorkflowLedger('run-1', {'ticker_agents': {'NVDA': ['technical']}, 'global_agents': []})
    ledger.start('technical', 'NVDA'); ledger.finish('technical', 'NVDA', handoff['status'])
    assert ledger.snapshot()['status'] == 'PARTIAL'


def test_cio_diff_highlights_only_material_changes():
    previous = {'market_regime': {'state': 'NEUTRAL'},
                'decisions_needed': [{'subject': 'NVDA', 'state': 'WATCH'}],
                'top_opportunities': []}
    current = {'market_regime': {'state': 'RISK_OFF', 'summary': 'Credit weakened'},
               'decisions_needed': [{'subject': 'NVDA', 'state': 'BROKEN_SETUP'}],
               'top_opportunities': [{'Ticker': 'MSFT'}]}
    diff = compare_cio_briefs(previous, current)
    assert diff['status'] == 'CHANGED'
    assert {row['section'] for row in diff['items']} == {'market_regime', 'decisions', 'opportunities'}


def test_thesis_memory_versions_user_thesis_and_preserves_review_history():
    thesis = [{'ticker': 'NVDA', 'thesis': 'AI demand', 'invalidation': 'Guidance cut', 'status': 'ACTIVE'}]
    handoff = [{'subject': 'NVDA', 'agent': 'Fundamental Analyst', 'state': 'INTACT',
                'summary': 'Thesis remains intact', 'verification_status': 'VERIFIED',
                'confidence': .8, 'contradictions': [], 'sources': ['IR']}]
    first = build_thesis_memory('u', 'run-1', thesis, handoff, previous={})
    assert first['assets']['NVDA']['thesis_version'] == 1
    changed = [{**thesis[0], 'thesis': 'AI demand and networking'}]
    second = build_thesis_memory('u', 'run-2', changed, [{**handoff[0], 'state': 'IMPROVING'}], previous=first)
    asset = second['assets']['NVDA']
    assert asset['thesis_version'] == 2
    assert asset['last_state'] == 'IMPROVING'
    assert asset['history'][-1]['state'] == 'INTACT'
