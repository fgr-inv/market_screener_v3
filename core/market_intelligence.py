from __future__ import annotations
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np
import pandas as pd

from core.config import SECTOR_ETFS
from core.indicators import enrich_indicators
from core.scoring import analyze_symbol, sector_strength_entry
from core.macro import sector_macro_score
from core.macro_regime_engine import macro_regime
from core.utils import clamp

ROOT = Path(__file__).resolve().parents[1]

# Small representative baskets keep the live fundamental overlay useful without
# turning Market Intelligence into a 500-symbol fundamental scan.  They are a
# transparent proxy only; the full Fundamental/Combined screener remains the
# authoritative constituent-level research workflow.
SECTOR_REPRESENTATIVES = {
    'Technology': ['MSFT','NVDA','AAPL','AVGO','ORCL'],
    'Financials': ['BRK-B','JPM','V','MA','BAC'],
    'Health Care': ['LLY','JNJ','ABBV','UNH','ISRG'],
    'Industrials': ['GE','CAT','RTX','UBER','HON'],
    'Utilities': ['NEE','SO','DUK','CEG','AEP'],
    'Energy': ['XOM','CVX','COP','SLB','EOG'],
    'Materials': ['LIN','SHW','FCX','NEM','APD'],
    'Real Estate': ['WELL','PLD','EQIX','AMT','DLR'],
    'Consumer Discretionary': ['AMZN','TSLA','HD','MCD','BKNG'],
    'Consumer Staples': ['WMT','COST','KO','PG','PM'],
    'Communication Services': ['META','GOOGL','NFLX','TMUS','DIS'],
}


def _num(x, default=np.nan):
    try:
        v=float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def _ret(raw, n):
    if raw is None or raw.empty or len(raw) <= n: return np.nan
    c=pd.to_numeric(raw['Close'],errors='coerce').dropna()
    return (float(c.iloc[-1]/c.iloc[-(n+1)]-1)*100) if len(c)>n else np.nan


def _trend_score(raw):
    if raw is None or raw.empty: return np.nan
    h=enrich_indicators(raw); z=h.iloc[-1]; p=_num(z.get('Close'))
    vals=[]
    for col,w in [('EMA20',15),('SMA50',25),('EMA62',20),('EMA79',15),('SMA200',25)]:
        ma=_num(z.get(col));
        if pd.notna(p) and pd.notna(ma): vals.append((w, 100 if p>ma else 0))
    return round(sum(w*s for w,s in vals)/sum(w for w,_ in vals),1) if vals else np.nan


def market_state(pm:dict, macro:dict|None=None):
    macro=macro or {}; spy=pm.get('SPY'); qqq=pm.get('QQQ'); rsp=pm.get('RSP'); iwm=pm.get('IWM')
    vix=pm.get('^VIX'); hyg=pm.get('HYG'); ief=pm.get('IEF')
    trend_vals=[_trend_score(x) for x in [spy,qqq] if x is not None]
    trend_vals=[x for x in trend_vals if pd.notna(x)]
    trend=float(np.mean(trend_vals)) if trend_vals else np.nan
    breadth=[]
    for raw in [spy,qqq,rsp,iwm]:
        s=_trend_score(raw)
        if pd.notna(s): breadth.append(s)
    breadth_score=np.mean(breadth) if breadth else np.nan
    vix_level=_num(vix['Close'].dropna().iloc[-1]) if vix is not None and not vix.empty else np.nan
    vol=85 if pd.notna(vix_level) and vix_level<16 else 70 if pd.notna(vix_level) and vix_level<20 else 50 if pd.notna(vix_level) and vix_level<25 else 25 if pd.notna(vix_level) else np.nan
    credit_delta=np.nan
    if hyg is not None and ief is not None and not hyg.empty and not ief.empty:
        x=pd.concat([hyg['Close'],ief['Close']],axis=1).dropna();
        if len(x)>21: credit_delta=float((x.iloc[-1,0]/x.iloc[-1,1])/(x.iloc[-21,0]/x.iloc[-21,1])-1)*100
    credit=70 if pd.notna(credit_delta) and credit_delta>0 else 45 if pd.notna(credit_delta) else _num(macro.get('Credit'),np.nan)
    mr=macro_regime(macro)
    liquidity=_num(mr.get('Global_Liquidity_Proxy_Score'),50)
    vals=[x for x in [trend,breadth_score,vol,credit,liquidity] if pd.notna(x)]
    score=round(float(np.mean(vals)),1) if vals else 50
    regime='RISK-ON' if score>=65 else 'RISK-OFF' if score<45 else 'NEUTRAL'
    return {'Market_Regime':regime,'Market_State_Score':score,'Trend_Score':trend,'Breadth_Proxy_Score':breadth_score,
            'Volatility_Score':vol,'Credit_Score':credit,'Liquidity_Score':liquidity,'VIX':vix_level,
            'Macro_Regime':mr.get('Macro_Regime','UNKNOWN'),'Credit_Ratio_20d_%':credit_delta}


