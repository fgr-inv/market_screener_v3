
from io import StringIO
from pathlib import Path
from datetime import datetime, timedelta
import json
import os
import time
import re
import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from core.config import SECTOR_ETFS, MACRO_SYMBOLS, CROSS_ASSET, ASSET_PRESETS
from core.monitoring import log_event, log_exception
from core.cache_policy import LIVE_PRICE_TTL, HISTORICAL_PRICE_TTL, PRICE_DISK_MAX_AGE_MINUTES
from core.emerging_trends import cap_segment

ROOT = Path(__file__).resolve().parents[1]
PRICE_CACHE = ROOT/'data'/'cache'/'prices'
LIVE_QUOTE_CACHE = ROOT/'data'/'cache'/'live_quotes'
PRICE_CACHE.mkdir(parents=True,exist_ok=True)
LIVE_QUOTE_CACHE.mkdir(parents=True,exist_ok=True)

def get_sector_etfs(): return SECTOR_ETFS.copy()
def get_macro_symbols(): return MACRO_SYMBOLS.copy()
def get_cross_asset_symbols(): return CROSS_ASSET.copy()
def get_asset_presets(): return ASSET_PRESETS.copy()
def get_market_symbols(): return ["SPY","QQQ","IWM","RSP","^VIX"]

def _fallback_universe():
    out=pd.read_csv(ROOT/"data"/"fallback_universe.csv")
    out['Universe Source']='Curated Liquid Supplemental'
    out['Market Cap']=pd.NA
    out['Cap Segment']='Unknown'
    return out


def _secret(name,default=''):
    try:
        value=st.secrets.get(name,default)
        if value is not None and str(value).strip(): return str(value).strip()
    except Exception:
        pass
    return str(os.getenv(name,default) or '').strip()


def _retry_session():
    session=requests.Session()
    retry=Retry(total=2,connect=2,read=2,backoff_factor=.7,
                status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(['GET']))
    session.mount('https://',HTTPAdapter(max_retries=retry))
    session.headers.update({'User-Agent':'market-screener/11.39'})
    return session

def _fetch_wikipedia(url,symbol_col,sector_col=None,universe_source='Public index constituents'):
    headers={"User-Agent":"Mozilla/5.0 AppleWebKit/537.36 Chrome/124 Safari/537.36"}
    r=requests.get(url,headers=headers,timeout=20); r.raise_for_status()
    tables=pd.read_html(StringIO(r.text))
    table=next((t.copy() for t in tables if symbol_col in t.columns),None)
    if table is None: raise ValueError(f"No se encontró columna {symbol_col}")
    out=pd.DataFrame()
    out["Ticker"]=table[symbol_col].astype(str).str.replace(".","-",regex=False).str.strip()
    out["Sector"]=table[sector_col].astype(str) if sector_col and sector_col in table.columns else "Unknown"
    out['Universe Source']=universe_source
    return out.dropna().drop_duplicates("Ticker")


def _combine_universe_frames(*frames):
    usable=[frame.copy() for frame in frames if frame is not None and not frame.empty and 'Ticker' in frame]
    if not usable: return pd.DataFrame(columns=['Ticker','Sector','Universe Source'])
    out=pd.concat(usable,ignore_index=True)
    out['Ticker']=out['Ticker'].astype(str).str.upper().str.strip()
    out=out[out['Ticker']!=''].drop_duplicates('Ticker',keep='first')
    if 'Sector' not in out: out['Sector']='Unknown'
    if 'Universe Source' not in out: out['Universe Source']='Unknown'
    if 'Market Cap' not in out: out['Market Cap']=pd.NA
    if 'Cap Segment' not in out: out['Cap Segment']='Unknown'
    out['Cap Segment']=[cap_segment(cap,source) for cap,source in zip(out['Market Cap'],out['Universe Source'])]
    columns=['Ticker','Sector','Universe Source','Market Cap','Cap Segment']
    if 'Exchange' in out: columns.append('Exchange')
    return out[columns]


