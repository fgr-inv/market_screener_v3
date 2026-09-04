import time
import pandas as pd
import requests
import yfinance as yf

from core.institutional_providers import provider_config, fmp_equity_snapshot
from core.commodity_data import eia_v2_series
from core.free_specialist_data import sec_specialist_snapshot, clinicaltrials_company_snapshot, openfda_company_snapshot
from core.free_market_providers import (
    coingecko_headers,
    binance_derivatives_snapshot,
    bybit_derivatives_snapshot,
    okx_derivatives_snapshot,
)
from core.monitoring import log_exception


def _check(name, fn):
    start=time.time()
    try:
        ok,detail=fn()
        return {'Provider':name,'Status':'OK' if ok else 'DEGRADED','Latency ms':round((time.time()-start)*1000),'Detail':detail}
    except Exception as exc:
        log_exception('provider_health_check_error',exc,provider=name)
        return {'Provider':name,'Status':'DOWN','Latency ms':round((time.time()-start)*1000),
                'Detail':'Sin respuesta; ver logs del servidor'}


def provider_health():
    rows=[]
    rows.append(_check('Yahoo Finance',lambda: (not yf.download('SPY',period='5d',progress=False,auto_adjust=True).empty,'SPY 5d')))
    rows.append(_check('FRED',lambda: (requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS',timeout=8).ok,'FEDFUNDS')))
    rows.append(_check('CoinGecko',lambda: (requests.get('https://api.coingecko.com/api/v3/global',headers=coingecko_headers(),timeout=8).ok,'global / demo-key aware')))
    rows.append(_check('Binance',lambda: (bool(binance_derivatives_snapshot('BTCUSDT').get('available')),'BTC public derivatives')))
    rows.append(_check('Bybit',lambda: (bool(bybit_derivatives_snapshot('BTCUSDT').get('available')),'BTC public derivatives')))
    rows.append(_check('OKX',lambda: (bool(okx_derivatives_snapshot('BTC').get('available')),'BTC public derivatives')))
    rows.append(_check('CFTC',lambda: (requests.get('https://www.cftc.gov/dea/newcot/deafut.txt',timeout=8).ok,'futures-only COT')))
    rows.append(_check('SEC EDGAR',lambda: (bool(sec_specialist_snapshot('AAPL').get('available')),'AAPL Company Facts / XBRL')))
    rows.append(_check('ClinicalTrials.gov',lambda: (requests.get('https://clinicaltrials.gov/api/v2/studies?pageSize=1&format=json',timeout=8).ok,'API v2')))
    rows.append(_check('openFDA',lambda: (requests.get('https://api.fda.gov/drug/label.json?limit=1',timeout=8).ok,'drug labels')))
    cfg=provider_config()
    if cfg.get('EIA_API_KEY'):
        rows.append(_check('EIA',lambda: (not eia_v2_series('petroleum/sum/sndw','WCESTUS1',length=2).empty,'WCESTUS1')))
    if cfg.get('FMP_API_KEY'):
        rows.append(_check('FMP',lambda: (bool(fmp_equity_snapshot('AAPL').get('available')),'AAPL fundamentals')))
    return pd.DataFrame(rows)
