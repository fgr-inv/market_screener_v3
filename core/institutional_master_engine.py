from __future__ import annotations
import numpy as np
from core.institutional_valuation import valuation_workstation
from core.financial_forensics import financial_forensics
from core.macro_regime_engine import macro_regime
from core.commodity_institutional import commodity_institutional_snapshot
from core.portfolio_intelligence import single_asset_portfolio_fit
from core.factor_model import factor_exposures
from core.institutional_thesis import build_thesis

def institutional_master_snapshot(ticker,asset_type,row,fund=None,macro=None,price_map=None,positions=None,research=None,eq=None,eia_key=''):
    typ=str(asset_type); out={'Macro_Regime':macro_regime(macro or {})}
    if typ=='Acción' and fund:
        peer=(research or {}).get('Peers',{}).get('Peer_Rank_Score',np.nan) if research else np.nan
        out['Valuation']=valuation_workstation(fund,str(row.get('Equity_Model_Key','generic')),peer)
        out['Forensics']=financial_forensics(fund)
    if typ=='Commodity': out['Commodity']=commodity_institutional_snapshot(ticker,eia_key=eia_key)
    if price_map:
        out['Portfolio_Fit']=single_asset_portfolio_fit(ticker,price_map,positions)
        try: out['Factor_Exposure']=factor_exposures(ticker,price_map)
        except Exception: out['Factor_Exposure']=None
    out['Thesis']=build_thesis(ticker,row,eq or {},research,out.get('Macro_Regime',{}),out.get('Forensics',{}),out.get('Valuation',{}),out.get('Commodity',{}))
    return out