@st.cache_data(ttl=21600,show_spinner=False)
def load_fmp_cap_universe(max_per_segment=250):
    """Best-effort US mid/small-cap supplement from the configured FMP plan.

    S&P 400/600 remain the provider-independent baseline. This source only
    broadens coverage when the company-screener endpoint is available.
    """
    key=_secret('FMP_API_KEY')
    columns=['Ticker','Sector','Universe Source','Market Cap','Cap Segment','Exchange']
    if not key: return pd.DataFrame(columns=columns)
    rows=[]; session=_retry_session()
    segments=(('FMP US Mid Cap',2_000_000_000,10_000_000_000,'Mid Cap'),
              ('FMP US Small Cap',300_000_000,2_000_000_000,'Small Cap'))
    for source,lower,upper,label in segments:
        try:
            response=session.get('https://financialmodelingprep.com/stable/company-screener',params={
                'marketCapMoreThan':lower,'marketCapLowerThan':upper,'priceMoreThan':2,
                'volumeMoreThan':100000,'country':'US','isEtf':'false','isFund':'false',
                'isActivelyTrading':'true','limit':int(max_per_segment),'apikey':key,
            },timeout=25)
            response.raise_for_status(); payload=response.json()
            if not isinstance(payload,list): payload=[]
            for item in payload[:int(max_per_segment)]:
                ticker=str(item.get('symbol') or '').upper().replace('.','-').strip()
                market_cap=pd.to_numeric(item.get('marketCap'),errors='coerce')
                exchange=str(item.get('exchangeShortName') or item.get('exchange') or '').upper()
                if not ticker or pd.isna(market_cap) or not (lower<=float(market_cap)<upper): continue
                if exchange and exchange not in {'NASDAQ','NYSE','AMEX','NYSE AMERICAN'}: continue
                rows.append({'Ticker':ticker,'Sector':str(item.get('sector') or 'Unknown'),
                             'Universe Source':source,'Market Cap':float(market_cap),
                             'Cap Segment':label,'Exchange':exchange or 'US'})
        except Exception as exc:
            log_exception('fmp_cap_universe_error',exc,segment=label)
    result=pd.DataFrame(rows,columns=columns).drop_duplicates('Ticker') if rows else pd.DataFrame(columns=columns)
    log_event('fmp_cap_universe',rows=len(result),mid_caps=sum(result.get('Cap Segment',[])=='Mid Cap'),
              small_caps=sum(result.get('Cap Segment',[])=='Small Cap'))
    return result

@st.cache_data(ttl=21600,show_spinner=False)
def load_universe(name):
    fb=_fallback_universe()
    if name=="Fallback líquido":
        return fb[["Ticker","Sector","Universe Source"]].copy()
    if name=="US Expanded Liquid":
        return _combine_universe_frames(
            load_universe('S&P 500'),load_universe('Nasdaq 100'),
            load_universe('S&P MidCap 400'),load_universe('S&P SmallCap 600'),
            load_fmp_cap_universe(),
            load_universe('Fallback líquido'))
    try:
        if name=="S&P 500":
            return _combine_universe_frames(_fetch_wikipedia("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies","Symbol","GICS Sector",'S&P 500'))
        if name=="S&P MidCap 400":
            return _combine_universe_frames(_fetch_wikipedia("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies","Symbol","GICS Sector",'S&P MidCap 400'))
        if name=="S&P SmallCap 600":
            return _combine_universe_frames(_fetch_wikipedia("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies","Symbol","GICS Sector",'S&P SmallCap 600'))
        if name=="Nasdaq 100":
            headers={"User-Agent":"Mozilla/5.0 AppleWebKit/537.36 Chrome/124 Safari/537.36"}
            r=requests.get("https://en.wikipedia.org/wiki/Nasdaq-100",headers=headers,timeout=20); r.raise_for_status()
            for t in pd.read_html(StringIO(r.text)):
                for col in ["Ticker","Symbol"]:
                    if col in t.columns:
                        return _combine_universe_frames(pd.DataFrame({
                            "Ticker":t[col].astype(str).str.replace(".","-",regex=False).str.strip(),
                            "Sector":t["GICS Sector"].astype(str) if "GICS Sector" in t.columns else "Unknown",
                            "Universe Source":'Nasdaq 100',
                        }).drop_duplicates("Ticker"))
    except Exception as exc:
        log_exception('universe_fetch_error',exc,universe=name)
    if name=="Nasdaq 100":
        return _combine_universe_frames(fb[fb["Nasdaq100"]==True].copy())
    if name in {'S&P MidCap 400','S&P SmallCap 600'}:
        return pd.DataFrame(columns=['Ticker','Sector','Universe Source'])
    return _combine_universe_frames(fb.copy())

