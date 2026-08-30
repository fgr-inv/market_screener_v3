"""Compatibility layer for professional industry-aware equity analysis.

V8.8 routes equity research through core.professional_equity_engine. Existing
callers keep the old function names so scans and saved workflows remain stable.
"""
import numpy as np
import pandas as pd

from core.professional_equity_engine import (
    professional_quality_score,
    professional_equity_snapshot,
    classify_equity_subindustry,
)


def sector_fundamental_score(f, sector, industry='', ticker=''):
    r=professional_quality_score(f or {},sector,industry or (f or {}).get('Industry',''),ticker)
    limitation=''
    if r.get('Fundamental_Coverage_%',0)<70:
        limitation='Quality score uses only observed free-data pillars; missing specialist KPIs are not synthesized.'
    return r.get('Quality_Score',np.nan), r.get('Fundamental_Coverage_%',0), limitation


def professional_equity_framework(sector, industry='', ticker=''):
    p=classify_equity_subindustry(sector,industry,ticker)
    kpis=', '.join(p.kpis)
    if 'reit' in p.key and 'FFO/AFFO' not in kpis: kpis='FFO/AFFO, '+kpis
    return (
        f"{p.label}: {p.description} "
        f"Key KPIs: {kpis}. "
        f"Preferred valuation: {', '.join(p.valuation)}."
    )


def equity_research_snapshot(f, sector='', industry='', ticker=''):
    return professional_equity_snapshot(f or {},sector,industry,ticker)
