from pathlib import Path
import math

from core.alert_state import should_notify

ROOT=Path(__file__).resolve().parents[1]


def test_portfolio_storage_is_user_scoped():
    text=(ROOT/'core'/'storage.py').read_text(encoding='utf-8')
    prod=(ROOT/'core'/'production_storage.py').read_text(encoding='utf-8')
    assert 'user_portfolio_positions' in text
    assert 'user_investment_theses' in text
    assert 'PRIMARY KEY (user_id, ticker)' in prod
    assert 'def load_positions(user_id=None)' in text
    assert 'def load_theses(ticker=None, user_id=None)' in text


def test_trade_journal_is_user_scoped_and_cloud_capable():
    text=(ROOT/'core'/'trade_journal.py').read_text(encoding='utf-8')
    assert 'user_trade_journal' in text
    assert 'user_id=None' in text
    assert 'cloud_available()' in text
    assert 'Profit Factor' in text


def test_failed_alert_delivery_is_retriable():
    text=(ROOT/'scripts'/'run_alerts.py').read_text(encoding='utf-8')
    assert 'persisted_hit = bool(hit) if (not notify or delivered) else False' in text
    assert 'triggered=bool(notify and delivered)' in text


def test_nan_alert_state_rearms_as_false():
    notify,reason=should_notify(True,{'last_hit':float('nan')})
    assert notify is True
    assert reason=='EDGE'


def test_private_state_not_pushed_by_actions():
    workflow=(ROOT/'.github'/'workflows'/'alerts.yml').read_text(encoding='utf-8')
    assert 'contents: read' in workflow
    assert 'git push' not in workflow
    ignore=(ROOT/'.gitignore').read_text(encoding='utf-8')
    assert 'data/portfolio_positions.csv' in ignore
    assert 'data/investment_theses.csv' in ignore
    assert 'data/alert_state.csv' in ignore


def test_owner_only_operations_are_hidden_and_guarded():
    app=(ROOT/'app.py').read_text(encoding='utf-8')
    health=(ROOT/'views'/'system_health.py').read_text(encoding='utf-8')
    hub=(ROOT/'views'/'data_hub.py').read_text(encoding='utf-8')
    assert "if _nav_user.get('role')=='OWNER'" in app
    assert "user.get('role')!='OWNER'" in health
    assert "user.get('role')!='OWNER'" in hub
