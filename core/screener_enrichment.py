"""Fast, resilient deep-enrichment orchestration for the Professional Screener.

The screener is intentionally two-stage:
1) fast cross-sectional scan over the full universe;
2) deep network enrichment only for the highest-ranked candidates.

Deep provider calls are cached on disk and fetched with a bounded thread pool.
The cache is only a performance layer; stale/missing provider data is never
converted into fabricated observations.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import threading
import time

import numpy as np
import pandas as pd

from core.fundamentals import get_fundamentals, get_market_valuation_snapshot
from core.analyst_data import get_analyst_snapshot
from core.events import earnings_event
from core.cache_policy import FUNDAMENTALS_TTL, ANALYST_TTL, EVENT_TTL, VALUATION_TTL
from core.provider_rate_limit import acquire as acquire_provider_slot

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / 'data' / 'cache' / 'screener_deep'
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_CACHE_LOCK = threading.Lock()


def _now_ts() -> float:
    return time.time()


def _safe_ticker(ticker: str) -> str:
    return ''.join(ch for ch in str(ticker).upper().strip() if ch.isalnum() or ch in '.-_=^')


def _path(ticker: str) -> Path:
    return CACHE_DIR / f'{_safe_ticker(ticker)}.json'


def _jsonable(value):
    if isinstance(value, pd.DataFrame):
        return None
    if isinstance(value, pd.Series):
        return value.to_dict()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items() if not isinstance(v, pd.DataFrame)}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if value is pd.NA:
        return None
    return value


def _read_cache(ticker: str) -> dict:
    p = _path(ticker)
    try:
        if p.exists():
            obj = json.loads(p.read_text(encoding='utf-8'))
            return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    return {}


def _write_cache(ticker: str, payload: dict) -> None:
    p = _path(ticker)
    tmp = p.with_suffix('.tmp')
    try:
        text = json.dumps(_jsonable(payload), ensure_ascii=False, separators=(',', ':'))
        with _CACHE_LOCK:
            tmp.write_text(text, encoding='utf-8')
            tmp.replace(p)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def _fresh(section: dict, ttl: int, now: float | None = None) -> bool:
    if not isinstance(section, dict) or 'data' not in section:
        return False
    now = _now_ts() if now is None else now
    try:
        return now - float(section.get('ts', 0)) <= ttl
    except Exception:
        return False


def clear_deep_cache(ticker: str | None = None) -> int:
    paths = [_path(ticker)] if ticker else list(CACHE_DIR.glob('*.json'))
    n = 0
    for p in paths:
        try:
            if p.exists():
                p.unlink(); n += 1
        except Exception:
            pass
    return n


def _event_from_analyst(analyst: dict) -> dict | None:
    raw = str((analyst or {}).get('Next_Earnings', 'N/D'))
    if not raw or raw in {'N/D', 'None', 'nan', 'NaT'}:
        return None
    try:
        ts = pd.Timestamp(raw)
        if ts.tzinfo is not None:
            ts = ts.tz_convert(None)
        days = (ts.normalize() - pd.Timestamp.now().normalize()).days
        risk = 'HIGH' if 0 <= days <= 3 else 'ELEVATED' if 4 <= days <= 7 else 'NORMAL'
        return {'next_earnings': str(ts.date()), 'days_to_earnings': int(days), 'risk': risk}
    except Exception:
        return None


def deep_bundle_cache_fresh(ticker: str) -> bool:
    """True when all expensive deep sections are currently reusable."""
    ticker=_safe_ticker(ticker); now=_now_ts(); cached=_read_cache(ticker)
    return all([
        _fresh(cached.get('fundamentals',{}), FUNDAMENTALS_TTL, now),
        _fresh(cached.get('valuation',{}), VALUATION_TTL, now),
        _fresh(cached.get('analyst',{}), ANALYST_TTL, now),
        _fresh(cached.get('event',{}), EVENT_TTL, now),
    ])

def fetch_deep_bundle(ticker: str, force_refresh: bool = False) -> dict:
    """Fetch fundamentals/analyst/event data with independent TTLs and fallbacks."""
    ticker = _safe_ticker(ticker)
    started = time.perf_counter()
    now = _now_ts()
    cached = {} if force_refresh else _read_cache(ticker)
    result = {'Ticker': ticker, 'Cache_Hits': [], 'Fetch_Issues': []}
    updated = dict(cached)

    # Fundamentals: slow accounting layer; keep for seven days unless explicitly refreshed.
    sec = cached.get('fundamentals', {})
    if not force_refresh and _fresh(sec, FUNDAMENTALS_TTL, now):
        f = sec.get('data') or {}
        result['Cache_Hits'].append('fundamentals')
    else:
        try:
            acquire_provider_slot('DEEP_BUNDLE')
            f = get_fundamentals(ticker) or {}
            updated['fundamentals'] = {'ts': now, 'data': f}
        except Exception as exc:
            f = sec.get('data') or {}
            result['Fetch_Issues'].append(f'fundamentals:{type(exc).__name__}')
    # Market-sensitive valuation is intentionally refreshed daily, independently
    # of the seven-day accounting-fundamental cache.
    vsec = cached.get('valuation', {})
    if not force_refresh and _fresh(vsec, VALUATION_TTL, now):
        v = vsec.get('data') or {}
        result['Cache_Hits'].append('valuation')
    else:
        try:
            acquire_provider_slot('DEEP_BUNDLE')
            v = get_market_valuation_snapshot(ticker) or {}
            updated['valuation'] = {'ts': now, 'data': v}
        except Exception as exc:
            v = vsec.get('data') or {}
            result['Fetch_Issues'].append(f'valuation:{type(exc).__name__}')
    if isinstance(f, dict) and isinstance(v, dict):
        merged_f = dict(f)
        for k, val in v.items():
            if k.startswith('Valuation_Market_Overlay_') or (val is not None and not (isinstance(val, float) and math.isnan(val))):
                merged_f[k] = val
        f = merged_f
    result['fundamentals'] = f
    result['valuation'] = v

    # Analyst estimates/revisions: refresh every twelve hours.
    sec = cached.get('analyst', {})
    if not force_refresh and _fresh(sec, ANALYST_TTL, now):
        a = sec.get('data') or {}
        result['Cache_Hits'].append('analyst')
    else:
        try:
            acquire_provider_slot('DEEP_BUNDLE')
            a = get_analyst_snapshot(ticker) or {}
            # Revision_Detail is a DataFrame and not required by the screener table.
            if isinstance(a, dict):
                a = {k: v for k, v in a.items() if k != 'Revision_Detail'}
            updated['analyst'] = {'ts': now, 'data': a}
        except Exception as exc:
            a = sec.get('data') or {}
            result['Fetch_Issues'].append(f'analyst:{type(exc).__name__}')
    result['analyst'] = a

    # Avoid a duplicate Yahoo calendar call when analyst data already exposed the date.
    derived_event = _event_from_analyst(a)
    sec = cached.get('event', {})
    if derived_event is not None:
        e = derived_event
        updated['event'] = {'ts': now, 'data': e}
        result['Event_Source'] = 'analyst_snapshot'
    elif not force_refresh and _fresh(sec, EVENT_TTL, now):
        e = sec.get('data') or {}
        result['Cache_Hits'].append('event')
        result['Event_Source'] = 'cache'
    else:
        try:
            acquire_provider_slot('DEEP_BUNDLE')
            e = earnings_event(ticker) or {}
            updated['event'] = {'ts': now, 'data': e}
            result['Event_Source'] = 'earnings_event'
        except Exception as exc:
            e = sec.get('data') or {'risk': 'UNKNOWN', 'days_to_earnings': None}
            result['Fetch_Issues'].append(f'event:{type(exc).__name__}')
            result['Event_Source'] = 'fallback'
    result['event'] = e

    # Preserve usable previous sections if a transient provider failure returned an error-only payload.
    old_f = (cached.get('fundamentals') or {}).get('data') or {}
    if isinstance(f, dict) and f.get('error') and isinstance(old_f, dict) and old_f.get('Fundamentals_Available'):
        rescued = dict(old_f)
        if isinstance(v, dict):
            rescued.update({k: val for k, val in v.items() if val is not None})
        result['fundamentals'] = rescued
        result['Cache_Hits'].append('fundamentals_stale_rescue')

    _write_cache(ticker, updated)
    result['Fetch_Seconds'] = round(time.perf_counter() - started, 3)
    result['From_Cache'] = bool(result['Cache_Hits'])
    return result


def fetch_deep_bundles(tickers, max_workers: int = 4, force_refresh: bool = False) -> tuple[dict, dict]:
    """Bounded parallel fetch for candidate tickers.

    Returns (bundles, diagnostics). max_workers is intentionally capped at 8 to
    avoid hammering free/public providers.
    """
    tickers = list(dict.fromkeys(_safe_ticker(t) for t in tickers if t))
    workers = max(1, min(int(max_workers or 1), 8, len(tickers) or 1))
    started = time.perf_counter()
    bundles = {}
    if workers == 1 or len(tickers) <= 1:
        for t in tickers:
            bundles[t] = fetch_deep_bundle(t, force_refresh=force_refresh)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='screener-deep') as pool:
            futs = {pool.submit(fetch_deep_bundle, t, force_refresh): t for t in tickers}
            for fut in as_completed(futs):
                t = futs[fut]
                try:
                    bundles[t] = fut.result()
                except Exception as exc:
                    bundles[t] = {
                        'Ticker': t, 'fundamentals': {}, 'analyst': {},
                        'event': {'risk': 'UNKNOWN', 'days_to_earnings': None},
                        'Cache_Hits': [], 'Fetch_Issues': [f'bundle:{type(exc).__name__}'],
                        'Fetch_Seconds': np.nan, 'From_Cache': False,
                    }
    cache_sections = sum(len(b.get('Cache_Hits', [])) for b in bundles.values())
    issues = sum(len(b.get('Fetch_Issues', [])) for b in bundles.values())
    diagnostics = {
        'tickers': len(tickers),
        'workers': workers,
        'elapsed_seconds': round(time.perf_counter() - started, 3),
        'cache_sections': cache_sections,
        'issues': issues,
    }
    return bundles, diagnostics