def breadth_dashboard(pm:dict):
    rows=[]
    for name,sym in [('S&P 500','SPY'),('Nasdaq 100','QQQ'),('Equal Weight','RSP'),('Small Caps','IWM')]:
        raw=pm.get(sym)
        rows.append({'Market':name,'Ticker':sym,'Trend Score':_trend_score(raw),'1M %':round(_ret(raw,21),2),'3M %':round(_ret(raw,63),2),'6M %':round(_ret(raw,126),2)})
    def rel(a,b,n=63):
        ra,rb=pm.get(a),pm.get(b)
        aa,bb=_ret(ra,n),_ret(rb,n)
        return aa-bb if pd.notna(aa) and pd.notna(bb) else np.nan
    return pd.DataFrame(rows), {'RSP_vs_SPY_3M_pp':rel('RSP','SPY'),'IWM_vs_SPY_3M_pp':rel('IWM','SPY'),'QQQ_vs_SPY_3M_pp':rel('QQQ','SPY')}


def _snapshot_sector_evidence(screener:pd.DataFrame|None):
    """Aggregate genuine sector evidence already produced by a deep scan.

    Technical-only snapshots often contain no fundamental fields.  We never
    convert that absence into a neutral 50.  Revision rows marked N/D are also
    excluded because older screener paths may use 50 as an availability fallback.
    """
    out={}
    if not isinstance(screener,pd.DataFrame) or screener.empty or 'Sector' not in screener:
        return out
    for sector,g in screener.groupby(screener['Sector'].astype(str)):
        rec={'revision':np.nan,'valuation':np.nan,'revision_n':0,'valuation_n':0}
        rev_col=next((c for c in ['EPS_Revision_Score','Revision_Score'] if c in g.columns),None)
        if rev_col:
            rv=pd.to_numeric(g[rev_col],errors='coerce')
            if 'Revision_Direction' in g.columns:
                direction=g['Revision_Direction'].astype(str).str.upper()
                rv=rv.where(~direction.isin(['N/D','ND','NONE','NAN','']))
            rv=rv.dropna()
            if len(rv):
                rec['revision']=float(rv.median()); rec['revision_n']=int(len(rv))
        val_col=next((c for c in ['Valuation_Score','PE_Sector_Percentile'] if c in g.columns),None)
        if val_col:
            vv=pd.to_numeric(g[val_col],errors='coerce').dropna()
            if len(vv):
                rec['valuation']=float(vv.median()); rec['valuation_n']=int(len(vv))
        out[sector]=rec
    return out


