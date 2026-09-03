"""News & Catalyst Agent: deterministic materiality, source and thesis checks."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
import re

import pandas as pd

from core.agent_contracts import AgentResult, DataStatus, Evidence


AGENT_VERSION='1.0'; SKILL='news_catalyst_intelligence'; SKILL_VERSION='1.0'

CATEGORY_RULES=(
    ('CYBERSECURITY',5,('data breach','cyberattack','cyber attack','ransomware','security incident','customer data exposed')),
    ('CAPITAL_STRUCTURE',4,('public offering','stock offering','share offering','secondary offering','at-the-market','dilution','convertible notes','bankruptcy','chapter 11','debt restructuring','restatement','material weakness')),
    ('M&A',5,('acquire','acquisition','merger','takeover','buyout','strategic alternatives','sale process')),
    ('REGULATORY_LEGAL',4,('fda approval','fda rejects','clinical hold','antitrust','department of justice','doj investigation','sec investigation','regulator','regulatory approval','lawsuit','settlement','recall','subpoena')),
    ('GUIDANCE',4,('raises guidance','raised guidance','cuts guidance','cut guidance','lowers outlook','raises outlook','forecast','financial outlook','withdraws guidance')),
    ('EARNINGS',4,('earnings','quarterly results','financial results','revenue beat','revenue miss','eps beat','eps miss','10-q','10-k','20-f')),
    ('MANAGEMENT',3,('chief executive','chief financial officer','ceo resigns','cfo resigns','appoints ceo','appoints cfo','management change')),
    ('CONTRACT_PRODUCT',3,('contract award','wins contract','strategic partnership','product launch','launches','new customer','supply agreement')),
    ('CAPITAL_RETURN',3,('share repurchase','stock buyback','buyback authorization','dividend increase','special dividend')),
    ('ANALYST_RATING',2,('upgrade','downgrade','price target','initiates coverage')),
)
NEGATIVE_TERMS=('misses','missed','cuts guidance','cut guidance','lowers outlook','rejects','clinical hold','investigation',
                'lawsuit','recall','breach','ransomware','bankruptcy','offering','dilution','resigns','terminated',
                'restatement','material weakness','default','fraud','warning')
POSITIVE_TERMS=('beats','beat estimates','raises guidance','raised guidance','raises outlook','approval','approved',
                'contract award','wins contract','buyback','dividend increase','record revenue','record earnings')
STOPWORDS={'about','after','again','against','being','company','could','from','have','into','more','over','their','there',
           'these','this','through','under','where','which','with','would','para','como','sobre','desde','hasta','esta'}


def _text(value): return str(value or '').strip()


def _tokens(value):
    return {token for token in re.findall(r'[a-záéíóúñ0-9]+',_text(value).lower()) if len(token)>=5 and token not in STOPWORDS}


def _sec_classification(story):
    form=_text(story.get('form')).upper(); items=_text(story.get('items'))
    if form.startswith(('S-1','S-3','424B')): return 'CAPITAL_STRUCTURE',4,'NEUTRAL'
    if form.startswith(('10-Q','10-K','20-F','40-F')): return 'EARNINGS',4,'NEUTRAL'
    if form.startswith(('8-K','6-K')):
        if any(item in items for item in ('2.02','2.06','4.02')): return 'EARNINGS',4,'NEUTRAL'
        if any(item in items for item in ('1.01','1.02','2.01')): return 'M&A_OR_AGREEMENT',4,'NEUTRAL'
        if '5.02' in items: return 'MANAGEMENT',3,'NEUTRAL'
        return 'SEC_FILING',3,'NEUTRAL'
    if form=='DEF 14A': return 'GOVERNANCE',2,'NEUTRAL'
    return 'SEC_FILING',3,'NEUTRAL'


def classify_catalyst_story(story,portfolio=False,thesis=None):
    """Classify one story without claiming unsupported causality or sentiment."""
    text=' '.join((_text(story.get('title')),_text(story.get('summary')))).lower()
    if story.get('source_type')=='SEC_FILING': category,severity,direction=_sec_classification(story)
    else:
        category,severity='GENERAL',1
        for name,level,patterns in CATEGORY_RULES:
            if any(pattern in text for pattern in patterns): category,severity=name,level; break
        negative=sum(term in text for term in NEGATIVE_TERMS); positive=sum(term in text for term in POSITIVE_TERMS)
        direction='NEGATIVE' if negative>positive else 'POSITIVE' if positive>negative else 'NEUTRAL'
    severity=min(5,severity+(1 if portfolio and severity>=3 else 0))
    thesis=thesis or {}; story_tokens=_tokens(text)
    invalidation_overlap=sorted(story_tokens&_tokens(thesis.get('invalidation')))
    catalyst_overlap=sorted(story_tokens&_tokens(thesis.get('catalysts')))
    if invalidation_overlap:
        thesis_impact='POTENTIAL_INVALIDATION_MATCH'
    elif catalyst_overlap:
        thesis_impact='CATALYST_MATCH'
    elif direction=='NEGATIVE' and severity>=4:
        thesis_impact='POTENTIAL_THESIS_RISK'
    elif direction=='POSITIVE' and severity>=4:
        thesis_impact='POTENTIAL_THESIS_SUPPORT'
    else:
        thesis_impact='REVIEW_REQUIRED' if severity>=3 else 'NO_MATERIAL_LINK'
    return {**story,'category':category,'severity':int(severity),'direction':direction,
            'material':bool(severity>=4),'portfolio':bool(portfolio),'thesis_impact':thesis_impact,
            'invalidation_matches':invalidation_overlap[:8],'catalyst_matches':catalyst_overlap[:8]}


def catalyst_story_event(classified):
    ticker=_text(classified.get('ticker')).upper(); category=_text(classified.get('category')).lower()
    story_id=_text(classified.get('story_id')) or hashlib.sha256(str(classified).encode()).hexdigest()[:28]
    event_types=['news_catalyst',f'news_{category}']
    if classified.get('source_type')=='SEC_FILING': event_types.append('sec_filing')
    if classified.get('primary_source'): event_types.append('primary_source')
    title=_text(classified.get('title'))
    return {'ticker':ticker,'event_types':sorted(set(event_types)),'severity':int(classified.get('severity') or 1),
            'reasons':[f"{classified.get('category')}: {title}"],'portfolio':bool(classified.get('portfolio')),
            'metrics':{'story':classified,'published_at':classified.get('published_at'),'source':classified.get('publisher'),
                       'category':classified.get('category'),'direction':classified.get('direction'),
                       'thesis_impact':classified.get('thesis_impact')},
            'event_key':f'NEWS:{ticker}:{story_id}','fingerprint':story_id}


def classify_catalyst_stories(stories,portfolio_tickers=None,theses=None):
    holdings={str(t).upper() for t in (portfolio_tickers or [])}; theses=theses or {}; rows=[]
    for story in stories or []:
        ticker=_text(story.get('ticker')).upper()
        rows.append(classify_catalyst_story(story,ticker in holdings,theses.get(ticker)))
    rows.sort(key=lambda row:(bool(row.get('portfolio')),int(row.get('severity') or 0),row.get('published_at') or ''),reverse=True)
    return rows


def _freshness(published_at,max_age_hours=72):
    try:
        ts=pd.Timestamp(published_at)
        if ts.tzinfo is None: ts=ts.tz_localize('UTC')
        age=max(0,(pd.Timestamp(datetime.now(timezone.utc))-ts.tz_convert('UTC')).total_seconds()/3600)
        return (DataStatus.CURRENT if age<=max_age_hours else DataStatus.STALE),round(age,1)
    except Exception:
        return DataStatus.NOT_CHECKED,None


def analyze_news_catalyst(ticker,stories,thesis=None,portfolio=False):
    ticker=_text(ticker).upper(); rows=classify_catalyst_stories(stories,[ticker] if portfolio else [],{ticker:thesis or {}})
    rows=[row for row in rows if _text(row.get('ticker')).upper()==ticker]
    if not rows:
        return AgentResult('News & Catalyst',AGENT_VERSION,SKILL,SKILL_VERSION,ticker,'NO_MATERIAL_NEWS',.25,
            'No fresh news or filing evidence was available for this routed review.',
            [Evidence('Fresh catalyst stories',0,'Configured news providers',status=DataStatus.UNAVAILABLE)],
            alternative_explanation='A provider may have no coverage or a story may not yet be indexed.',
            metadata={'articles':[],'material_count':0,'approval_boundary':'Research only. No order or thesis edit is performed.'})
    material=[row for row in rows if row.get('material')]
    negative=[row for row in material if row.get('direction')=='NEGATIVE' or row.get('thesis_impact')=='POTENTIAL_INVALIDATION_MATCH']
    positive=[row for row in material if row.get('direction')=='POSITIVE' or row.get('thesis_impact')=='CATALYST_MATCH']
    if negative and positive: state='MIXED_CATALYSTS'
    elif negative: state='MATERIAL_NEGATIVE'
    elif positive: state='MATERIAL_POSITIVE'
    elif material: state='MATERIAL_REVIEW'
    else: state='MONITOR'
    evidence=[]
    for row in rows[:3]:
        status,age=_freshness(row.get('published_at'))
        evidence.append(Evidence(row.get('title'),row.get('category'),row.get('url') or row.get('provider'),
                                 observed_at=row.get('published_at') or datetime.now(timezone.utc).isoformat(),status=status,
                                 note=f"{row.get('publisher')} · direction {row.get('direction')} · severity {row.get('severity')}/5"+
                                      ('' if age is None else f' · {age:.1f}h old')))
    primary=any(row.get('primary_source') for row in rows)
    evidence.append(Evidence('Primary-source confirmation',primary,'SEC EDGAR / company press release',
                             status=DataStatus.CURRENT if primary else DataStatus.UNAVAILABLE,
                             note='Media-only reports remain partially verified until a primary source is observed.'))
    contradictions=[]
    if negative and positive: contradictions.append('Fresh evidence contains both positive and negative material catalysts.')
    max_severity=max(int(row.get('severity') or 0) for row in rows)
    confidence=min(.95,.42+.09*min(len(rows),3)+(.18 if primary else 0)+(.08 if max_severity>=5 else 0))
    leading=(material or rows)[0]
    summary=(f"{ticker}: {state} · {len(material)} material item(s) · leading event "
             f"{leading.get('category')} ({leading.get('direction')}, severity {leading.get('severity')}/5).")
    return AgentResult('News & Catalyst',AGENT_VERSION,SKILL,SKILL_VERSION,ticker,state,round(confidence,2),summary,
        evidence,contradictions,
        'A headline can be incomplete, duplicated, speculative or already reflected in price; review the linked primary document before acting.',
        metadata={'articles':rows[:12],'material_count':len(material),'primary_source_observed':primary,
                  'thesis_impact':leading.get('thesis_impact'),'approval_boundary':'Research only. No order or thesis edit is performed.'})
