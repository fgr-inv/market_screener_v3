from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_screener_uses_plan_caps_and_quota():
    s=(ROOT/'views'/'screener_shared.py').read_text(encoding='utf-8')
    assert "max_screener_assets" in s
    assert "require_quota" in s
    assert "record_usage" in s

def test_asset_analysis_has_levels_and_cache_free_deep_usage():
    s=(ROOT/'views'/'asset_analysis.py').read_text(encoding='utf-8')
    assert "Nivel de análisis" in s
    assert "deep_bundle_cache_fresh" in s
    assert "analysis_level=='Completo'" in s

def test_account_page_and_owner_nav_exist():
    app=(ROOT/'app.py').read_text(encoding='utf-8')
    acc=(ROOT/'views'/'account.py').read_text(encoding='utf-8')
    assert "views/account.py" in app
    assert "OWNER" in acc