def _live_representative_evidence():
    """Fetch a bounded, cached representative-company overlay.

    Revisions require actual analyst/revision evidence.  Valuation uses forward
    P/E where available and is converted into an *across-sector* percentile only
    after sector medians are calculated.  It is deliberately not labelled as a
    historical percentile.
    """
    try:
        from core.analyst_data import get_analyst_snapshot
        from core.fundamentals import get_market_valuation_snapshot
    except Exception:
        return {}

    jobs=[(sector,t) for sector,tickers in SECTOR_REPRESENTATIVES.items() for t in tickers]
    raw={sector:[] for sector in SECTOR_REPRESENTATIVES}

    def fetch(item):
        sector,ticker=item
        a={}; v={}
        try: a=get_analyst_snapshot(ticker) or {}
        except Exception: pass
        try: v=get_market_valuation_snapshot(ticker) or {}
        except Exception: pass
        detail=a.get('Revision_Detail')
        has_detail=isinstance(detail,pd.DataFrame) and not detail.empty
        has_revision_evidence=(has_detail or pd.notna(_num(a.get('Revision_Velocity_%'))) or pd.notna(_num(a.get('Analyst_Count'))))
        rev=_num(a.get('EPS_Revision_Score')) if has_revision_evidence else np.nan
        pe=_num(v.get('Forward_PE'))
        if pd.notna(pe) and pe<=0: pe=np.nan
        return sector,ticker,rev,pe

    # Provider calls are cached at their own TTLs; bounded parallelism avoids a
    # 55-request serial page load while remaining conservative with free sources.
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs=[ex.submit(fetch,j) for j in jobs]
        for fut in as_completed(futs):
            try:
                sector,ticker,rev,pe=fut.result()
                raw[sector].append((ticker,rev,pe))
            except Exception:
                continue

    sector_pe={}
    out={}
    for sector,items in raw.items():
        revs=[r for _,r,_ in items if pd.notna(r)]
        pes=[p for _,_,p in items if pd.notna(p)]
        med_pe=float(np.median(pes)) if pes else np.nan
        sector_pe[sector]=med_pe
        out[sector]={
            'revision':float(np.median(revs)) if revs else np.nan,
            'revision_n':len(revs),
            'forward_pe_median':med_pe,
            'valuation_n':len(pes),
        }

    valid={k:v for k,v in sector_pe.items() if pd.notna(v)}
    if valid:
        s=pd.Series(valid,dtype=float)
        # Lower forward P/E => higher valuation-attractiveness score.
        pct=(1.0-s.rank(method='average',pct=True)+1.0/len(s))*100
        pct=pct.clip(0,100)
        for sector,val in pct.items(): out[sector]['valuation']=float(round(val,1))
    return out


def sector_fundamental_overlay(screener:pd.DataFrame|None=None, live_fallback=True):
    snap=_snapshot_sector_evidence(screener)
    need_live=live_fallback and any(
        pd.isna(_num(snap.get(s,{}).get('revision'))) or pd.isna(_num(snap.get(s,{}).get('valuation')))
        for s in SECTOR_ETFS
    )
    live=_live_representative_evidence() if need_live else {}
    out={}
    for sector in SECTOR_ETFS:
        ss=snap.get(sector,{}) ; ll=live.get(sector,{})
        sr=_num(ss.get('revision')); sv=_num(ss.get('valuation'))
        lr=_num(ll.get('revision')); lv=_num(ll.get('valuation'))
        rev=sr if pd.notna(sr) else lr
        val=sv if pd.notna(sv) else lv
        out[sector]={
            'revision':rev,'valuation':val,
            'revision_source':'DEEP SCREENER' if pd.notna(sr) else ('TOP HOLDINGS PROXY' if pd.notna(lr) else 'N/D'),
            'valuation_source':'DEEP SCREENER' if pd.notna(sv) else ('FWD P/E CROSS-SECTOR PROXY' if pd.notna(lv) else 'N/D'),
            'revision_n':int(ss.get('revision_n',0) or 0) if pd.notna(sr) else int(ll.get('revision_n',0) or 0),
            'valuation_n':int(ss.get('valuation_n',0) or 0) if pd.notna(sv) else int(ll.get('valuation_n',0) or 0),
            'forward_pe_median':_num(ll.get('forward_pe_median')),
        }
    return out


def sector_rotation_table(pm:dict, macro:dict|None=None, screener:pd.DataFrame|None=None, live_fundamentals=True):
    macro=macro or {}; spy=pm.get('SPY'); rows=[]
    overlay=sector_fundamental_overlay(screener,live_fallback=live_fundamentals)
    for sector,etf in SECTOR_ETFS.items():
        raw=pm.get(etf)
        if raw is None or raw.empty: continue
        try:
            r=analyze_symbol(etf,enrich_indicators(raw),spy,sector); strength,entry,status=sector_strength_entry(r); mf=sector_macro_score(sector,macro)
            ev=overlay.get(sector,{})
            rev=_num(ev.get('revision')); val=_num(ev.get('valuation'))
            components=[(.30,strength),(.20,entry),(.20,mf),(.15,rev),(.15,val)]
            avail=[(w,_num(v)) for w,v in components if pd.notna(_num(v))]
            overall=round(sum(w*v for w,v in avail)/sum(w for w,_ in avail)) if avail else np.nan
            rows.append({'Sector':sector,'ETF':etf,'Opportunity':overall,'Strength':strength,'Entry':entry,'Macro Fit':mf,
                         'Revisions':round(rev,1) if pd.notna(rev) else np.nan,
                         'Relative Valuation':round(val,1) if pd.notna(val) else np.nan,
                         'Revision Coverage':ev.get('revision_n',0),'Valuation Coverage':ev.get('valuation_n',0),
                         'Revisions Source':ev.get('revision_source','N/D'),'Valuation Source':ev.get('valuation_source','N/D'),
                         'Median Forward P/E':round(_num(ev.get('forward_pe_median')),2) if pd.notna(_num(ev.get('forward_pe_median'))) else np.nan,
                         '1M %':round(_ret(raw,21),2),'3M %':round(_ret(raw,63),2),
                         '6M %':round(_ret(raw,126),2),'RS vs SPY 3M pp':round(_ret(raw,63)-_ret(spy,63),2),'Status':status})
        except Exception: continue
    return pd.DataFrame(rows).sort_values(['Opportunity','Strength'],ascending=False,na_position='last') if rows else pd.DataFrame()


