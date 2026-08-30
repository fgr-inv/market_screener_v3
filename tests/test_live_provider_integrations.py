import numpy as np
import pandas as pd


def test_eia_inventory_stats_chronological():
    from core.commodity_data import _inventory_stats
    dates = pd.date_range('2026-01-02', periods=70, freq='W-FRI')
    df = pd.DataFrame({'period': dates, 'value': np.arange(70, dtype=float) + 400})
    x = _inventory_stats(df)
    assert x['latest'] == 469.0
    assert x['1w_change'] == 1.0
    assert x['4w_change'] == 4.0


def test_fx_pair_parser():
    from core.fx_macro import parse_pair
    assert parse_pair('EURUSD=X') == ('EUR', 'USD')
    assert parse_pair('USD/JPY') == ('USD', 'JPY')


def test_fmp_missing_key_is_explicit(monkeypatch):
    import core.institutional_providers as ip
    monkeypatch.setattr(ip, '_secret', lambda name, default='': '')
    ip.fmp_equity_snapshot.clear()
    x = ip.fmp_equity_snapshot('AAPL')
    assert x['available'] is False
    assert x['provider'] == 'FMP'


def test_coingecko_header_uses_free_demo_key(monkeypatch):
    import core.free_market_providers as fp
    monkeypatch.setattr(fp, '_secret', lambda name, default='': 'demo123' if name == 'COINGECKO_API_KEY' else '')
    h = fp.coingecko_headers()
    assert h['x-cg-demo-api-key'] == 'demo123'


def test_free_crypto_aggregate_weighting(monkeypatch):
    import core.free_market_providers as fp
    fp.free_crypto_derivatives_snapshot.clear()
    monkeypatch.setattr(fp, 'binance_derivatives_snapshot', lambda symbol: {
        'provider':'Binance public','available':True,'Funding_Rate_%':0.01,
        'Open_Interest_USD':100.0,'Open_Interest_24h_%':5.0,'Perp_Basis_%':0.02,'Long_Short_Ratio':1.1})
    monkeypatch.setattr(fp, 'bybit_derivatives_snapshot', lambda symbol: {
        'provider':'Bybit public','available':True,'Funding_Rate_%':0.03,
        'Open_Interest_USD':300.0,'Perp_Basis_%':0.04})
    monkeypatch.setattr(fp, 'okx_derivatives_snapshot', lambda coin: {
        'provider':'OKX public','available':False,'Funding_Rate_%':np.nan,
        'Open_Interest_USD':np.nan,'Perp_Basis_%':np.nan})
    x=fp.free_crypto_derivatives_snapshot('BTC')
    assert x['Provider_Count'] == 2
    assert x['Open_Interest_USD'] == 400.0
    assert round(x['Funding_Rate_OI_Weighted_%'], 4) == 0.025
    assert x['Open_Interest_24h_%'] == 5.0
