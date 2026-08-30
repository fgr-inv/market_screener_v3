"""V11 free/public data connectors and source contracts.

All connectors are best-effort and preserve provenance. Network failures return structured
missing states instead of fabricated values. No paid provider is required.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
import io, json, math, zipfile
import pandas as pd
import requests

UA='MarketScreenerPro/11.0 research contact: user@example.com'
TIMEOUT=12

@dataclass
class ProviderResult:
    provider:str
    ok:bool
    data:Any=None
    error:str=''
    observed_at:str=''
    fetched_at:str=''
    note:str=''
    def to_dict(self): return asdict(self)

def _now(): return datetime.now(timezone.utc).isoformat()
def _get(url,params=None,headers=None,timeout=TIMEOUT):
    h={'User-Agent':UA,'Accept-Encoding':'gzip, deflate'}
    if headers:h.update(headers)
    return requests.get(url,params=params,headers=h,timeout=timeout)

def sec_company_tickers():
    try:
        r=_get('https://www.sec.gov/files/company_tickers.json'); r.raise_for_status()
        d=r.json(); rows=[]
        for v in d.values(): rows.append({'ticker':str(v.get('ticker','')).upper(),'cik':str(v.get('cik_str','')).zfill(10),'title':v.get('title')})
        return ProviderResult('SEC',True,pd.DataFrame(rows),fetched_at=_now())
    except Exception as e:return ProviderResult('SEC',False,error=str(e),fetched_at=_now())

def sec_submissions(cik:str):
    cik=str(cik).zfill(10)
    try:
        r=_get(f'https://data.sec.gov/submissions/CIK{cik}.json'); r.raise_for_status(); d=r.json()
        recent=pd.DataFrame(d.get('filings',{}).get('recent',{}))
        return ProviderResult('SEC submissions',True,recent,fetched_at=_now(),note='Official SEC submissions; filing dates are point-in-time.')
    except Exception as e:return ProviderResult('SEC submissions',False,error=str(e),fetched_at=_now())

def sec_recent_forms(cik:str, forms=('4','13F-HR','NPORT-P','10-Q','10-K','8-K')):
    res=sec_submissions(cik)
    if not res.ok:return res
    df=res.data
    if df.empty or 'form' not in df:return ProviderResult('SEC submissions',True,pd.DataFrame(),fetched_at=_now())
    out=df[df['form'].isin(forms)].copy()
    keep=[c for c in ['filingDate','reportDate','acceptanceDateTime','accessionNumber','form','primaryDocument'] if c in out]
    return ProviderResult('SEC submissions',True,out[keep],fetched_at=_now())

def sec_quarterly_dataset_url(dataset:str,year:int,quarter:int):
    """Official SEC data-set archive URL builder. dataset: form13f|insider|nport.
    SEC archive naming can change; caller should treat 404 as unavailable, never as neutral.
    """
    ds=dataset.lower()
    names={
        'form13f':f'{year}q{quarter}_form13f.zip',
        'insider':f'{year}q{quarter}_insider_transactions.zip',
        'nport':f'{year}q{quarter}_nport.zip',
    }
    return f'https://www.sec.gov/files/dera/data/{names.get(ds,"")}' if ds in names else ''

def finra_short_sale_volume(symbol:str,date=None):
    """Best-effort FINRA public-data query contract.
    Returns missing when API changes or unavailable. Short-sale volume is NOT short interest.
    """
    params={'symbol':symbol.upper()}
    if date:params['date']=pd.Timestamp(date).strftime('%Y-%m-%d')
    candidates=[
        'https://api.finra.org/data/group/otcMarket/name/regShoDaily',
        'https://api.finra.org/data/group/otcMarket/name/shortSaleVolume',
    ]
    for url in candidates:
        try:
            r=_get(url,params=params,headers={'Accept':'application/json'}); 
            if r.ok:
                js=r.json()
                return ProviderResult('FINRA',True,pd.DataFrame(js if isinstance(js,list) else [js]),fetched_at=_now(),note='Daily short-sale volume; not equivalent to short interest.')
        except Exception: pass
    return ProviderResult('FINRA',False,error='Public FINRA query unavailable or schema changed.',fetched_at=_now(),note='Keep short-sale volume separate from short interest.')

def coinmetrics_community(asset='btc',metrics=None,start_time=None):
    metrics=metrics or ['PriceUSD','CapMrktCurUSD','TxCnt','AdrActCnt','HashRate','FeeTotUSD','IssTotNtv']
    params={'assets':asset.lower(),'metrics':','.join(metrics),'frequency':'1d','page_size':100}
    if start_time:params['start_time']=pd.Timestamp(start_time).strftime('%Y-%m-%d')
    try:
        r=_get('https://community-api.coinmetrics.io/v4/timeseries/asset-metrics',params=params); r.raise_for_status()
        js=r.json(); return ProviderResult('Coin Metrics Community',True,pd.DataFrame(js.get('data',[])),fetched_at=_now(),note='Community coverage/rate limits apply.')
    except Exception as e:return ProviderResult('Coin Metrics Community',False,error=str(e),fetched_at=_now())

def mempool_space(endpoint='mempool'):
    allowed={'mempool':'/api/mempool','fees':'/api/v1/fees/recommended','difficulty':'/api/v1/difficulty-adjustment','hashrate':'/api/v1/mining/hashrate/3m'}
    if endpoint not in allowed:return ProviderResult('mempool.space',False,error='unsupported endpoint',fetched_at=_now())
    try:
        r=_get('https://mempool.space'+allowed[endpoint]); r.raise_for_status(); return ProviderResult('mempool.space',True,r.json(),fetched_at=_now())
    except Exception as e:return ProviderResult('mempool.space',False,error=str(e),fetched_at=_now())

def bls_timeseries(series_ids,start_year=None,end_year=None,api_key=''):
    end_year=end_year or datetime.now().year; start_year=start_year or max(2000,end_year-10)
    payload={'seriesid':list(series_ids),'startyear':str(start_year),'endyear':str(end_year)}
    if api_key:payload['registrationkey']=api_key
    try:
        r=requests.post('https://api.bls.gov/publicAPI/v2/timeseries/data/',json=payload,timeout=TIMEOUT); r.raise_for_status(); js=r.json()
        rows=[]
        for s in js.get('Results',{}).get('series',[]):
            for x in s.get('data',[]):
                rows.append({'series_id':s.get('seriesID'),'year':x.get('year'),'period':x.get('period'),'periodName':x.get('periodName'),'value':x.get('value'),'footnotes':x.get('footnotes')})
        return ProviderResult('BLS',True,pd.DataFrame(rows),fetched_at=_now())
    except Exception as e:return ProviderResult('BLS',False,error=str(e),fetched_at=_now())

def bea_request(dataset='NIPA',table='T10101',api_key='samplekey',year='X'):
    params={'UserID':api_key,'method':'GetData','datasetname':dataset,'TableName':table,'Year':year,'ResultFormat':'JSON'}
    try:
        r=_get('https://apps.bea.gov/api/data/',params=params); r.raise_for_status(); return ProviderResult('BEA',True,r.json(),fetched_at=_now(),note='BEA API key can be obtained free; sample key may be rate-limited.')
    except Exception as e:return ProviderResult('BEA',False,error=str(e),fetched_at=_now())

def treasury_fiscal_data(endpoint='DebtToPenny',page_size=100):
    url=f'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/{endpoint}'
    try:
        r=_get(url,params={'page[size]':page_size}); r.raise_for_status(); js=r.json(); return ProviderResult('US Treasury FiscalData',True,pd.DataFrame(js.get('data',[])),fetched_at=_now())
    except Exception as e:return ProviderResult('US Treasury FiscalData',False,error=str(e),fetched_at=_now())

def gdelt_doc(query,maxrecords=25,timespan='7d'):
    params={'query':query,'mode':'artlist','maxrecords':maxrecords,'format':'json','timespan':timespan}
    try:
        r=_get('https://api.gdeltproject.org/api/v2/doc/doc',params=params); r.raise_for_status(); js=r.json(); return ProviderResult('GDELT',True,pd.DataFrame(js.get('articles',[])),fetched_at=_now())
    except Exception as e:return ProviderResult('GDELT',False,error=str(e),fetched_at=_now())

def free_source_catalog():
    return pd.DataFrame([
      ('SEC EDGAR/XBRL','Equities/ETF','No key','filings, company facts, submissions, Form 4/13F/N-PORT filing discovery'),
      ('FINRA public data','Equities','No key','short-sale volume / OTC market datasets where public; not short interest substitute'),
      ('FRED/ALFRED','Macro/Rates/Credit','Free key','macro, rates, credit spreads, vintage observations'),
      ('BLS Public API','Macro','No key / optional free key','CPI/PPI/employment/productivity'),
      ('BEA API','Macro','Free key','GDP, income, corporate/industry accounts'),
      ('US Treasury FiscalData','Macro/Rates','No key','debt, TGA/fiscal series, auctions where exposed'),
      ('EIA Open Data','Energy','Free key','oil/gas inventories, production, flows, storage'),
      ('USDA public data','Agriculture','Public/free access varies','crop, stocks, exports, WASDE/NASS feeds'),
      ('NOAA/NWS','Weather/Energy/Agriculture','No key for many endpoints','weather observations/forecasts'),
      ('CFTC','Futures/FX','No key','COT positioning'),
      ('CoinGecko','Crypto','Demo/free key','market cap, supply, volume, metadata'),
      ('Coin Metrics Community','Crypto','No key','community on-chain/network metrics'),
      ('mempool.space','BTC','No key','mempool, fees, difficulty, mining/hashrate endpoints'),
      ('DefiLlama','Crypto/DeFi','No key','TVL, stablecoins, protocols/chains'),
      ('Binance/Bybit/OKX','Crypto derivatives','No key','funding, OI, basis where public'),
      ('ClinicalTrials.gov','Biotech','No key','trial phase/status/timing'),
      ('openFDA','Healthcare','No key/basic','labels/context'),
      ('GDELT','News/Geopolitics','No key','global news/event attention; not authoritative sentiment'),
    ],columns=['Provider','Coverage','Access','Professional use'])