def cross_asset_table(pm:dict):
    mapping={'S&P 500':'SPY','Nasdaq 100':'QQQ','Small Caps':'IWM','Equal Weight':'RSP','Long Treasuries':'TLT','High Yield':'HYG','Gold':'GLD','US Dollar':'UUP','Oil':'CL=F','Copper':'HG=F','Bitcoin':'BTC-USD'}
    rows=[]
    for name,sym in mapping.items():
        raw=pm.get(sym)
        if raw is None or raw.empty: continue
        rows.append({'Asset':name,'Ticker':sym,'Trend Score':_trend_score(raw),'1W %':round(_ret(raw,5),2),'1M %':round(_ret(raw,21),2),'3M %':round(_ret(raw,63),2),'6M %':round(_ret(raw,126),2)})
    return pd.DataFrame(rows).sort_values('3M %',ascending=False,na_position='last')


def macro_sensitivity_table():
    data={
      'Technology':(1,-1,-1,1,1),'Financials':(0,0,1,1,1),'Health Care':(1,0,0,0,0),'Industrials':(1,-1,0,1,1),
      'Utilities':(2,0,-1,0,0),'Energy':(0,2,1,1,1),'Materials':(1,1,-1,1,1),'Real Estate':(2,0,-1,1,-1),
      'Consumer Discretionary':(2,-1,-1,2,1),'Consumer Staples':(1,0,0,-1,0),'Communication Services':(1,-1,-1,1,1)}
    return pd.DataFrame([{'Sector':k,'Rates ↓':v[0],'Inflation ↑':v[1],'USD ↑':v[2],'Growth ↑':v[3],'Oil ↑':v[4]} for k,v in data.items()])


def load_latest_screener():
    p=ROOT/'data'/'snapshots'/'latest_screener.parquet'
    try: return pd.read_parquet(p) if p.exists() else pd.DataFrame()
    except Exception: return pd.DataFrame()


def opportunity_radar(df:pd.DataFrame, limit=25):
    if df is None or df.empty: return pd.DataFrame()
    x=df.copy(); candidates={
      'Quality':['Quality_Score'],'Growth':['Growth_Score','Growth'],'Valuation':['Valuation_Score','PE_Sector_Percentile'],
      'Technical':['Technical_Score','Technical'],'Entry':['Entry_Score','Entry'],'Revisions':['EPS_Revision_Score','Revision_Score'],
      'Financial Resilience':['Financial_Resilience','Financial_Resilience_Score']}
    found={}
    for label,cols in candidates.items():
        for c in cols:
            if c in x: found[label]=c; break
    weights={'Quality':.22,'Growth':.14,'Valuation':.18,'Technical':.14,'Entry':.14,'Revisions':.10,'Financial Resilience':.08}
    score=pd.Series(0.0,index=x.index); denom=pd.Series(0.0,index=x.index)
    for label,c in found.items():
        v=pd.to_numeric(x[c],errors='coerce').clip(0,100); w=weights[label]; score=score.add(v.fillna(0)*w); denom=denom.add(v.notna().astype(float)*w)
    x['Market_Intelligence_Score']=(score/denom.replace(0,np.nan)).round(1)
    keep=[c for c in ['Ticker','Sector','Market_Intelligence_Score']+list(found.values())+['Trend','Setup','Forward_PE','Drawdown_%','Drawdown_52w_%'] if c in x.columns]
    return x.sort_values('Market_Intelligence_Score',ascending=False,na_position='last')[keep].head(limit)
