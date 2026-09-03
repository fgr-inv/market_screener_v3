import pandas as pd

from core.portfolio_metadata import infer_position_sectors, normalize_portfolio_sector, sector_is_missing


def test_local_portfolio_sector_inference_covers_equities_and_bitcoin_etf():
    positions=pd.DataFrame([
        {'ticker':'AMD','sector':'Unknown'},
        {'ticker':'AMZN','sector':''},
        {'ticker':'IBIT','sector':'Unknown'},
        {'ticker':'LLY','sector':'Health Care'},
    ])
    inferred=infer_position_sectors(positions,live_fallback=False)
    assert inferred['AMD']=='Technology'
    assert inferred['AMZN']=='Consumer Discretionary'
    assert inferred['IBIT']=='Digital Assets'
    assert 'LLY' not in inferred


def test_sector_normalization_and_missing_detection():
    assert normalize_portfolio_sector('Information Technology')=='Technology'
    assert sector_is_missing('Unknown')
    assert sector_is_missing(None)
    assert not sector_is_missing('Health Care')


def test_portfolio_page_does_not_treat_missing_cost_as_profit():
    source=open('views/portfolio.py',encoding='utf-8').read()
    assert "c2.metric('Cost Basis','N/D')" in source
    assert "c3.metric('Unrealized P&L','N/D')" in source
    assert "covered_value-invested" in source
    assert "total-invested" not in source
    assert 'Completar sectores automáticamente' in source
    assert 'Convertir pesos actuales a porcentajes' in source
