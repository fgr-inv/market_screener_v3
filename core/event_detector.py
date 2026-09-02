"""Cheap, snapshot-only event detection for the background desk.

The detector never calls a provider. It compares already-persisted screener and
market snapshots and emits typed events that can be routed without waking every
specialist.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import math
import pandas as pd

MAX_CURRENT_AGE_HOURS=36


def _num(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _text(value):
    if value is None or (not isinstance(value,str) and pd.isna(value)):
        return ''
    return str(value).strip()


def _fingerprint(ticker,event_types,signal):
    canonical=json.dumps(
        {'ticker':ticker,'event_types':sorted(event_types),'signal':signal},
        sort_keys=True,separators=(',',':'),default=str,
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]


def _event(ticker,event_types,severity,reasons,portfolio=False,metrics=None):
    types=sorted(set(event_types)); metrics=metrics or {}
    return {
        'ticker':ticker,'event_types':types,'severity':int(max(severity,1)),
        'reasons':reasons,'portfolio':bool(portfolio),'metrics':metrics,
        'event_key':f"{ticker}:{'+'.join(types)}",
        'fingerprint':_fingerprint(ticker,types,metrics),
    }


def detect_snapshot_events(
    latest: pd.DataFrame,
    previous: pd.DataFrame|None=None,
    portfolio_tickers=None,
    max_events=12,
    price_move_pct=4.0,
    abnormal_volume=2.0,
):
    """Detect price, volume, technical and fundamental changes from cached rows."""
    if latest is None or latest.empty or 'Ticker' not in latest.columns:
        return []
    x=latest.copy(); x['Ticker']=x['Ticker'].astype(str).str.upper()
    portfolio={str(t).upper() for t in (portfolio_tickers or [])}
    prev={}
    if previous is not None and not previous.empty and 'Ticker' in previous.columns:
        prev={str(r['Ticker']).upper():r for _,r in previous.iterrows()}
    events=[]
    for _,r in x.iterrows():
        ticker=str(r['Ticker']).upper(); old=prev.get(ticker)
        reasons=[]; types=[]; severity=0; metrics={}
        entry=_num(r.get('Entry_Score')); opp=_num(r.get('Opportunity_Score'))
        price=_num(r.get('Price')); rel_volume=_num(r.get('Rel_Volume'))

        if entry is not None and entry>=75:
            types.append('strong_candidate'); reasons.append(f'Entry score {entry:.0f}'); severity+=2
            metrics['entry_score']=round(entry)
        if opp is not None and opp>=75:
            types.append('strong_candidate'); reasons.append(f'Opportunity score {opp:.0f}'); severity+=2
            metrics['opportunity_score']=round(opp)
        if rel_volume is not None and rel_volume>=abnormal_volume:
            old_rel=_num(old.get('Rel_Volume')) if old is not None else None
            if old_rel is None or old_rel<abnormal_volume:
                types.append('abnormal_volume'); reasons.append(f'Relative volume {rel_volume:.1f}x'); severity+=2
                metrics['relative_volume']=round(rel_volume,1)

        if old is not None:
            old_price=_num(old.get('Price'))
            if price is not None and old_price not in (None,0):
                move=(price/old_price-1)*100
                if abs(move)>=price_move_pct:
                    types.append('large_price_move'); reasons.append(f'Price moved {move:+.1f}%'); severity+=3 if abs(move)>=7 else 2
                    metrics['price_move_pct']=round(move,1); metrics['price']=round(price,6)
                    observed=_text(r.get('Live_Observed_At'))
                    if observed: metrics['observed_at']=observed
            old_entry=_num(old.get('Entry_Score'))
            if entry is not None and old_entry is not None and abs(entry-old_entry)>=12:
                types.append('technical_score_change'); reasons.append(f'Entry score moved {entry-old_entry:+.0f}'); severity+=2
                metrics['entry_score_change']=round(entry-old_entry)
            for column,label in (('Action','Action'),('Setup','Setup'),('Trend','Trend')):
                before=_text(old.get(column)); after=_text(r.get(column))
                if before and after and before!=after:
                    types.append('technical_state_change'); reasons.append(f'{label} changed {before} → {after}'); severity+=1
                    metrics[column.lower()]=after
            old_fund=_num(old.get('Fundamental_Opportunity_Score')); fund=_num(r.get('Fundamental_Opportunity_Score'))
            if fund is not None and old_fund is not None and abs(fund-old_fund)>=10:
                types.append('fundamental_change'); reasons.append(f'Fundamental score moved {fund-old_fund:+.0f}'); severity+=2
                metrics['fundamental_score_change']=round(fund-old_fund)
            old_event=_text(old.get('Event_Risk')).upper(); event_risk=_text(r.get('Event_Risk')).upper()
            if event_risk in {'ELEVATED','HIGH','HIGH_RISK'} and event_risk!=old_event:
                types.append('fundamental_event'); reasons.append(f'Event risk changed {old_event or "N/D"} → {event_risk}'); severity+=2
                metrics['event_risk']=event_risk

        if ticker in portfolio and types:
            severity+=1
        if types and severity>=2:
            events.append(_event(ticker,types,severity,reasons,ticker in portfolio,metrics))
    events.sort(key=lambda e:(e['portfolio'],e['severity']),reverse=True)
    return events[:int(max_events)]


def market_context(macro=None,snapshot_meta=None):
    macro=macro or {}; meta=snapshot_meta or {}
    return {
        'risk_regime':_text(macro.get('Institutional_Regime') or macro.get('Risk_Regime') or 'N/A').upper(),
        'economic_regime':_text(macro.get('Economic_Regime_Slow') or macro.get('Economic_Regime') or 'N/A').upper(),
        'momentum':_text(macro.get('Momentum') or 'N/A').upper(),
        'generated_at':_text(meta.get('generated_at')),
    }


def detect_market_context_events(macro=None,snapshot_meta=None,previous_context=None,max_age_hours=MAX_CURRENT_AGE_HOURS):
    """Detect stale central data or a changed cached market regime."""
    context=market_context(macro,snapshot_meta); previous_context=previous_context or {}
    reasons=[]; types=[]; severity=0; metrics={k:v for k,v in context.items() if k!='generated_at'}
    generated=context.get('generated_at')
    if generated:
        try:
            ts=pd.Timestamp(generated)
            if ts.tzinfo is None: ts=ts.tz_localize('UTC')
            now=pd.Timestamp(datetime.now(timezone.utc))
            age=max(0,(now-ts.tz_convert('UTC')).total_seconds()/3600)
            metrics['snapshot_age_hours']=round(age,1)
            if age>max_age_hours:
                types.append('snapshot_stale'); reasons.append(f'Central snapshot is stale ({age:.1f}h)'); severity+=4
        except Exception:
            types.append('snapshot_status_unknown'); reasons.append('Central snapshot timestamp is invalid'); severity+=3
    else:
        types.append('snapshot_status_unknown'); reasons.append('Central snapshot timestamp is unavailable'); severity+=3
    for key,label in (('risk_regime','Market regime'),('economic_regime','Economic regime'),('momentum','Macro momentum')):
        before=_text(previous_context.get(key)); after=_text(context.get(key))
        if before and after and before!=after:
            types.append('market_regime_change'); reasons.append(f'{label} changed {before} → {after}'); severity+=2
    return [] if not types else [_event('MARKET',types,severity,reasons,False,metrics)]
