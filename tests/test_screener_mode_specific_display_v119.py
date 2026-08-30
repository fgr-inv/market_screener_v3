from pathlib import Path


def test_mode_specific_column_contracts_exist():
    src = Path("views/screener_shared.py").read_text(encoding="utf-8")
    assert "technical_cols=[" in src
    assert "fundamental_cols=[" in src
    assert "combined_cols=[" in src
    assert "if _active_mode=='Técnico'" in src
    assert "elif _active_mode=='Fundamental'" in src
    assert "Tabla técnica completa" in src
    assert "Tabla fundamental completa" in src
    assert "Tabla combinada completa" in src


def test_technical_and_fundamental_views_are_separated():
    src = Path("views/screener_shared.py").read_text(encoding="utf-8")
    technical_block = src.split("technical_cols=[",1)[1].split("]\n    fundamental_cols=[",1)[0]
    fundamental_block = src.split("fundamental_cols=[",1)[1].split("]\n    combined_cols=[",1)[0]
    assert "Quality_Score" not in technical_block
    assert "Valuation_Score" not in technical_block
    assert "Revision_Score" not in technical_block
    assert "RSI14" not in fundamental_block
    assert "Dist_EMA62_%" not in fundamental_block
    assert "Trend_Score" not in fundamental_block
