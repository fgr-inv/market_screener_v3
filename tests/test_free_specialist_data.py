import numpy as np
from core.free_specialist_data import _latest_fact
from core.data_coverage import equity_data_coverage

def test_latest_sec_fact_prefers_latest_end():
    facts={'InventoryNet':{'units':{'USD':[{'end':'2025-01-01','filed':'2025-02-01','val':10},{'end':'2026-01-01','filed':'2026-02-01','val':12}]}}}
    v,tag=_latest_fact(facts,['InventoryNet'])
    assert v==12 and tag=='InventoryNet'

def test_sec_specialist_metric_can_raise_semiconductor_coverage():
    base={'Market_Cap':1,'Revenue_Growth':.1,'Earnings_Growth':.1,'Gross_Margin':.5,'Operating_Margin':.2,'ROE':.2,'FCF':1,'Total_Debt':1,'Total_Cash':1,'Forward_PE':20,'Price_to_Book':3,'EV_EBITDA':15}
    a=equity_data_coverage(base,'Technology','Semiconductors')
    base['Capex']=100
    b=equity_data_coverage(base,'Technology','Semiconductors')
    assert b['Specialist_Data_Coverage_%'] > a['Specialist_Data_Coverage_%']
