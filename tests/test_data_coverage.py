from core.data_coverage import equity_data_coverage, asset_data_coverage, industry_lens_key


def test_bank_specialist_gap_is_visible():
    f = {
        'Market_Cap': 1, 'Revenue_Growth': .05, 'Earnings_Growth': .08,
        'Gross_Margin': .5, 'Operating_Margin': .2, 'ROE': .15, 'FCF': 1,
        'Total_Debt': 1, 'Total_Cash': 1, 'Forward_PE': 12, 'Price_to_Book': 1.5,
        'EV_EBITDA': 8,
    }
    cov = equity_data_coverage(f, 'Financials', 'Banks - Diversified')
    assert industry_lens_key('Banks - Diversified') == 'banks'
    assert cov['Core_Data_Coverage_%'] == 100.0
    assert cov['Specialist_Data_Coverage_%'] == 0.0
    assert 'CET1' in cov['Missing_Critical_Data']
    assert cov['Data_Coverage_Score'] < 70


def test_crypto_requires_specialist_data():
    ctx = {'20d_Return': .1, '63d_Return': .3, 'BTC_Dominance': 58}
    cov = asset_data_coverage('BTC-USD', 'Cripto', ctx, {})
    assert cov['Core_Data_Coverage_%'] == 100.0
    assert cov['Specialist_Data_Coverage_%'] == 0.0
    assert 'Funding_Rate' in cov['Missing_Critical_Data']


def test_fx_flags_carry_gap():
    ctx = {'20d_Return': .01, '63d_Return': .02, 'Dollar_20d': -.01}
    cov = asset_data_coverage('EURUSD=X', 'Forex', ctx, {})
    assert 'Carry_Differential' in cov['Missing_Critical_Data']
