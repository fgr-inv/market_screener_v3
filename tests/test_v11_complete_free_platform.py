import pandas as pd
from core.professional_complete_v11 import fundamental_acceleration,forensic_v2,futures_curve_metrics,signal_disagreement,correlation_regimes,source_reconcile
from core.model_validation_v11 import probability_metrics,walk_forward_summary
from core.free_sources_v11 import free_source_catalog,sec_quarterly_dataset_url

def test_fundamental_acceleration():
    df=pd.DataFrame({'Revenue':[100,110,125,150],'EPS':[1,1.1,1.3,1.8],'FCF':[10,12,15,20]})
    out=fundamental_acceleration(df); assert 'Fundamental_Momentum_Score' in out

def test_forensics_missing_aware():
    o=forensic_v2({'Revenue':100,'NetIncome':10,'OCF':12,'SBC':2,'FCF':8});assert o['Coverage_%']>0 and o['Financial_Forensics_Score']>50

def test_curve():
    o=futures_curve_metrics(pd.DataFrame({'price':[100,98,97]}));assert o['Curve_Regime']=='BACKWARDATION'

def test_signal_conflict():
    o=signal_disagreement({'Fundamental':90,'Technical':85,'Positioning':20});assert o['Conflict_Count']>=1

def test_probability_metrics():
    o=probability_metrics([.8,.2,.7],[1,0,1]);assert o['Brier_Score']<.2

def test_walkforward():
    df=pd.DataFrame({'Opportunity':[55,56,57,58,59,75,76,77,78,79],'Fwd_63d_%':[1,2,1,-1,2,4,5,3,6,2]}); assert not walk_forward_summary(df,min_n=3).empty

def test_sources_catalog_and_sec_url():
    assert len(free_source_catalog())>=15; assert '2026q1' in sec_quarterly_dataset_url('form13f',2026,1)

def test_reconcile_conflict():
    o=source_reconcile('Revenue',[{'source':'SEC','value':100},{'source':'Fallback','value':80}],2); assert o['Conflict']
