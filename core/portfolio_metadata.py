"""Portfolio metadata enrichment without changing economic position data."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.config import SECTOR_ALIASES, SECTOR_ETFS


ROOT=Path(__file__).resolve().parents[1]
MISSING_SECTORS={'','unknown','none','nan','n/a','not classified'}
SPECIAL_SECTORS={
    'IBIT':'Digital Assets','FBTC':'Digital Assets','GBTC':'Digital Assets','BITB':'Digital Assets',
    'ARKB':'Digital Assets','BTC-USD':'Digital Assets','ETH-USD':'Digital Assets','SOL-USD':'Digital Assets',
    'AAVE-USD':'Digital Assets','ZEC-USD':'Digital Assets','UNI-USD':'Digital Assets',
    'SPY':'Diversified Equity','QQQ':'Diversified Equity','IWM':'Diversified Equity','DIA':'Diversified Equity','RSP':'Diversified Equity',
    'TLT':'Fixed Income','IEF':'Fixed Income','SHY':'Fixed Income','HYG':'Fixed Income','LQD':'Fixed Income',
    'GLD':'Commodities','SLV':'Commodities','USO':'Commodities','UNG':'Commodities','DBA':'Commodities',
}
SPECIAL_SECTORS.update({ticker:sector for sector,ticker in SECTOR_ETFS.items()})


def sector_is_missing(value):
    return str(value or '').strip().lower() in MISSING_SECTORS


def normalize_portfolio_sector(value):
    value=str(value or '').strip()
    return SECTOR_ALIASES.get(value,value) if not sector_is_missing(value) else 'Unknown'


def _local_sector_map():
    mapping={}
    for path in (ROOT/'data'/'fallback_universe.csv',ROOT/'data'/'snapshots'/'latest_screener.parquet'):
        try:
            frame=pd.read_csv(path) if path.suffix=='.csv' else pd.read_parquet(path)
            if {'Ticker','Sector'}.issubset(frame.columns):
                for _,row in frame[['Ticker','Sector']].dropna().iterrows():
                    ticker=str(row['Ticker']).upper().strip()
                    sector=normalize_portfolio_sector(row['Sector'])
                    if ticker and not sector_is_missing(sector): mapping[ticker]=sector
        except Exception:
            continue
    return mapping


def infer_position_sectors(positions,live_fallback=True):
    """Return inferred sectors only for rows whose saved sector is missing."""
    if positions is None or positions.empty: return {}
    local=_local_sector_map(); resolved={}
    missing=[]
    for _,row in positions.iterrows():
        ticker=str(row.get('ticker','')).upper().strip()
        if not ticker or not sector_is_missing(row.get('sector')): continue
        sector=SPECIAL_SECTORS.get(ticker) or ('Digital Assets' if ticker.endswith('-USD') else None) or local.get(ticker)
        if sector: resolved[ticker]=normalize_portfolio_sector(sector)
        else: missing.append(ticker)
    if live_fallback and missing:
        from core.industry import get_industry
        for ticker in missing:
            try:
                sector=normalize_portfolio_sector(get_industry(ticker).get('Sector'))
                if not sector_is_missing(sector): resolved[ticker]=sector
            except Exception:
                continue
    return resolved
