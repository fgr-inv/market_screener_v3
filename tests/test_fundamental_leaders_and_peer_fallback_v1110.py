import numpy as np
import pandas as pd

from core.opportunity import fundamental_leader_score, fundamental_opportunity_score
from core.professional_research_engine import peer_benchmark_snapshot


def test_fundamental_leader_and_opportunity_are_distinct_scores():
    expensive_quality = {
        'Quality_Score': 92,
        'Valuation_Score': 30,
        'Revision_Score': 70,
        'Financial_Resilience_Score': 90,
        'Earnings_Quality_Score': 88,
        'Capital_Allocation_Score': 85,
        'Management_Execution_Score': 80,
    }
    leader = fundamental_leader_score(expensive_quality)
    opportunity = fundamental_opportunity_score(expensive_quality)
    assert leader > opportunity
    assert leader >= 80


def test_peer_rank_falls_back_to_sector_when_exact_model_group_is_too_small():
    universe = pd.DataFrame([
        {'Ticker':'A','Equity_Model_Key':'gpu','Industry':'Semiconductors','Sector':'Technology','Quality_Score':90,'Valuation_Score':50,'Revision_Score':80,'RS_Percentile':90},
        {'Ticker':'B','Equity_Model_Key':'software','Industry':'Software','Sector':'Technology','Quality_Score':60,'Valuation_Score':70,'Revision_Score':55,'RS_Percentile':60},
        {'Ticker':'C','Equity_Model_Key':'internet','Industry':'Internet','Sector':'Technology','Quality_Score':70,'Valuation_Score':65,'Revision_Score':65,'RS_Percentile':70},
        {'Ticker':'D','Equity_Model_Key':'bank','Industry':'Banks','Sector':'Financials','Quality_Score':75,'Valuation_Score':80,'Revision_Score':60,'RS_Percentile':50},
    ])
    row = {'Ticker':'X','Equity_Model_Key':'gpu','Industry':'AI Accelerators','Sector':'Technology','Quality_Score':80,'Valuation_Score':60,'Revision_Score':70,'RS_Percentile':80}
    out = peer_benchmark_snapshot(row, universe)
    assert out['Peer_Rank_Source'] == 'SECTOR'
    assert out['Peer_Rank_Peer_Count'] == 3
    assert np.isfinite(out['Peer_Rank_Score'])


def test_peer_rank_falls_back_to_universe_if_sector_is_too_small():
    universe = pd.DataFrame([
        {'Ticker':'A','Equity_Model_Key':'gpu','Industry':'Semiconductors','Sector':'Technology','Quality_Score':90,'Valuation_Score':50,'Revision_Score':80,'RS_Percentile':90},
        {'Ticker':'B','Equity_Model_Key':'bank','Industry':'Banks','Sector':'Financials','Quality_Score':60,'Valuation_Score':70,'Revision_Score':55,'RS_Percentile':60},
        {'Ticker':'C','Equity_Model_Key':'insurance','Industry':'Insurance','Sector':'Financials','Quality_Score':70,'Valuation_Score':65,'Revision_Score':65,'RS_Percentile':70},
    ])
    row = {'Ticker':'X','Equity_Model_Key':'reits','Industry':'Office REIT','Sector':'Real Estate','Quality_Score':80,'Valuation_Score':60,'Revision_Score':70,'RS_Percentile':80}
    out = peer_benchmark_snapshot(row, universe)
    assert out['Peer_Rank_Source'] == 'UNIVERSE'
    assert out['Peer_Rank_Peer_Count'] == 3
    assert np.isfinite(out['Peer_Rank_Score'])
