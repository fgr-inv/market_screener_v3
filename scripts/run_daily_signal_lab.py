"""Post-close technical experiment runner.  Research only; no execution path."""
from __future__ import annotations

from datetime import datetime
import os
from zoneinfo import ZoneInfo

import pandas as pd

from core.agent_audit import append_agent_audit
from core.automation_health import record_automation_heartbeat
from core.desk_store import load_desk_output, save_desk_output
from core.market_data import download_prices
from core.production_storage import storage_mode
from core.signal_lab import (build_daily_signal_lab_report, detect_signal_experiments,
                             evaluate_signal_experiments, load_signal_lab_ledger,
                             merge_signal_lab_ledger, notify_signal_lab, save_signal_lab_ledger)
from core.storage import load_latest_snapshot, load_positions


def _text(row, names, default='Unknown'):
    for name in names:
        value=row.get(name)
        if value is not None and str(value).strip() and str(value).lower()!='nan': return str(value)
    return default


def build_signal_universe(user_id, snapshot, opportunity=None, maximum=90):
    """Balanced liquid universe: desk list, holdings, and large/mid/small leaders."""
    ordered=[]; metadata={}
    discovery=((opportunity or {}).get('payload') or {}).get('discovery') or {}
    for ticker in discovery.get('monitor_tickers') or []:
        ordered.append(str(ticker).upper())
    positions=load_positions(user_id=user_id)
    if positions is not None and not positions.empty:
        ordered.extend(positions['ticker'].dropna().astype(str).str.upper().tolist())
    if snapshot is not None and not snapshot.empty and 'Ticker' in snapshot:
        score_col=next((c for c in ('Opportunity','Opportunity Score','Score','Entry Score') if c in snapshot),None)
        source_col=next((c for c in ('Universe Source','Universe_Source') if c in snapshot),None)
        groups=[]
        if source_col:
            for source in ('S&P 500','Nasdaq 100','S&P MidCap 400','S&P SmallCap 600','Curated Liquid Supplemental'):
                group=snapshot[snapshot[source_col].astype(str)==source].copy()
                if score_col: group=group.sort_values(score_col,ascending=False)
                groups.append(group.head(12))
        else:
            group=snapshot.sort_values(score_col,ascending=False) if score_col else snapshot
            groups=[group.head(60)]
        for _,row in pd.concat(groups,ignore_index=True).drop_duplicates('Ticker').iterrows():
            ticker=str(row['Ticker']).upper(); ordered.append(ticker)
            metadata[ticker]={'sector':_text(row,('Sector','GICS Sector')),
                              'universe_source':_text(row,('Universe Source','Universe_Source')),
                              'market_cap_bucket':_text(row,('Universe Source','Universe_Source'))}
    ordered.extend(['SPY','QQQ','IWM','BTC-USD','ETH-USD','SOL-USD'])
    return list(dict.fromkeys(t for t in ordered if t))[:maximum],metadata


def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    if os.getenv('GITHUB_ACTIONS','').lower()=='true' and storage_mode()!='POSTGRES':
        print('ERROR: DATABASE_URL is required for scheduled signal lab.'); return 2
    now=datetime.now(ZoneInfo('America/New_York'))
    if now.weekday()>=5: print('Daily signal lab skipped: weekend'); return 0
    run_key=f"signal-lab-{now.date().isoformat()}"
    previous=load_desk_output(uid,'signal_lab_daily_report',run_key)
    if previous:
        notification=notify_signal_lab(uid,previous.get('payload') or {},run_key)
        record_automation_heartbeat(uid,'signal_lab_daily','REUSED',{'run_key':run_key,'notification':notification.get('status')})
        print('Daily signal lab reused.'); return 0
    snapshot=load_latest_snapshot('latest_screener')
    opportunity=load_desk_output(uid,'daily_opportunity_hunt',run_key.replace('signal-lab','hunt'))
    if opportunity is None:
        from core.desk_store import load_latest_desk_output
        opportunity=load_latest_desk_output(uid,'daily_opportunity_hunt')
    tickers,metadata=build_signal_universe(uid,snapshot,opportunity)
    ledger=load_signal_lab_ledger(uid)
    completed_20={str(row.get('signal_key')) for row in ledger['outcomes'] if int(row.get('horizon_days') or 0)==20}
    open_tickers=list(dict.fromkeys(str(row.get('ticker')).upper() for row in ledger['signals']
                                   if row.get('ticker') and str(row.get('signal_key')) not in completed_20))
    # Keep every still-open experiment evaluable even if the name drops out of
    # today's shortlist. The cap is a provider-budget guard, not a selection rule.
    tickers=list(dict.fromkeys(tickers+open_tickers))[:250]
    histories=download_prices(tickers,period='2y',max_age_minutes=15,max_single_fallback=12)
    benchmark=histories.get('SPY'); failures=[]; detected=[]
    for ticker in tickers:
        history=histories.get(ticker)
        if history is None or history.empty:
            failures.append({'ticker':ticker,'reason':'PRICE_HISTORY_UNAVAILABLE'}); continue
        detected.extend(detect_signal_experiments(ticker,history,benchmark,metadata.get(ticker),observed_at=now))
    known={row.get('signal_key') for row in ledger['signals']}
    new_signals=[row for row in detected if row.get('signal_key') not in known]
    combined_signals=ledger['signals']+new_signals
    current_signals=[row for row in combined_signals if str(row.get('setup_version'))=='2.0']
    new_outcomes=evaluate_signal_experiments(current_signals,histories,benchmark,ledger['outcomes'],now)
    merged=merge_signal_lab_ledger(ledger,new_signals,new_outcomes)
    save_signal_lab_ledger(uid,merged['signals'],merged['outcomes'])
    report=build_daily_signal_lab_report(new_signals,new_outcomes,len(tickers),failures,now)
    save_desk_output(uid,'signal_lab_daily_report',report,run_key=run_key)
    notification=notify_signal_lab(uid,report,run_key)
    append_agent_audit(uid,'daily_signal_lab',{'run_key':run_key,'universe':len(tickers),
        'new_signals':len(new_signals),'matured_outcomes':len(new_outcomes),'failures':len(failures),
        'notification':notification,'shadow_mode':True,'no_execution':True})
    record_automation_heartbeat(uid,'signal_lab_daily','CURRENT',{'run_key':run_key,'new_signals':len(new_signals),
        'matured_outcomes':len(new_outcomes),'partial_failures':len(failures)})
    print(f"Signal lab: universe={len(tickers)} new={len(new_signals)} matured={len(new_outcomes)} failures={len(failures)} notification={notification.get('status')}")
    return 1 if notification.get('status')=='FAILED' else 0


if __name__=='__main__': raise SystemExit(main())
