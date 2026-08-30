from pathlib import Path

from core.cache_policy import (
    MINUTE,
    LIVE_PRICE_TTL,
    HISTORICAL_PRICE_TTL,
    PRICE_TTL,
    TECHNICAL_TTL,
    PRICE_DISK_MAX_AGE_MINUTES,
)


def test_market_freshness_policy_is_layered():
    assert LIVE_PRICE_TTL == 5 * MINUTE
    assert PRICE_TTL == LIVE_PRICE_TTL
    assert TECHNICAL_TTL == 15 * MINUTE
    assert HISTORICAL_PRICE_TTL == 60 * MINUTE
    assert PRICE_DISK_MAX_AGE_MINUTES == 60


def test_historical_download_does_not_use_live_quote_ttl():
    text = Path('core/market_data.py').read_text(encoding='utf-8')
    assert '@st.cache_data(ttl=HISTORICAL_PRICE_TTL' in text
    assert 'def get_live_price' in text
    assert '@st.cache_data(ttl=LIVE_PRICE_TTL' in text


def test_asset_analysis_overlays_fresh_quote():
    text = Path('views/asset_analysis.py').read_text(encoding='utf-8')
    assert 'get_live_price' in text
    assert "row['Price']=live_price" in text
