from core.config import ASSET_PRESETS, CRYPTO_RESEARCH_WATCHLIST
from core.crypto_professional import CG_IDS
from scripts.run_news_catalyst_monitor import news_watchlist_tickers


def test_research_watchlist_contains_requested_crypto_assets():
    assert CRYPTO_RESEARCH_WATCHLIST == [
        'BTC-USD','ETH-USD','SOL-USD','AAVE-USD','ZEC-USD','UNI-USD',
    ]
    assert {'ZEC-USD','UNI-USD'}.issubset(ASSET_PRESETS['Cripto']['Ampliado'])


def test_requested_assets_have_professional_metadata_routes():
    assert CG_IDS['ZEC']=='zcash'
    assert CG_IDS['UNI']=='uniswap'


def test_hourly_news_watchlist_keeps_requested_crypto_assets():
    monitored=news_watchlist_tickers(['AMD','ZEC-USD'])
    assert monitored[0]=='AMD'
    assert monitored.count('ZEC-USD')==1
    assert {'ZEC-USD','UNI-USD'}.issubset(monitored)
