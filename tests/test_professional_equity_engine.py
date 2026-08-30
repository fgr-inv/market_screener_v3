import numpy as np
from core.professional_equity_engine import (
    classify_equity_subindustry, professional_equity_snapshot,
    professional_valuation_score, add_professional_peer_valuation_scores,
)
import pandas as pd


def sample_fundamentals():
    return {
        'Revenue_Growth':.18,'Earnings_Growth':.22,'Operating_Margin':.26,
        'Profit_Margin':.20,'ROE':.24,'Debt_Equity':55,'FCF':8,'Market_Cap':100,
        'Operating_Cashflow':10,'Current_Ratio':1.5,'Quick_Ratio':1.2,
        'Forward_PE':25,'EV_EBITDA':16,'Price_to_Book':4,'Price_to_Sales':5,
        'EV_Revenue':5,'SBC_to_Revenue':.05,'Inventory_to_Revenue':.12,
    }


def test_ticker_specific_subindustry_models():
    assert classify_equity_subindustry('Technology','Semiconductors','MU').key=='memory'
    assert classify_equity_subindustry('Materials','Copper','FCX').key=='copper_miner'
    assert classify_equity_subindustry('Real Estate','REIT - Industrial','PLD').key=='industrial_reit'
    assert classify_equity_subindustry('Financials','Credit Services','V').key=='payments'
    assert classify_equity_subindustry('Health Care','Medical Devices','ISRG').key=='medtech'


def test_professional_snapshot_separates_quality_and_valuation():
    r=professional_equity_snapshot(sample_fundamentals(),'Technology','Software - Application','CRM')
    assert r['Equity_Model_Key']=='saas'
    assert 0 <= r['Quality_Score'] <= 100
    assert 0 <= r['Valuation_Score'] <= 100
    assert 'ARR' in r['Critical_KPIs']
    assert 'ARR' in r['Missing_Specialist_KPIs']
    assert r['Fundamental_Coverage_%'] > 0


def test_biotech_valuation_is_intentionally_sparse_without_rnpv():
    r=professional_valuation_score(sample_fundamentals(),'Health Care','Biotechnology','XYZ')
    assert r['Equity_Model_Key']=='biotech'
    assert r['Valuation_Coverage_%'] < 100
    assert 'rNPV' in ' '.join(r['Preferred_Valuation_Methods'])


def test_peer_valuation_uses_subindustry_not_whole_sector():
    df=pd.DataFrame([
        {'Ticker':'A','Sector':'Technology','Industry':'Software - Application','Equity_Model_Key':'saas','Forward_PE':20,'EV_EBITDA':12,'Price_to_Sales':4,'FCF_Yield':.06,'Valuation_Score':70},
        {'Ticker':'B','Sector':'Technology','Industry':'Software - Application','Equity_Model_Key':'saas','Forward_PE':30,'EV_EBITDA':18,'Price_to_Sales':7,'FCF_Yield':.04,'Valuation_Score':55},
        {'Ticker':'C','Sector':'Technology','Industry':'Software - Application','Equity_Model_Key':'saas','Forward_PE':45,'EV_EBITDA':25,'Price_to_Sales':11,'FCF_Yield':.02,'Valuation_Score':40},
        {'Ticker':'D','Sector':'Technology','Industry':'Semiconductors','Equity_Model_Key':'memory','Forward_PE':10,'EV_EBITDA':8,'Price_to_Sales':2,'FCF_Yield':.08,'Valuation_Score':80},
    ])
    out=add_professional_peer_valuation_scores(df)
    a=out[out.Ticker=='A'].iloc[0]
    c=out[out.Ticker=='C'].iloc[0]
    assert a['Peer_Valuation_Score'] > c['Peer_Valuation_Score']
    assert pd.isna(out[out.Ticker=='D']['Peer_Valuation_Score'].iloc[0])
