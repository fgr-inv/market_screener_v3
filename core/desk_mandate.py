"""Versioned desk mandates and official-catalyst qualification.

Mandates are deterministic policy.  They do not contain credentials, call a
broker, or let a model change risk limits at runtime.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import pandas as pd


ROOT=Path(__file__).resolve().parents[1]
DEFAULT_MANDATE_PATH=ROOT/'config'/'mandates'/'us_equities_catalyst.json'
REQUIRED_KEYS={
    'mandate_id','version','mode','broker_connections_allowed','live_execution_allowed',
    'require_primary_catalyst','catalyst_window_days','max_new_positions_per_week',
    'max_open_positions','max_weekly_new_risk_pct','max_sector_weight_pct','starter_fraction','sleeves',
}


def validate_desk_mandate(raw):
    mandate=deepcopy(raw or {})
    missing=sorted(REQUIRED_KEYS-set(mandate))
    if missing: raise ValueError('Desk mandate missing keys: '+', '.join(missing))
    if mandate.get('broker_connections_allowed') is not False:
        raise ValueError('This application accepts only broker-free mandates.')
    if mandate.get('live_execution_allowed') is not False:
        raise ValueError('Live execution must remain disabled.')
    fraction=float(mandate['starter_fraction'])
    if not 0<fraction<=1: raise ValueError('starter_fraction must be in (0, 1].')
    if int(mandate['max_new_positions_per_week'])<0:
        raise ValueError('max_new_positions_per_week cannot be negative.')
    for sleeve,policy in mandate['sleeves'].items():
        for key in ('risk_pct','max_weight_pct','slippage_bps','commission_bps'):
            if key not in policy or float(policy[key])<0:
                raise ValueError(f'{sleeve}.{key} must be non-negative.')
    return mandate


def load_desk_mandate(path=None):
    target=Path(path) if path else DEFAULT_MANDATE_PATH
    return validate_desk_mandate(json.loads(target.read_text(encoding='utf-8')))


def mandate_public_summary(mandate):
    mandate=validate_desk_mandate(mandate)
    return {key:deepcopy(mandate.get(key)) for key in (
        'mandate_id','version','mode','asset_class','cash_is_valid','long_only',
        'broker_connections_allowed','live_execution_allowed','require_primary_catalyst',
        'catalyst_window_days','allowed_catalysts','max_new_positions_per_week',
        'max_open_positions','max_weekly_new_risk_pct','max_sector_weight_pct','starter_fraction','sleeves')}


def classify_official_catalyst(story):
    """Return the narrow event type accepted by the US-equity mandate."""
    text=' '.join(str(story.get(key) or '') for key in ('title','summary','category','form','items')).lower()
    text=re.sub(r'\s+',' ',text)
    if any(term in text for term in ('cuts guidance','cut guidance','lowers outlook','withdraws guidance')):
        return 'GUIDANCE_CUT'
    if any(term in text for term in ('reaffirms guidance','reaffirmed guidance','reiterates guidance','maintains guidance')):
        return 'GUIDANCE_REAFFIRMED'
    if any(term in text for term in ('raises guidance','raised guidance','increases guidance','raises outlook','raised outlook')):
        return 'GUIDANCE_RAISED'
    if any(term in text for term in ('terminates merger','terminated merger','deal terminated','agreement terminated','deal collapsed')):
        return 'DEAL_TERMINATED'
    if any(term in text for term in ('completed acquisition','completes acquisition','closed acquisition','closes acquisition',
                                     'transaction closed','completed merger','completes merger')):
        return 'DEAL_CLOSED'
    if any(term in text for term in ('definitive agreement','signed agreement','enters into agreement','entered into agreement',
                                     'contract award','awarded contract','wins contract','supply agreement')):
        return 'DEAL_SIGNED'
    if any(term in text for term in ('lawsuit','investigation','antitrust','clinical hold','recall','subpoena')):
        return 'MATERIAL_LEGAL_OR_REGULATORY_EVENT'
    return 'OTHER'


def qualifying_catalyst_evidence(stories,mandate,now=None):
    """Return fresh, primary-source events explicitly allowed by the mandate."""
    mandate=validate_desk_mandate(mandate); allowed=set(mandate.get('allowed_catalysts') or [])
    current=pd.Timestamp(now or datetime.now(timezone.utc))
    if current.tzinfo is None: current=current.tz_localize('UTC')
    current=current.tz_convert('UTC'); maximum_days=float(mandate['catalyst_window_days'])
    accepted=[]
    for story in stories or []:
        if mandate.get('require_primary_catalyst') and not bool(story.get('primary')): continue
        event_type=classify_official_catalyst(story)
        if event_type not in allowed: continue
        try:
            published=pd.Timestamp(story.get('published_at'))
            if published.tzinfo is None: published=published.tz_localize('UTC')
            age_days=max(0.0,(current-published.tz_convert('UTC')).total_seconds()/86400)
        except Exception: continue
        if age_days>maximum_days: continue
        accepted.append({**story,'event_type':event_type,'age_days':round(age_days,2),'verified':True})
    accepted.sort(key=lambda row:row.get('published_at') or '',reverse=True)
    return accepted


def invalidating_catalyst_evidence(stories,mandate,now=None):
    """Return fresh official events that kill, rather than merely weaken, a thesis."""
    mandate=validate_desk_mandate(mandate); invalidations=set(mandate.get('thesis_invalidations') or [])
    current=pd.Timestamp(now or datetime.now(timezone.utc))
    if current.tzinfo is None: current=current.tz_localize('UTC')
    current=current.tz_convert('UTC'); maximum_days=float(mandate['catalyst_window_days'])
    rejected=[]
    for story in stories or []:
        if mandate.get('require_primary_catalyst') and not bool(story.get('primary')): continue
        event_type=classify_official_catalyst(story)
        if event_type not in invalidations: continue
        try:
            published=pd.Timestamp(story.get('published_at'))
            if published.tzinfo is None: published=published.tz_localize('UTC')
            age_days=max(0.0,(current-published.tz_convert('UTC')).total_seconds()/86400)
        except Exception: continue
        if age_days<=maximum_days:
            rejected.append({**story,'event_type':event_type,'age_days':round(age_days,2),'verified':True})
    rejected.sort(key=lambda row:row.get('published_at') or '',reverse=True)
    return rejected
