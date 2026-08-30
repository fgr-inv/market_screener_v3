from pathlib import Path

from core.cache_policy import (
    DAY, HOUR, MINUTE,
    FUNDAMENTALS_TTL, ANALYST_TTL, EVENT_TTL, FRED_TTL,
    PRICE_TTL, PRICE_DISK_MAX_AGE_MINUTES, NEWS_TTL, OPTIONS_TTL,
)


def test_cache_policy_expected_ttls():
    assert FUNDAMENTALS_TTL == 7 * DAY
    assert ANALYST_TTL == 12 * HOUR
    assert EVENT_TTL == 12 * HOUR
    assert FRED_TTL == 12 * HOUR
    assert PRICE_TTL == 5 * MINUTE
    assert PRICE_DISK_MAX_AGE_MINUTES == 60
    assert NEWS_TTL == 30 * MINUTE
    assert OPTIONS_TTL == 30 * MINUTE


def test_asset_analysis_uses_shared_deep_cache():
    text = Path('views/asset_analysis.py').read_text(encoding='utf-8')
    assert 'fetch_deep_bundle(ticker)' in text
    assert 'cached_fund=st.session_state.fundamentals_cache.get' not in text


def test_screener_deep_cache_uses_central_policy():
    text = Path('core/screener_enrichment.py').read_text(encoding='utf-8')
    assert 'from core.cache_policy import FUNDAMENTALS_TTL, ANALYST_TTL, EVENT_TTL' in text
    assert 'FUNDAMENTALS_TTL = 6 * 3600' not in text

def test_daily_valuation_overlay_is_separate_from_weekly_fundamentals():
    text = Path('core/screener_enrichment.py').read_text(encoding='utf-8')
    assert "cached.get('valuation'" in text
    assert '_fresh(vsec, VALUATION_TTL' in text
    fundamentals = Path('core/fundamentals.py').read_text(encoding='utf-8')
    assert '@st.cache_data(ttl=VALUATION_TTL' in fundamentals
    assert 'def get_market_valuation_snapshot' in fundamentals