def build_asset_universe(asset_type,preset=None,custom_text=""):
    if asset_type=="Acciones":
        raise ValueError("Para acciones usá load_universe().")
    if asset_type=="Personalizado":
        ticks=[x.strip().upper() for x in custom_text.replace("\n",",").split(",") if x.strip()]
        return pd.DataFrame({"Ticker":list(dict.fromkeys(ticks)),"Sector":"Personalizado","Asset_Type":"Personalizado"})
    presets=get_asset_presets().get(asset_type,{})
    if preset not in presets:
        return pd.DataFrame(columns=["Ticker","Sector","Asset_Type"])
    return pd.DataFrame({"Ticker":presets[preset],"Sector":asset_type,"Asset_Type":asset_type})

def _extract(data,tickers):
    out={}
    if not tickers: return out
    if len(tickers)==1:
        t=tickers[0]
        if isinstance(data.columns,pd.MultiIndex):
            if t in set(data.columns.get_level_values(0)): out[t]=data[t].dropna(how="all").copy()
        else:
            out[t]=data.dropna(how="all").copy()
        return out
    if not isinstance(data.columns,pd.MultiIndex): return out
    lv=set(data.columns.get_level_values(0))
    for t in tickers:
        if t in lv: out[t]=data[t].dropna(how="all").copy()
    return out

def _cache_path(ticker,period):
    safe=re.sub(r'[^A-Za-z0-9._-]+','_',ticker)
    return PRICE_CACHE/f'{safe}_{period}.parquet'


def _read_price_cache(ticker,period,max_age_minutes):
    path=_cache_path(ticker,period)
    if not path.exists(): return None
    age=datetime.now()-datetime.fromtimestamp(path.stat().st_mtime)
    if age>timedelta(minutes=max_age_minutes): return None
    try:
        df=pd.read_parquet(path)
        if 'Date' in df.columns:
            df['Date']=pd.to_datetime(df['Date']); df=df.set_index('Date')
        return df if not df.empty else None
    except Exception as exc:
        log_exception('price_cache_read_error',exc,ticker=ticker,period=period)
        return None


def _write_price_cache(ticker,period,df):
    try:
        path=_cache_path(ticker,period)
        x=df.copy().reset_index()
        x.to_parquet(path,index=False)
    except Exception as exc:
        log_exception('price_cache_write_error',exc,ticker=ticker,period=period)


@st.cache_data(ttl=HISTORICAL_PRICE_TTL,show_spinner=False)
def download_prices(tickers,period="2y",batch_size=80,max_age_minutes=PRICE_DISK_MAX_AGE_MINUTES,
                    max_single_fallback=None):
    tickers=[t for t in dict.fromkeys(tickers) if t]
    out={}; missing=[]; single_fallbacks=0
    for t in tickers:
        cached=_read_price_cache(t,period,max_age_minutes)
        if cached is not None: out[t]=cached
        else: missing.append(t)
    for start in range(0,len(missing),batch_size):
        batch=missing[start:start+batch_size]
        try:
            data=yf.download(batch,period=period,interval='1d',group_by='ticker',auto_adjust=True,threads=True,progress=False)
            got=_extract(data,batch); out.update(got)
            for t,df in got.items(): _write_price_cache(t,period,df)
            # yfinance can return a partial batch when one of its internal
            # SQLite cache writes is briefly locked. Retry only missing names,
            # serially and without provider threads.
            unresolved=[t for t in batch if t not in got]
            for t in unresolved:
                if max_single_fallback is not None and single_fallbacks>=int(max_single_fallback): break
                single_fallbacks+=1
                for attempt in range(3):
                    try:
                        single=yf.download(t,period=period,interval='1d',auto_adjust=True,
                                           progress=False,threads=False)
                        if single is not None and not single.empty:
                            df=single.dropna(how='all').copy(); out[t]=df; _write_price_cache(t,period,df)
                        break
                    except Exception as exc:
                        locked='database is locked' in str(exc).lower()
                        if not locked or attempt>=2:
                            log_exception('yahoo_single_download_error',exc,ticker=t,period=period)
                            break
                        time.sleep(.25*(2**attempt))
        except Exception as exc:
            log_exception('yahoo_batch_download_error',exc,batch_size=len(batch),period=period)
            for t in batch:
                if max_single_fallback is not None and single_fallbacks>=int(max_single_fallback): break
                single_fallbacks+=1
                try:
                    single=yf.download(t,period=period,interval='1d',auto_adjust=True,progress=False)
                    if single is not None and not single.empty:
                        df=single.dropna(how='all').copy(); out[t]=df; _write_price_cache(t,period,df)
                except Exception as exc:
                    log_exception('yahoo_single_download_error',exc,ticker=t,period=period)
    log_event('price_download',requested=len(tickers),returned=len(out),missing=len(tickers)-len(out),period=period,
              single_fallbacks=single_fallbacks,
              single_fallback_limit='UNBOUNDED' if max_single_fallback is None else int(max_single_fallback))
    return out


