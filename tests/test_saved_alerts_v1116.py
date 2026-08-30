from pathlib import Path


def test_saved_alerts_main_page_form_contract():
    root=Path(__file__).resolve().parents[1]
    text=(root/'views'/'saved_alerts.py').read_text(encoding='utf-8')
    assert "with st.form('create_saved_alert'" in text
    assert "Crear alerta" in text
    assert "user_id=uid" in text
    assert "alert_storage_health" in text


def test_alert_schema_is_user_scoped():
    root=Path(__file__).resolve().parents[1]
    storage=(root/'core'/'storage.py').read_text(encoding='utf-8')
    prod=(root/'core'/'production_storage.py').read_text(encoding='utf-8')
    assert "user_id VARCHAR" in storage
    assert "user_id TEXT" in prod
    assert "idx_saved_alerts_user_enabled" in prod
    assert "def list_alerts(enabled_only=False, user_id=None)" in storage


def test_alert_plan_caps_present():
    from core.plans import plan_config
    assert plan_config('FREE')['max_saved_alerts']==3
    assert plan_config('PRO')['max_saved_alerts']==25
    assert plan_config('PREMIUM')['max_saved_alerts']==100
    assert plan_config('OWNER')['max_saved_alerts'] is None


def test_price_alert_uses_live_quote_contract():
    root=Path(__file__).resolve().parents[1]
    text=(root/'core'/'alerts_engine.py').read_text(encoding='utf-8')
    assert 'get_live_price' in text
    assert "typ=='PRICE_BELOW'" in text
    assert "typ=='PRICE_ABOVE'" in text


def test_random_alert_ids_avoid_max_id_race():
    root=Path(__file__).resolve().parents[1]
    text=(root/'core'/'storage.py').read_text(encoding='utf-8')
    assert 'def _new_alert_id()' in text
    assert 'secrets.randbelow' in text
