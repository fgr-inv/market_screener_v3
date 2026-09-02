"""Cheap event detector. Uses existing snapshots only; it never calls a market-data provider."""
from __future__ import annotations
import pandas as pd

def detect_snapshot_events(latest: pd.DataFrame, previous: pd.DataFrame|None=None, portfolio_tickers=None, max_events=12):
    if latest is None or latest.empty or 'Ticker' not in latest.columns: return []
    x=latest.copy(); x['Ticker']=x['Ticker'].astype(str).str.upper()
    portfolio={str(t).upper() for t in (portfolio_tickers or [])}
    prev={}
    if previous is not None and not previous.empty and 'Ticker' in previous.columns:
        prev={str(r['Ticker']).upper():r for _,r in previous.iterrows()}
    events=[]
    for _,r in x.iterrows():
        t=str(r['Ticker']).upper(); reasons=[]; severity=0
        entry=pd.to_numeric(r.get('Entry_Score'),errors='coerce'); opp=pd.to_numeric(r.get('Opportunity_Score'),errors='coerce')
        if pd.notna(entry) and entry>=75: reasons.append(f'Entry score {entry:.0f}'); severity+=2
        if pd.notna(opp) and opp>=75: reasons.append(f'Opportunity score {opp:.0f}'); severity+=2
        old=prev.get(t)
        if old is not None:
            old_entry=pd.to_numeric(old.get('Entry_Score'),errors='coerce')
            if pd.notna(entry) and pd.notna(old_entry) and abs(entry-old_entry)>=12:
                reasons.append(f'Entry score moved {entry-old_entry:+.0f}'); severity+=2
            old_action=str(old.get('Action','')); action=str(r.get('Action',''))
            if action and old_action and action!=old_action:
                reasons.append(f'Action changed {old_action} → {action}'); severity+=1
        if t in portfolio:
            severity+=1
            if not reasons: reasons.append('Portfolio holding scheduled review')
        if severity>=2: events.append({'ticker':t,'severity':severity,'reasons':reasons,'portfolio':t in portfolio})
    events.sort(key=lambda e:(e['portfolio'],e['severity']),reverse=True)
    return events[:int(max_events)]
