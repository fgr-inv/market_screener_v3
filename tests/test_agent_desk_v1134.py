from datetime import datetime
from pathlib import Path

from core.agent_contracts import AgentResult
from core.portfolio_risk_agent import portfolio_fit_for_candidate
from core.shadow_validation import shadow_validation_summary
from scripts.run_daily_opportunity_hunt import opportunity_run_key


def test_empty_portfolio_fit_is_neutral_not_artificially_perfect():
    portfolio=AgentResult('Portfolio & Risk','1','skill','1','PORTFOLIO','UNAVAILABLE',0,'none',
                          metadata={'weights':{},'sector_weights':{}})
    fit,note=portfolio_fit_for_candidate('AMD','Technology',portfolio)
    assert fit == .6
    assert 'empty' in note.lower()


def test_shadow_summary_counts_unevaluated_horizons_as_pending():
    decisions=[{'decision_key':'d1'},{'decision_key':'d2'}]
    outcomes=[{'decision_key':'d1','horizon_days':1,'status':'PENDING'}]
    summary=shadow_validation_summary(decisions,outcomes)
    assert summary['unevaluated_outcomes'] == 5
    assert summary['pending_outcomes'] == 6


def test_opportunity_key_reuses_snapshot_but_changes_after_refresh():
    now=datetime(2026,9,3,20,0)
    first=opportunity_run_key(now,{'generated_at':'2026-09-03T19:00:00+00:00'})
    assert first == opportunity_run_key(now,{'generated_at':'2026-09-03T19:00:00+00:00'})
    assert first != opportunity_run_key(now,{'generated_at':'2026-09-03T20:00:00+00:00'})


def test_v1134_wires_candidate_sectors_and_manual_alert_refresh():
    runner=Path('core/desk_runner.py').read_text(encoding='utf-8')
    worker=Path('scripts/run_daily_opportunity_hunt.py').read_text(encoding='utf-8')
    alerts=Path('views/alerts.py').read_text(encoding='utf-8')
    config=Path('core/config.py').read_text(encoding='utf-8')
    assert 'candidate_sectors=None' in runner
    assert 'candidate_sectors=candidate_sectors' in worker
    assert "if st.button('Actualizar señales',type='primary'):" in alerts
    assert "or 'live_alert_rows' not in st.session_state" not in alerts
    assert 'desk_ticks' in alerts
    version=config.split('APP_VERSION = "',1)[1].split('"',1)[0]
    assert tuple(map(int,version.split('.'))) >= (11,34)
    assert all(term not in worker.lower() for term in ('tradingclient','place_order','submit_order','alpaca'))
