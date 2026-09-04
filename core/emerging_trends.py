"""Evidence-based equity size and early-trend diagnostics.

The module describes observable market structure; it does not forecast a
guaranteed price move.  All calculations use completed daily bars so the same
inputs always produce the same result in Shadow validation.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd


CAP_BOUNDS = {
    'micro_max': 300_000_000,
    'small_max': 2_000_000_000,
    'mid_max': 10_000_000_000,
    'large_max': 200_000_000_000,
}


def _number(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def cap_segment(market_cap=None, universe_source=''):
    """Classify company size from observed market cap, then index provenance."""
    value = _number(market_cap)
    if value is not None and value > 0:
        if value < CAP_BOUNDS['micro_max']:
            return 'Micro Cap'
        if value < CAP_BOUNDS['small_max']:
            return 'Small Cap'
        if value < CAP_BOUNDS['mid_max']:
            return 'Mid Cap'
        if value < CAP_BOUNDS['large_max']:
            return 'Large Cap'
        return 'Mega Cap'
    source = str(universe_source or '').lower()
    if 'small' in source:
        return 'Small Cap'
    if 'mid' in source:
        return 'Mid Cap'
    if 's&p 500' in source or 'nasdaq 100' in source:
        return 'Large Cap'
    return 'Unknown'


def _return(close, periods):
    if len(close) <= periods:
        return np.nan
    old = float(close.iloc[-(periods + 1)])
    return np.nan if old == 0 else (float(close.iloc[-1]) / old - 1) * 100


def _safe_ratio(numerator, denominator):
    try:
        denominator = float(denominator)
        return np.nan if denominator <= 0 else float(numerator) / denominator
    except Exception:
        return np.nan


def analyze_emerging_trend(history, benchmark=None):
    """Score established and developing trends using price/volume evidence.

    Phases intentionally separate a confirmed leader from an early setup.  A
    high early-trend score is a research priority, never a promise that a
    breakout will occur.
    """
    empty = {
        'Emerging_Trend_Score': np.nan,
        'Trend_Phase': 'INSUFFICIENT_DATA',
        'Trend_Opportunity': False,
        'Breakout_Proximity_%': np.nan,
        'Momentum_Acceleration': np.nan,
        'Accumulation_Score': np.nan,
        'Compression_Ratio': np.nan,
        'RS_63d_Emerging_%': np.nan,
    }
    if history is None or history.empty or 'Close' not in history:
        return empty
    frame = history.copy()
    close = pd.to_numeric(frame['Close'], errors='coerce').dropna()
    if len(close) < 126:
        return empty

    price = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50_series = close.rolling(50).mean().dropna()
    sma200_series = close.rolling(200).mean().dropna()
    sma50 = float(sma50_series.iloc[-1]) if not sma50_series.empty else np.nan
    sma200 = float(sma200_series.iloc[-1]) if not sma200_series.empty else np.nan
    slope50 = (_return(sma50_series, 20) if len(sma50_series) > 20 else np.nan)
    slope200 = (_return(sma200_series, 20) if len(sma200_series) > 20 else np.nan)
    ret20, ret63, ret126 = (_return(close, period) for period in (20, 63, 126))
    acceleration = ret20 - ret63 / 3 if pd.notna(ret20) and pd.notna(ret63) else np.nan

    prior_high = float(close.iloc[-64:-1].max()) if len(close) >= 64 else np.nan
    proximity = (price / prior_high - 1) * 100 if pd.notna(prior_high) and prior_high else np.nan

    returns = close.pct_change().dropna()
    vol20 = float(returns.tail(20).std()) if len(returns) >= 20 else np.nan
    vol63 = float(returns.tail(63).std()) if len(returns) >= 63 else np.nan
    compression = _safe_ratio(vol20, vol63)

    accumulation_ratio = np.nan
    if 'Volume' in frame:
        aligned = pd.DataFrame({
            'close': pd.to_numeric(frame['Close'], errors='coerce'),
            'volume': pd.to_numeric(frame['Volume'], errors='coerce'),
        }).dropna().tail(21)
        if len(aligned) >= 15:
            direction = aligned['close'].diff()
            up = aligned.loc[direction > 0, 'volume'].sum()
            down = aligned.loc[direction < 0, 'volume'].sum()
            accumulation_ratio = 2.0 if down <= 0 and up > 0 else _safe_ratio(up, down)
    accumulation_score = (90 if pd.notna(accumulation_ratio) and accumulation_ratio >= 1.5 else
                          75 if pd.notna(accumulation_ratio) and accumulation_ratio >= 1.15 else
                          55 if pd.notna(accumulation_ratio) and accumulation_ratio >= .9 else
                          30 if pd.notna(accumulation_ratio) else np.nan)

    benchmark_rs = np.nan
    if benchmark is not None and not benchmark.empty and 'Close' in benchmark:
        bench_close = pd.to_numeric(benchmark['Close'], errors='coerce').dropna()
        bench_ret = _return(bench_close, 63)
        if pd.notna(ret63) and pd.notna(bench_ret):
            benchmark_rs = ret63 - bench_ret

    above50 = pd.notna(sma50) and price > sma50
    above200 = pd.notna(sma200) and price > sma200
    aligned = above50 and above200 and pd.notna(sma20) and sma20 > sma50
    extended = pd.notna(sma50) and price > sma50 * 1.18
    breakout = bool(pd.notna(proximity) and proximity >= 0 and above50 and
                    pd.notna(accumulation_ratio) and accumulation_ratio >= 1.05)
    base = bool(pd.notna(proximity) and -6 <= proximity < 1.5 and above50 and above200 and
                pd.notna(compression) and compression <= 1.05)
    early = bool(above50 and pd.notna(slope50) and slope50 > 0 and
                 pd.notna(acceleration) and acceleration >= 1.5 and
                 (pd.isna(benchmark_rs) or benchmark_rs > -2))

    score = 0
    score += 10 if above200 else 0
    score += 10 if above50 else 0
    score += 10 if aligned else 0
    score += 8 if pd.notna(ret20) and ret20 > 0 else 0
    score += 12 if pd.notna(acceleration) and acceleration >= 2 else 6 if pd.notna(acceleration) and acceleration > 0 else 0
    score += 10 if pd.notna(benchmark_rs) and benchmark_rs >= 5 else 6 if pd.notna(benchmark_rs) and benchmark_rs > 0 else 0
    score += 15 if pd.notna(proximity) and -6 <= proximity <= 2 else 8 if pd.notna(proximity) and -12 <= proximity < -6 else 0
    score += 10 if pd.notna(accumulation_score) and accumulation_score >= 75 else 5 if pd.notna(accumulation_score) and accumulation_score >= 55 else 0
    score += 10 if pd.notna(compression) and compression <= .85 else 5 if pd.notna(compression) and compression <= 1.05 else 0
    score += 5 if pd.notna(slope200) and slope200 > 0 else 0
    if extended:
        score -= 18
    if pd.notna(ret20) and ret20 < -8:
        score -= 12
    score = int(max(0, min(100, score)))

    if breakout and score >= 65:
        phase = 'BREAKOUT_CONFIRMED'
    elif aligned and pd.notna(ret63) and ret63 >= 10 and (pd.isna(benchmark_rs) or benchmark_rs > 0) and score >= 70:
        phase = 'ESTABLISHED_LEADER'
    elif base and score >= 62:
        phase = 'BASE_NEAR_BREAKOUT'
    elif early and score >= 58:
        phase = 'EARLY_ACCELERATION'
    elif above50 and not above200 and pd.notna(acceleration) and acceleration > 2:
        phase = 'RECOVERY_WATCH'
    else:
        phase = 'NO_QUALIFIED_SETUP'
    opportunity = phase in {'BREAKOUT_CONFIRMED', 'ESTABLISHED_LEADER',
                            'BASE_NEAR_BREAKOUT', 'EARLY_ACCELERATION'} and score >= 62
    return {
        'Emerging_Trend_Score': score,
        'Trend_Phase': phase,
        'Trend_Opportunity': bool(opportunity),
        'Breakout_Proximity_%': round(float(proximity), 2) if pd.notna(proximity) else np.nan,
        'Momentum_Acceleration': round(float(acceleration), 2) if pd.notna(acceleration) else np.nan,
        'Accumulation_Score': accumulation_score,
        'Compression_Ratio': round(float(compression), 3) if pd.notna(compression) else np.nan,
        'RS_63d_Emerging_%': round(float(benchmark_rs), 2) if pd.notna(benchmark_rs) else np.nan,
    }
