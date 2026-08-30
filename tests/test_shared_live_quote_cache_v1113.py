import json
import time
from pathlib import Path

from core.cache_policy import LIVE_PRICE_TTL
import core.market_data as md


def test_live_quote_shared_cache_contract_present():
    text=Path('core/market_data.py').read_text(encoding='utf-8')
    assert "LIVE_QUOTE_CACHE" in text
    assert "_read_live_quote_cache" in text
    assert "_write_live_quote_cache" in text
    assert "_acquire_quote_lock" in text
    assert "_get_live_price_shared" in text
    assert "@st.cache_data(ttl=LIVE_PRICE_TTL" in text


def test_shared_live_quote_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(md,'LIVE_QUOTE_CACHE',tmp_path)
    md._write_live_quote_cache('AMD',123.45)
    assert md._read_live_quote_cache('AMD') == 123.45


def test_shared_live_quote_cache_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(md,'LIVE_QUOTE_CACHE',tmp_path)
    path=md._live_quote_path('AMD')
    path.write_text(json.dumps({'ticker':'AMD','price':123.45,'timestamp':time.time()-LIVE_PRICE_TTL-10}))
    assert md._read_live_quote_cache('AMD') is None


def test_shared_get_avoids_provider_when_cache_is_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(md,'LIVE_QUOTE_CACHE',tmp_path)
    md._write_live_quote_cache('AMD',200.0)
    calls={'n':0}
    def fake_provider(ticker):
        calls['n']+=1
        return 201.0
    monkeypatch.setattr(md,'_fetch_live_price_provider',fake_provider)
    assert md._get_live_price_shared('AMD') == 200.0
    assert calls['n'] == 0


def test_shared_get_refreshes_once_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(md,'LIVE_QUOTE_CACHE',tmp_path)
    calls={'n':0}
    def fake_provider(ticker):
        calls['n']+=1
        return 222.0
    monkeypatch.setattr(md,'_fetch_live_price_provider',fake_provider)
    assert md._get_live_price_shared('AMD') == 222.0
    assert md._get_live_price_shared('AMD') == 222.0
    assert calls['n'] == 1
