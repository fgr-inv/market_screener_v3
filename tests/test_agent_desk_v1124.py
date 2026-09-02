import pandas as pd
import numpy as np
from core.agent_contracts import AgentResult,Evidence,DataStatus,VerificationStatus
from core.technical_agent import analyze_technical
from core.verification_agent import verify_result
from core.cio_agent import build_cio_brief

def _history(n=260):
    idx=pd.date_range('2025-01-01',periods=n,freq='B'); base=np.linspace(100,180,n)+np.sin(np.arange(n)/7)*2
    df=pd.DataFrame(index=idx)
    df['Close']=base; df['Open']=base-.3; df['High']=base+1; df['Low']=base-1; df['Volume']=1_000_000+np.arange(n)*100
    df['Vol20']=df['Volume'].rolling(20).mean(); tr=df['High']-df['Low']; df['ATR_%']=tr.rolling(14).mean()/df['Close']*100
    delta=df['Close'].diff(); up=delta.clip(lower=0).rolling(14).mean(); down=(-delta.clip(upper=0)).rolling(14).mean(); rs=up/down.replace(0,np.nan); df['RSI14']=100-(100/(1+rs))
    return df

def test_technical_agent_contract_and_no_execution():
    r=analyze_technical('TEST',_history())
    assert r.agent=='Technical Signal'; assert r.state in {'SETUP','WATCH','NO_SETUP','BROKEN_SETUP'}
    assert len(r.evidence)>=4; assert 'Never place' in r.metadata['approval_boundary']

def test_missing_history_is_explicit_unavailable():
    r=analyze_technical('TEST',pd.DataFrame())
    assert r.evidence[0].status==DataStatus.UNAVAILABLE
    assert r.confidence==0

def test_verifier_caps_untrusted_result():
    r=AgentResult('x','1','s','1','ABC','SETUP',.9,'x',[Evidence('x',1,'src',status=DataStatus.STALE)])
    v=verify_result(r)
    assert v.verification_status==VerificationStatus.STALE_DATA
    assert v.confidence<=.49

def test_cio_only_promotes_verified_work():
    good=verify_result(analyze_technical('GOOD',_history()))
    bad=AgentResult('x','1','s','1','BAD','SETUP',.99,'x',[Evidence('x',None,'',status=DataStatus.FAILED)])
    bad=verify_result(bad)
    b=build_cio_brief([good,bad])
    assert all(x['subject']!='BAD' for x in b['decisions'])
    assert any(x['subject']=='BAD' for x in b['blocked_or_low_trust'])
    assert 'User approval' in b['approval_boundary']
