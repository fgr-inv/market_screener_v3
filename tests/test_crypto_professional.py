from core.crypto_professional import crypto_model_type, _score_tokenomics

def test_crypto_model_routing():
    assert crypto_model_type('BTC-USD') == 'Bitcoin'
    assert crypto_model_type('ETH-USD') == 'Ethereum'
    assert crypto_model_type('SOL-USD') == 'L1/L2'
    assert crypto_model_type('AAVE-USD') == 'DeFi'
    assert crypto_model_type('USDC-USD') == 'Stablecoin'
    assert crypto_model_type('PEPE-USD') == 'Speculative Token'

def test_tokenomics_penalizes_large_fdv_gap():
    good={'FDV_to_MCap':1.05,'Circulating_%_of_Total':95,'24h_Volume_$':1e9,'Market_Cap_$':10e9}
    bad={'FDV_to_MCap':4.0,'Circulating_%_of_Total':20,'24h_Volume_$':1e6,'Market_Cap_$':10e9}
    assert _score_tokenomics(good) > _score_tokenomics(bad)
