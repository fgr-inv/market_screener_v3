import json
import time
from pathlib import Path

import core.screener_enrichment as se


def test_deep_bundle_uses_disk_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(se, 'CACHE_DIR', tmp_path)
    calls={'f':0,'a':0,'e':0}
    def f(t): calls['f']+=1; return {'Fundamentals_Available':True,'Fundamental_Score':72}
    def a(t): calls['a']+=1; return {'EPS_Revision_Score':61,'Revision_Direction':'IMPROVING','Next_Earnings':'N/D'}
    def e(t): calls['e']+=1; return {'risk':'NORMAL','days_to_earnings':20}
    monkeypatch.setattr(se,'get_fundamentals',f)
    monkeypatch.setattr(se,'get_analyst_snapshot',a)
    monkeypatch.setattr(se,'earnings_event',e)
    one=se.fetch_deep_bundle('AAA')
    two=se.fetch_deep_bundle('AAA')
    assert one['fundamentals']['Fundamental_Score']==72
    assert calls=={'f':1,'a':1,'e':1}
    assert set(two['Cache_Hits']) >= {'fundamentals','analyst','event'}


def test_event_is_deduplicated_when_analyst_has_date(monkeypatch, tmp_path):
    monkeypatch.setattr(se, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(se,'get_fundamentals',lambda t:{'Fundamentals_Available':True})
    monkeypatch.setattr(se,'get_analyst_snapshot',lambda t:{'EPS_Revision_Score':55,'Next_Earnings':'2099-01-10'})
    def should_not_run(t):
        raise AssertionError('duplicate earnings call')
    monkeypatch.setattr(se,'earnings_event',should_not_run)
    out=se.fetch_deep_bundle('BBB', force_refresh=True)
    assert out['Event_Source']=='analyst_snapshot'
    assert out['event']['risk'] in {'NORMAL','ELEVATED','HIGH'}


def test_parallel_bundle_fetch_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(se, 'CACHE_DIR', tmp_path)
    def fake(t, force_refresh=False):
        time.sleep(.01)
        return {'Ticker':t,'Cache_Hits':[],'Fetch_Issues':[],'Fetch_Seconds':.01}
    monkeypatch.setattr(se,'fetch_deep_bundle',fake)
    out,diag=se.fetch_deep_bundles(['A','B','C','D'],max_workers=99)
    assert set(out)=={'A','B','C','D'}
    assert diag['workers']==4
    assert diag['tickers']==4
