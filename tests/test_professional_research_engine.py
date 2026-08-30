import pandas as pd
from core.professional_research_engine import revision_research_snapshot, peer_benchmark_snapshot, scenario_valuation, catalyst_map


def test_revision_snapshot_separates_signal_and_confidence():
    x=revision_research_snapshot({'EPS_Revision_Score':75,'Revision_Direction':'IMPROVING','Price_Target_Upside_%':20,'Analyst_Count':10,'Earnings_Surprise_%':5},{'days_to_earnings':12,'risk':'NORMAL'})
    assert x['Revision_Momentum']=='STRONG POSITIVE'
    assert x['Revision_Research_Confidence_%']==100


def test_peer_benchmark_same_model_only():
    u=pd.DataFrame([
        {'Ticker':'A','Equity_Model_Key':'memory','Quality_Score':90,'Valuation_Score':60,'Revision_Score':80,'RS_Percentile':90},
        {'Ticker':'B','Equity_Model_Key':'memory','Quality_Score':60,'Valuation_Score':40,'Revision_Score':50,'RS_Percentile':50},
        {'Ticker':'C','Equity_Model_Key':'saas','Quality_Score':99,'Valuation_Score':99,'Revision_Score':99,'RS_Percentile':99},
    ])
    r={'Ticker':'X','Equity_Model_Key':'memory','Quality_Score':80,'Valuation_Score':50,'Revision_Score':70,'RS_Percentile':70}
    p=peer_benchmark_snapshot(r,u)
    assert p['Peer_Count']==2
    assert p['Peer_Rank_Score']>=50


def test_scenarios_have_probabilities_and_order():
    r={'Price':100,'Invalidation':'< $90.00','Target':'$120.00','Quality_Score':80,'Revision_Score':70,'Trend_Score':80,'Macro_Fit':65,'Risk_Score':70,'Event_Risk':'NORMAL'}
    s=scenario_valuation(r,analyst={'Price_Target_Upside_%':25})
    assert s['Bear_Price'] < s['Base_Price'] < s['Bull_Price']
    assert round(s['Scenarios']['Probability_%'].sum(),5)==100


def test_catalyst_map_preserves_structural_model():
    c=catalyst_map({'Key_Catalysts':['HBM pricing'],'Key_Risks':['oversupply']},{},{'days_to_earnings':5,'next_earnings':'2026-09-01','risk':'ELEVATED'})
    assert 'HBM pricing' in c['Structural_Catalysts']
    assert c['Dated_Catalysts'][0]['Type']=='EARNINGS'