def download_intraday_prices(tickers,period='5d',interval='5m'):
    """One bounded batch for the background event detector; no per-symbol retry."""
    tickers=[t for t in dict.fromkeys(str(x).upper().strip() for x in tickers) if t]
    if not tickers: return {},{'status':'UNAVAILABLE','source':'Yahoo Finance 5m batch'}
    try:
        data=yf.download(tickers,period=period,interval=interval,group_by='ticker',auto_adjust=True,
                         threads=True,progress=False)
        out=_extract(data,tickers)
        status='CURRENT' if out else 'FAILED'
        log_event('intraday_monitor_batch',requested=len(tickers),returned=len(out),status=status)
        return out,{'status':status,'coverage_status':'COMPLETE' if len(out)==len(tickers) else 'PARTIAL',
                    'source':f'Yahoo Finance {interval} batch'}
    except Exception as exc:
        log_exception('intraday_monitor_batch_error',exc,requested=len(tickers),interval=interval)
        return {},{'status':'FAILED','source':f'Yahoo Finance {interval} batch','error':type(exc).__name__}



def _live_quote_path(ticker):
    safe=re.sub(r'[^A-Za-z0-9._-]+','_',ticker)
    return LIVE_QUOTE_CACHE/f'{safe}.json'


def _live_quote_lock_path(ticker):
    return _live_quote_path(ticker).with_suffix('.lock')


def _read_live_quote_cache(ticker, ttl_seconds=LIVE_PRICE_TTL):
    """Read the process-independent quote cache used by all Streamlit sessions."""
    path=_live_quote_path(ticker)
    if not path.exists():
        return None
    try:
        payload=json.loads(path.read_text(encoding='utf-8'))
        ts=float(payload.get('timestamp',0))
        price=float(payload.get('price'))
        if price<=0 or (time.time()-ts)>float(ttl_seconds):
            return None
        return price
    except Exception as exc:
        log_exception('live_quote_cache_read_error',exc,ticker=ticker)
        return None


def _write_live_quote_cache(ticker, price):
    """Atomically persist a quote so other users/processes can reuse it."""
    path=_live_quote_path(ticker)
    tmp=path.with_suffix(f'.{os.getpid()}.tmp')
    try:
        payload={'ticker':ticker,'price':float(price),'timestamp':time.time()}
        tmp.write_text(json.dumps(payload,separators=(',',':')),encoding='utf-8')
        os.replace(tmp,path)
    except Exception as exc:
        log_exception('live_quote_cache_write_error',exc,ticker=ticker)
        try:
            if tmp.exists(): tmp.unlink()
        except Exception:
            pass


