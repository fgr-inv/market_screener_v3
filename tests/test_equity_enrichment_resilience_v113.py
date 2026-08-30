import pandas as pd


def test_standalone_valuation_does_not_invent_neutral_score():
    from core.valuation import standalone_valuation_score
    assert pd.isna(standalone_valuation_score({}))
