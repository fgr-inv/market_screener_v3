"""One immutable data context shared by every specialist in a desk run."""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

from core.market_data import download_prices
from core.storage import load_json_snapshot,load_latest_snapshot,load_positions,load_theses


@dataclass(frozen=True)
class DeskRunContext:
    positions: pd.DataFrame
    theses: pd.DataFrame
    histories: dict
    macro: dict
    meta: dict
    sectors: pd.DataFrame
    screener: pd.DataFrame


def build_desk_context(user_id,ticker_agents,global_agents,automated=False,
                       position_loader=load_positions,thesis_loader=load_theses,
                       price_loader=download_prices,json_loader=load_json_snapshot,
                       snapshot_loader=load_latest_snapshot):
    """Load each durable snapshot once and make one bounded price request."""
    uid=str(user_id or 'local-user'); global_agents=set(global_agents or [])
    positions=position_loader(user_id=uid)
    position_ticks=[] if positions.empty else positions['ticker'].dropna().astype(str).str.upper().tolist()
    needs_news=any('news' in set(agents) for agents in (ticker_agents or {}).values())
    theses=thesis_loader(user_id=uid) if needs_news else pd.DataFrame()
    needs_prices=('portfolio' in global_agents or automated or
                  any({'technical','news'} & set(agents) for agents in (ticker_agents or {}).values()))
    price_ticks=list(ticker_agents or {})+(position_ticks if 'portfolio' in global_agents else [])
    if automated and ticker_agents: price_ticks.append('SPY')
    unique=list(dict.fromkeys(price_ticks))
    histories=price_loader(unique,period='2y',max_age_minutes=15) if needs_prices and unique else {}
    return DeskRunContext(
        positions=positions,theses=theses,histories=histories,
        macro=json_loader('latest_macro') or {},meta=json_loader('latest_meta') or {},
        sectors=snapshot_loader('latest_sectors'),screener=snapshot_loader('latest_screener'))
