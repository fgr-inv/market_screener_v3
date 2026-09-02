from core.data_budget import decide, write_snapshot, shared_fundamental_snapshot
from core.fundamental_agent import analyze_fundamental
import core.data_budget as db
import core.fundamental_agent as fa

def test_shared_snapshot_calls_loader_once(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'ROOT',tmp_path); monkeypatch.setattr(db,'FUND_DIR',tmp_path/'fundamentals')
    calls={'n':0}
    def loader(t): calls['n']+=1; return {'Fundamentals_Available':True,'Revenue_Growth':.2,'Fundamentals_Provider_Status':{'X':'OK'}}
    a,d1,r1=shared_fundamental_snapshot('ABC',loader); b,d2,r2=shared_fundamental_snapshot('ABC',loader)
    assert calls['n']==1 and r1 is True and r2 is False and d2.action=='CACHE'

def test_force_refresh_spends_budget(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'ROOT',tmp_path); monkeypatch.setattr(db,'FUND_DIR',tmp_path/'fundamentals')
    calls={'n':0}
    def loader(t): calls['n']+=1; return {'Fundamentals_Available':True,'Fundamentals_Provider_Status':{}}
    shared_fundamental_snapshot('ABC',loader); shared_fundamental_snapshot('ABC',loader,force=True)
    assert calls['n']==2

def test_fundamental_agent_contract_without_live_network(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'ROOT',tmp_path); monkeypatch.setattr(db,'FUND_DIR',tmp_path/'fundamentals')
    fake={'Fundamentals_Available':True,'Fundamental_Score':76,'Revenue_Growth':.2,'Earnings_Growth':.25,'Profit_Margin':.18,'ROE':.22,'FCF':100,'Forward_PE':30,'Fundamentals_Source':'TEST','Fundamentals_Provider_Status':{'TEST':'OK'}}
    monkeypatch.setattr(fa,'get_fundamentals',lambda t:fake.copy()); monkeypatch.setattr(fa,'get_market_valuation_snapshot',lambda t:{'Valuation_Market_Overlay_Available':False})
    r=analyze_fundamental('ABC')
    assert r.agent=='Fundamental & Catalyst' and r.state=='IMPROVING'
    assert r.metadata['provider_refresh_performed'] is True
    assert 'Never place' in r.metadata['approval_boundary']
