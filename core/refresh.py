from datetime import datetime, timezone
import numpy as np
import pandas as pd

from core.market_data import load_universe,download_prices,get_market_symbols,get_sector_etfs,get_macro_symbols
from core.indicators import enrich_indicators
from core.scoring import analyze_symbol,sector_strength_entry
from core.breadth import composite_breadth
from core.economic_data import institutional_macro_snapshot
from core.macro import sector_macro_score
from core.opportunity import normalize_sector,add_cross_sectional_metrics,attach_scores
from core.relative_strength import add_multi_horizon_rs
from core.confidence import confidence_score
from core.storage import save_latest_snapshot,save_json_snapshot,save_score_snapshot
from core.audit import append_score_audit
from core.monitoring import log_event,log_exception,timer


MIN_EXPANDED_PRICE=2.0
MIN_EXPANDED_DOLLAR_VOLUME_20D=5_000_000
CORE_UNIVERSES={'S&P 500','Nasdaq 100'}


def combine_equity_universes(*universes,limit=None):
    """Combine ordered equity universes without duplicates, preserving provenance."""
    frames=[]
    for universe in universes:
        if universe is not None and not universe.empty and 'Ticker' in universe.columns:
            frames.append(universe.copy())
    if not frames: return pd.DataFrame(columns=['Ticker','Sector'])
    out=pd.concat(frames,ignore_index=True)
    out['Ticker']=out['Ticker'].astype(str).str.upper().str.strip()
    out=out[out['Ticker']!=''].drop_duplicates('Ticker',keep='first')
    return out.head(int(limit)) if limit is not None else out


def equity_liquidity_profile(history,universe_source='',minimum_price=MIN_EXPANDED_PRICE,
                             minimum_dollar_volume=MIN_EXPANDED_DOLLAR_VOLUME_20D):
    """Return a transparent eligibility profile for the expanded universe."""
    if history is None or history.empty or 'Close' not in history:
        return {'eligible':False,'price':None,'average_dollar_volume_20d':None,
                'liquidity_tier':'NO_DATA','reason':'NO_PRICE_DATA'}
    close=pd.to_numeric(history['Close'],errors='coerce').dropna()
    if close.empty:
        return {'eligible':False,'price':None,'average_dollar_volume_20d':None,
                'liquidity_tier':'NO_DATA','reason':'NO_PRICE_DATA'}
    price=float(close.iloc[-1]); adv=None
    if 'Volume' in history:
        volume=pd.to_numeric(history['Volume'],errors='coerce')
        aligned=pd.concat([pd.to_numeric(history['Close'],errors='coerce'),volume],axis=1).dropna().tail(20)
        if not aligned.empty: adv=float((aligned.iloc[:,0]*aligned.iloc[:,1]).mean())
    core=str(universe_source) in CORE_UNIVERSES
    eligible=bool(core or (price>=float(minimum_price) and adv is not None and adv>=float(minimum_dollar_volume)))
    if core: tier='CORE_INDEX'
    elif adv is None: tier='NO_VOLUME'
    elif adv>=50_000_000: tier='HIGH'
    elif adv>=10_000_000: tier='MEDIUM'
    elif adv>=float(minimum_dollar_volume): tier='MINIMUM'
    else: tier='ILLIQUID'
    reason=('CORE_INDEX' if core else 'CURRENT' if eligible else
            'LOW_PRICE' if price<float(minimum_price) else 'LOW_DOLLAR_VOLUME' if adv is not None else 'NO_VOLUME')
    return {'eligible':eligible,'price':round(price,4),
            'average_dollar_volume_20d':None if adv is None else round(adv,2),
            'liquidity_tier':tier,'reason':reason}


