from datetime import datetime, timezone
import numpy as np
import pandas as pd


def freshness_score(ts, max_age_hours=24):
    if ts is None or pd.isna(ts):
        return 0
    try:
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize('UTC')
        now = pd.Timestamp.now(tz='UTC')
        age = max((now - t).total_seconds()/3600, 0)
        return int(max(0, min(100, 100 * (1 - age/max_age_hours))))
    except Exception:
        return 0


def completeness_score(mapping, required_keys):
    if not required_keys:
        return 100
    present = 0
    for k in required_keys:
        v = mapping.get(k)
        try:
            missing = v is None or pd.isna(v)
        except Exception:
            missing = v is None
        if not missing:
            present += 1
    return round(present/len(required_keys)*100)


def quality_label(score):
    if score >= 90: return 'EXCELLENT'
    if score >= 75: return 'GOOD'
    if score >= 55: return 'PARTIAL'
    return 'LOW'


def build_quality_record(source, data, required_keys, timestamp=None, max_age_hours=24, notes=''):
    comp = completeness_score(data, required_keys)
    fresh = freshness_score(timestamp or datetime.now(timezone.utc), max_age_hours)
    score = round(0.75*comp + 0.25*fresh)
    return {
        'Source': source,
        'Completeness %': comp,
        'Freshness %': fresh,
        'Quality Score': score,
        'Quality': quality_label(score),
        'Timestamp': str(timestamp or datetime.now(timezone.utc)),
        'Notes': notes,
    }


def confidence_from_sources(records):
    if not records:
        return 0
    vals = [r.get('Quality Score', 0) for r in records]
    return int(round(float(np.mean(vals))))
