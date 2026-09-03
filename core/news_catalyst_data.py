"""Bounded, multi-source news and SEC filing collection for the agent desk."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
import re
import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


FMP_BASE='https://financialmodelingprep.com'
SEC_TICKERS_URL='https://www.sec.gov/files/company_tickers.json'
SEC_SUBMISSIONS='https://data.sec.gov/submissions/CIK{cik}.json'
SEC_FORMS={'8-K','8-K/A','10-Q','10-Q/A','10-K','10-K/A','6-K','6-K/A','20-F','20-F/A','40-F','S-1','S-1/A','S-3','S-3/A','424B2','424B3','424B4','424B5','DEF 14A'}


def _secret(name):
    value=os.getenv(name,'')
    if value: return str(value).strip()
    try:
        import streamlit as st
        return str(st.secrets.get(name,'') or '').strip()
    except Exception:
        return ''


def _session(user_agent='market-screener/11.36'):
    session=requests.Session()
    retry=Retry(total=3,connect=3,read=3,backoff_factor=.5,
                status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(['GET']))
    session.mount('https://',HTTPAdapter(max_retries=retry))
    session.headers.update({'User-Agent':user_agent,'Accept-Encoding':'gzip, deflate'})
    return session


def _request_json(url,params=None,headers=None,timeout=18):
    response=_session().get(url,params=params or {},headers=headers or {},timeout=timeout)
    response.raise_for_status(); return response.json()


def _timestamp(value):
    if value in (None,''): return None
    try:
        if isinstance(value,(int,float)):
            return pd.Timestamp(value,unit='s',tz='UTC').isoformat()
        ts=pd.Timestamp(value)
        if ts.tzinfo is None: ts=ts.tz_localize('UTC')
        return ts.tz_convert('UTC').isoformat()
    except Exception:
        return None


def _story_id(ticker,title,url,published_at,source_type):
    raw='|'.join([str(ticker).upper(),str(title).strip().lower(),str(url or '').strip(),
                  str(published_at or '')[:10],str(source_type)])
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:28]


def _symbols(value):
    if isinstance(value,(list,tuple,set)): items=value
    else: items=str(value or '').replace(';',',').split(',')
    return [str(item).upper().strip() for item in items if str(item).strip()]


def normalize_story(raw,default_ticker='',provider='FMP',source_type='NEWS',primary_source=False):
    raw=raw or {}; symbols=_symbols(raw.get('symbol') or raw.get('symbols') or raw.get('tickers') or default_ticker)
    ticker=(symbols[0] if symbols else str(default_ticker).upper().strip())
    title=str(raw.get('title') or raw.get('headline') or raw.get('primaryDocDescription') or '').strip()
    summary=str(raw.get('text') or raw.get('summary') or raw.get('description') or '').strip()
    publisher=str(raw.get('publisher') or raw.get('site') or raw.get('source') or provider).strip()
    published=_timestamp(raw.get('publishedDate') or raw.get('published_at') or raw.get('pubDate') or
                         raw.get('providerPublishTime') or raw.get('acceptanceDateTime') or raw.get('filingDate'))
    url=str(raw.get('url') or raw.get('link') or '').strip()
    if not ticker or not title: return None
    return {'story_id':_story_id(ticker,title,url,published,source_type),'ticker':ticker,'title':title,
            'summary':summary[:1200],'publisher':publisher,'published_at':published,'url':url,
            'provider':provider,'source_type':source_type,'primary_source':bool(primary_source),
            'symbols':symbols or [ticker]}


def _chunks(values,size):
    values=list(values)
    for start in range(0,len(values),size): yield values[start:start+size]


def fetch_fmp_stories(tickers,limit_per_batch=100,get_json=None):
    """Fetch stock news and company press releases in bounded symbol batches."""
    tickers=list(dict.fromkeys(str(t).upper().strip() for t in tickers if str(t).strip()))
    key=_secret('FMP_API_KEY')
    if not key: return [],{'status':'NOT_CONFIGURED','provider':'FMP','requests':0}
    get_json=get_json or _request_json; stories=[]; requests_made=0; failures=[]
    for batch in _chunks(tickers,20):
        symbols=','.join(batch)
        endpoints=[('stable/news/stock',False),('stable/news/press-releases',True)]
        for endpoint,press_release in endpoints:
            try:
                data=get_json(f'{FMP_BASE}/{endpoint}',params={'symbols':symbols,'page':0,'limit':limit_per_batch,'apikey':key})
                requests_made+=1
                for raw in data if isinstance(data,list) else []:
                    story=normalize_story(raw,provider='FMP',source_type='PRESS_RELEASE' if press_release else 'NEWS',
                                          primary_source=press_release)
                    if story and story['ticker'] in batch: stories.append(story)
            except Exception as exc:
                failures.append(f'{endpoint}:{type(exc).__name__}')
        # Some older/free plans expose only the legacy stock-news route.
        if not any(story['ticker'] in batch and story['source_type']=='NEWS' for story in stories):
            try:
                data=get_json(f'{FMP_BASE}/api/v3/stock_news',params={'tickers':symbols,'page':0,'limit':limit_per_batch,'apikey':key})
                requests_made+=1
                for raw in data if isinstance(data,list) else []:
                    story=normalize_story(raw,provider='FMP',source_type='NEWS')
                    if story and story['ticker'] in batch: stories.append(story)
            except Exception as exc:
                failures.append(f'legacy:{type(exc).__name__}')
    status='CURRENT' if stories else 'FAILED' if failures else 'NO_DATA'
    return stories,{'status':status,'provider':'FMP','requests':requests_made,'failures':failures[:6]}


def fetch_yahoo_fallback(tickers,limit_per_ticker=8,max_tickers=20):
    """Fallback only; the automated path prefers one bounded FMP batch."""
    from core.news_data import get_news
    stories=[]; failures=[]
    selected=list(dict.fromkeys(str(t).upper().strip() for t in tickers if str(t).strip()))[:max_tickers]
    for ticker in selected:
        try:
            frame=get_news(ticker,limit_per_ticker)
            for _,raw in frame.iterrows():
                story=normalize_story({'symbol':ticker,'title':raw.get('Title'),'publisher':raw.get('Publisher'),
                                       'published_at':raw.get('Published'),'url':raw.get('URL')},
                                      default_ticker=ticker,provider='Yahoo Finance',source_type='NEWS')
                if story: stories.append(story)
        except Exception as exc: failures.append(f'{ticker}:{type(exc).__name__}')
    return stories,{'status':'CURRENT' if stories else 'FAILED' if failures else 'NO_DATA',
                    'provider':'Yahoo Finance','requests':len(selected),'failures':failures[:6]}


def _sec_ticker_map(data):
    rows=data.values() if isinstance(data,dict) else data if isinstance(data,list) else []
    mapping={}
    for row in rows:
        if not isinstance(row,dict): continue
        ticker=str(row.get('ticker','')).upper().strip(); cik=row.get('cik_str') or row.get('cik')
        try: mapping[ticker]=str(int(cik)).zfill(10)
        except Exception: continue
    return mapping


def _recent_columns(data):
    recent=((data or {}).get('filings') or {}).get('recent') or {}
    length=max((len(value) for value in recent.values() if isinstance(value,list)),default=0)
    return [{key:(value[index] if isinstance(value,list) and index<len(value) else None)
             for key,value in recent.items()} for index in range(length)]


def fetch_sec_filings(tickers,lookback_hours=48,max_tickers=30,get_json=None,pause_seconds=.12,now=None):
    """Read recent material forms from the official SEC submissions API."""
    selected=list(dict.fromkeys(str(t).upper().strip() for t in tickers if str(t).strip()))[:max_tickers]
    if not selected: return [],{'status':'NO_TICKERS','provider':'SEC EDGAR','requests':0}
    get_json=get_json or _request_json
    user_agent=os.getenv('SEC_USER_AGENT','InvestmentDesk fgr-inv@users.noreply.github.com')
    headers={'User-Agent':user_agent,'Accept-Encoding':'gzip, deflate'}
    requests_made=0; failures=[]; stories=[]
    try:
        mapping=_sec_ticker_map(get_json(SEC_TICKERS_URL,headers=headers)); requests_made+=1
    except Exception as exc:
        return [],{'status':'FAILED','provider':'SEC EDGAR','requests':requests_made,'failures':[type(exc).__name__]}
    cutoff=pd.Timestamp(now or datetime.now(timezone.utc))
    if cutoff.tzinfo is None: cutoff=cutoff.tz_localize('UTC')
    cutoff=cutoff.tz_convert('UTC')-timedelta(hours=float(lookback_hours))
    for ticker in selected:
        cik=mapping.get(ticker)
        if not cik: continue
        try:
            data=get_json(SEC_SUBMISSIONS.format(cik=cik),headers=headers); requests_made+=1
            company=str((data or {}).get('name') or ticker)
            for row in _recent_columns(data):
                form=str(row.get('form') or '').upper().strip()
                if form not in SEC_FORMS: continue
                published=_timestamp(row.get('acceptanceDateTime') or row.get('filingDate'))
                if not published or pd.Timestamp(published)<cutoff: continue
                accession=str(row.get('accessionNumber') or '')
                document=str(row.get('primaryDocument') or '')
                accession_path=accession.replace('-','')
                url=(f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{document}'
                     if accession_path and document else '')
                description=str(row.get('primaryDocDescription') or '').strip()
                items=str(row.get('items') or '').strip()
                title=f'{form} filing — {company}'
                summary=' · '.join(part for part in (description,f'Items {items}' if items else '') if part)
                story=normalize_story({'symbol':ticker,'title':title,'summary':summary,'publisher':'SEC EDGAR',
                                       'published_at':published,'url':url},default_ticker=ticker,
                                      provider='SEC EDGAR',source_type='SEC_FILING',primary_source=True)
                if story:
                    story.update({'form':form,'accession_number':accession,'items':items,'cik':cik})
                    stories.append(story)
        except Exception as exc: failures.append(f'{ticker}:{type(exc).__name__}')
        if pause_seconds and get_json is _request_json: time.sleep(float(pause_seconds))
    status='CURRENT' if stories or not failures else 'FAILED'
    return stories,{'status':status,'provider':'SEC EDGAR','requests':requests_made,'failures':failures[:6],
                    'tickers_mapped':sum(t in mapping for t in selected)}


def _deduplicate(stories):
    """Collapse syndicated duplicates while preferring the linked primary source.

    SEC filings keep their accession-level identity.  Non-SEC items with the
    same normalized headline, ticker and publication day are treated as the
    same underlying story, even when a news feed and the issuer press-release
    feed expose different URLs.
    """
    output=[]; indexes={}
    for story in stories:
        ticker=str(story.get('ticker') or '').upper().strip()
        if story.get('source_type')=='SEC_FILING':
            identity=('SEC',ticker,story.get('accession_number') or story.get('story_id'))
        else:
            headline=re.sub(r'[^a-z0-9]+',' ',str(story.get('title') or '').lower()).strip()
            identity=('STORY',ticker,headline,str(story.get('published_at') or '')[:10])
        if identity not in indexes:
            indexes[identity]=len(output); output.append(story); continue
        current=output[indexes[identity]]
        current_rank=(bool(current.get('primary_source')),current.get('source_type')=='PRESS_RELEASE',
                      len(str(current.get('summary') or '')))
        candidate_rank=(bool(story.get('primary_source')),story.get('source_type')=='PRESS_RELEASE',
                        len(str(story.get('summary') or '')))
        if candidate_rank>current_rank: output[indexes[identity]]=story
    return output


def collect_catalyst_stories(tickers,include_sec=False,lookback_hours=36,now=None):
    """Collect fresh stories with explicit provider diagnostics and bounded fallbacks."""
    current=pd.Timestamp(now or datetime.now(timezone.utc))
    if current.tzinfo is None: current=current.tz_localize('UTC')
    current=current.tz_convert('UTC'); cutoff=current-timedelta(hours=float(lookback_hours))
    news,fmp_status=fetch_fmp_stories(tickers)
    statuses=[fmp_status]
    if not news:
        news,yahoo_status=fetch_yahoo_fallback(tickers)
        statuses.append(yahoo_status)
    filings=[]
    if include_sec:
        filings,sec_status=fetch_sec_filings(tickers,lookback_hours=max(lookback_hours,48),now=current)
        statuses.append(sec_status)
    fresh=[]
    for story in _deduplicate(news+filings):
        published=_timestamp(story.get('published_at'))
        if not published: continue
        ts=pd.Timestamp(published)
        # Reject undated, old, or implausibly future items before classification.
        if cutoff<=ts<=current+timedelta(minutes=15): fresh.append({**story,'published_at':published})
    fresh.sort(key=lambda row:row.get('published_at') or '',reverse=True)
    return fresh,{'providers':statuses,'requested_tickers':len(set(tickers)),'fresh_stories':len(fresh),
                  'include_sec':bool(include_sec),'lookback_hours':float(lookback_hours)}