def _acquire_quote_lock(ticker, wait_seconds=3.0, stale_seconds=20.0):
    """Best-effort cross-session/process request de-duplication using a lock file.

    Returns True when this caller owns the provider refresh. Other callers wait briefly
    and then consume the quote written by the owner instead of hitting Yahoo again.
    """
    lock=_live_quote_lock_path(ticker)
    deadline=time.time()+max(0.0,float(wait_seconds))
    while time.time()<=deadline:
        try:
            fd=os.open(str(lock),os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            with os.fdopen(fd,'w') as fh:
                fh.write(f'{os.getpid()} {time.time()}')
            return True
        except FileExistsError:
            try:
                if (time.time()-lock.stat().st_mtime)>stale_seconds:
                    lock.unlink(missing_ok=True)
                    continue
            except Exception:
                pass
            time.sleep(0.05)
        except Exception as exc:
            log_exception('live_quote_lock_error',exc,ticker=ticker)
            return False
    return False


def _release_quote_lock(ticker):
    try:
        _live_quote_lock_path(ticker).unlink(missing_ok=True)
    except Exception as exc:
        log_exception('live_quote_unlock_error',exc,ticker=ticker)


def _fetch_live_price_provider(ticker):
    """Hit the external provider only after shared caches/locks are exhausted."""
    try:
        fi=yf.Ticker(ticker).fast_info or {}
        for key in ('last_price','lastPrice','regular_market_price','previous_close'):
            value=fi.get(key) if hasattr(fi,'get') else None
            if value is not None:
                try:
                    value=float(value)
                    if value>0:
                        return value
                except (TypeError,ValueError):
                    pass
    except Exception as exc:
        log_exception('live_price_fast_info_error',exc,ticker=ticker)
    try:
        short=yf.download(ticker,period='5d',interval='1m',auto_adjust=True,progress=False,threads=False)
        if short is not None and not short.empty and 'Close' in short:
            close=short['Close'].dropna()
            if not close.empty:
                value=close.iloc[-1]
                if hasattr(value,'iloc'):
                    value=value.iloc[-1]
                value=float(value)
                if value>0:
                    return value
    except Exception as exc:
        log_exception('live_price_fallback_error',exc,ticker=ticker)
    return None


def _get_live_price_shared(ticker):
    t=str(ticker or '').upper().strip()
    if not t:
        return None

    # Persistent cache is shared by all users on the same application filesystem.
    cached=_read_live_quote_cache(t)
    if cached is not None:
        log_event('live_quote_cache_hit',ticker=t,layer='disk_shared')
        return cached

    owns_lock=_acquire_quote_lock(t)
    if not owns_lock:
        # Another request is most likely refreshing this ticker. Re-check shared cache
        # once more before considering a provider call.
        cached=_read_live_quote_cache(t)
        if cached is not None:
            log_event('live_quote_cache_hit',ticker=t,layer='deduplicated_wait')
            return cached
    try:
        # Double-check after acquiring the lock: another caller may have refreshed it.
        cached=_read_live_quote_cache(t)
        if cached is not None:
            return cached
        value=_fetch_live_price_provider(t)
        if value is not None:
            _write_live_quote_cache(t,value)
            log_event('live_quote_provider_refresh',ticker=t)
        return value
    finally:
        if owns_lock:
            _release_quote_lock(t)


@st.cache_data(ttl=LIVE_PRICE_TTL, show_spinner=False)
def get_live_price(ticker):
    """Return a 5-minute quote shared across users before calling Yahoo.

    There are two cache layers: Streamlit's process-wide cache and a persistent
    per-ticker disk cache. A small lock file de-duplicates simultaneous refreshes, so
    many users requesting AMD at once normally generate one provider request.
    """
    return _get_live_price_shared(ticker)

def classify_symbol(ticker):
    """Classify common symbols without a provider request during page render.

    Explicit suffixes and the configured ETF universe cover the built-in
    symbols. Plain exchange tickers default to equities; Asset Analysis still
    exposes a manual type override for uncommon instruments.
    """
    t=str(ticker or '').upper().strip()
    if not t: return "Otro"
    if t.endswith("-USD"): return "Cripto"
    if t.endswith("=X"): return "Forex"
    if t.endswith("=F"): return "Commodity"
    if t.startswith("^"):
        return "Bono/Tasa" if t in {"^TNX","^TYX","^FVX","^IRX"} else "Índice"
    known_etfs={symbol for group in ASSET_PRESETS.get('ETFs',{}).values() for symbol in group}
    known_etfs.update(SECTOR_ETFS.values())
    known_etfs.update({'IBIT','FBTC','BITB','ARKB','GBTC','SMH','SOXX','XBI','KRE','VNQ','DIA'})
    if t in known_etfs: return "ETF"
    if re.fullmatch(r'[A-Z][A-Z0-9.-]{0,11}',t): return "Acción"
    return "Otro"
