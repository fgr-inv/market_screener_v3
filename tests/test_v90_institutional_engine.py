import numpy as np
import pandas as pd

from core.institutional_valuation import reverse_dcf_growth, dcf_scenarios, valuation_workstation
from core.financial_forensics import financial_forensics
from core.macro_regime_engine import macro_regime
from core.portfolio_intelligence import single_asset_portfolio_fit, institutional_position_size
from core.institutional_thesis import build_thesis


def test_reverse_dcf_and_scenarios_work_with_observed_fcf():
    f={'FCF':10,'Enterprise_Value':180,'Market_Cap':160,'Total_Debt':40,'Total_Cash':20,'Revenue_Growth':.12,'Earnings_Growth':.15}
    r=reverse_dcf_growth(f)
    assert r['available']
    assert -30 <= r['Implied_FCF_Growth_%'] <= 80
    d=dcf_scenarios(f,'saas')
    assert d['available']
    assert len(d['Scenarios'])==3
    assert set(d['Scenarios']['Scenario'])=={'Bear','Base','Bull'}


def test_reverse_dcf_refuses_missing_or_negative_fcf():
    assert not reverse_dcf_growth({'FCF':-1,'Enterprise_Value':100})['available']
    assert not dcf_scenarios({'FCF':np.nan,'Market_Cap':100})['available']


def test_financial_forensics_uses_cash_flow_and_balance_sheet():
    f={'Net_Income_SEC':100,'Operating_Cashflow':130,'FCF':90,'Revenue':500,'SBC':10,'Inventory_to_Revenue':.10,
       'Total_Debt':100,'Total_Cash':80,'EBITDA':120,'Interest_Expense':10,'Current_Ratio':1.8,'Quick_Ratio':1.2,'ROIC':.18,'Payout_Ratio':.3}
    x=financial_forensics(f)
    assert x['Earnings_Quality_Score']>50
    assert x['Financial_Resilience_Score']>50
    assert x['Capital_Allocation_Score']>50
    assert x['Forensics_Coverage_%']>70


def test_macro_regimes_are_explicit():
    assert macro_regime({'Slow_Growth':65,'Slow_Inflation_Pressure':40})['Macro_Regime']=='GOLDILOCKS'
    assert macro_regime({'Slow_Growth':65,'Slow_Inflation_Pressure':70})['Macro_Regime']=='REFLATION'
    assert macro_regime({'Slow_Growth':35,'Slow_Inflation_Pressure':70})['Macro_Regime']=='STAGFLATION'


def test_portfolio_fit_and_sizing():
    idx=pd.date_range('2025-01-01',periods=200,freq='B')
    a=pd.DataFrame({'Close':100*np.cumprod(1+np.sin(np.arange(200)/9)*.002+.0005)},index=idx)
    b=pd.DataFrame({'Close':100*np.cumprod(1+np.sin(np.arange(200)/11)*.001+.0003)},index=idx)
    fit=single_asset_portfolio_fit('AAA',{'AAA':a,'SPY':b},pd.DataFrame())
    assert 0<=fit['Portfolio_Fit_Score']<=100
    s=institutional_position_size(100000,100,92,80,30,75,15)
    assert 0 <= s['position_pct'] <= 15
    assert s['risk_budget_pct']>0


def test_thesis_does_not_claim_mispricing_without_evidence():
    t=build_thesis('AAA',{'Trend_Score':50,'Invalidation':'< 90','Action':'WAIT'})
    assert t['Invalidation']=='< 90'
    assert t['What_Market_May_Be_Missing']