def build_market_snapshot(scan_limit=1700):
    with timer('build_market_snapshot',scan_limit=scan_limit):
        sp=load_universe('S&P 500'); ndx=load_universe('Nasdaq 100')
        mid=load_universe('S&P MidCap 400'); small=load_universe('S&P SmallCap 600')
        fb=load_universe('Fallback líquido')
        scan=combine_equity_universes(sp,ndx,mid,small,fb,limit=scan_limit)
        equity_symbols=scan['Ticker'].tolist()
        context_symbols=list(dict.fromkeys(get_market_symbols()+list(get_sector_etfs().values())+
                                           list(get_macro_symbols().values())))
        syms=list(dict.fromkeys(equity_symbols+context_symbols))
        # A failed large batch may retry a few individual names, but never fan
        # out into thousands of provider calls in one scheduled run.
        pm=download_prices(equity_symbols,period='2y',max_single_fallback=24)
        pm.update(download_prices(context_symbols,period='2y'))
        spy=pm.get('SPY')
        bscore,bdf=composite_breadth({'S&P 500':sp,'Nasdaq 100':ndx,'S&P MidCap 400':mid,
                                      'S&P SmallCap 600':small},pm)
        macro=institutional_macro_snapshot(pm,breadth_level=50 if pd.isna(bscore) else bscore)

        rows=[]; failed=[]
        for t in scan['Ticker'].tolist():
            try:
                raw=pm.get(t)
                if raw is None or raw.empty:
                    failed.append((t,'NO_PRICE_DATA')); continue
                source=str(scan.loc[scan['Ticker']==t,'Universe Source'].iloc[0]
                           if 'Universe Source' in scan else 'Unknown')
                liquidity=equity_liquidity_profile(raw,source)
                if not liquidity['eligible']:
                    failed.append((t,f"LIQUIDITY_{liquidity['reason']}")); continue
                h=enrich_indicators(raw)
                if len(h.dropna(subset=['SMA200']))<20:
                    failed.append((t,'INSUFFICIENT_HISTORY')); continue
                sec=scan.loc[scan['Ticker']==t,'Sector'].iloc[0]
                r=analyze_symbol(t,h,spy,sec); r['Sector']=normalize_sector(r['Sector']); r['Asset_Type']='Acciones'
                r['Universe Source']=source
                r['Average Dollar Volume 20d']=liquidity['average_dollar_volume_20d']
                r['Liquidity Tier']=liquidity['liquidity_tier']
                rows.append(r)
            except Exception as exc:
                failed.append((t,type(exc).__name__)); log_exception('snapshot_symbol_error',exc,ticker=t)
        results=pd.DataFrame(rows)

        if len(results):
            results=add_cross_sectional_metrics(results)
            hist_map={}
            for t in results['Ticker'].tolist():
                try: hist_map[t]=enrich_indicators(pm[t])
                except Exception as exc: log_exception('snapshot_rs_history_error',exc,ticker=t)
            results=add_multi_horizon_rs(results,hist_map,pm,get_sector_etfs())

        sector_rows=[]; strength_map={}
        for sec,etf in get_sector_etfs().items():
            try:
                r=analyze_symbol(etf,enrich_indicators(pm[etf]),spy,sec)
                strength,entry,status=sector_strength_entry(r); mf=sector_macro_score(sec,macro)
                overall=round(.45*strength+.25*entry+.30*mf); strength_map[sec]=strength
                sector_rows.append({'Sector':sec,'ETF':etf,'Overall':overall,'Strength':strength,'Entry':entry,'Macro':mf,'Status':status})
            except Exception as exc:
                log_exception('snapshot_sector_error',exc,sector=sec,etf=etf)
        sectors=pd.DataFrame(sector_rows)
        if not sectors.empty: sectors=sectors.sort_values('Overall',ascending=False)

        if len(results):
            results['Sector_Score']=[strength_map.get(normalize_sector(s),np.nan) for s in results['Sector']]
            results['Macro_Fit']=[sector_macro_score(normalize_sector(s),macro) for s in results['Sector']]
            results['Quality_Score']=np.nan
            results['Confidence_Score']=[confidence_score(r,macro=macro)[0] for _,r in results.iterrows()]
            results=attach_scores(results)

        meta={
            'generated_at':datetime.now(timezone.utc).isoformat(),'scan_limit':scan_limit,
            'equity_universe_rows':len(scan),
            'universe_policy':'S&P 500 + Nasdaq 100 + S&P MidCap 400 + S&P SmallCap 600 + curated liquid supplemental; deduplicated and liquidity-gated',
            'universe_source_rows':({str(k):int(v) for k,v in scan['Universe Source'].value_counts().items()}
                                    if 'Universe Source' in scan else {}),
            'expanded_liquidity_gate':{'minimum_price':MIN_EXPANDED_PRICE,
                                       'minimum_average_dollar_volume_20d':MIN_EXPANDED_DOLLAR_VOLUME_20D,
                                       'core_index_exemptions':sorted(CORE_UNIVERSES)},
            'symbols_requested':len(syms),
            'symbols_downloaded':len(pm),'symbols_scored':len(results),'symbol_failures':len(failed),
            'failure_examples':failed[:25],
        }
        save_latest_snapshot(results,'latest_screener')
        if len(results):
            day=datetime.now(timezone.utc).strftime('%Y-%m-%d'); save_latest_snapshot(results,f'history_scores_{day}')
        save_latest_snapshot(sectors,'latest_sectors'); save_latest_snapshot(bdf,'latest_breadth')
        save_json_snapshot(macro,'latest_macro'); save_json_snapshot(meta,'latest_meta')
        if len(results):
            save_score_snapshot(results,'Acciones')
            for _,audit_row in results.sort_values('Preliminary_Score',ascending=False).head(50).iterrows():
                try: append_score_audit(audit_row.to_dict(),reason='daily_refresh')
                except Exception as exc: log_exception('score_audit_error',exc,ticker=audit_row.get('Ticker'))
        log_event('snapshot_complete',**{k:v for k,v in meta.items() if k!='failure_examples'})
        return {'results':results,'sectors':sectors,'breadth':bdf,'macro':macro,'meta':meta,'price_map':pm}
