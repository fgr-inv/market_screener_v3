from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

from core.desk_mandate import (classify_official_catalyst, invalidating_catalyst_evidence,
                                load_desk_mandate, qualifying_catalyst_evidence)
from core.opportunity_lifecycle import build_opportunity_lifecycle, update_shadow_book
from core.portfolio_import import normalize_positions_csv


NOW=pd.Timestamp('2026-09-08 20:00:00',tz='America/New_York')


def _seed(ticker):
    return {'Ticker':ticker,'Universe Source':'S&P 500','Cap Segment':'Large Cap','Sector':'Technology',
            'Entry Score':80,'Priority Score':80,'RR':2.0}


def _verified(ticker):
    return {'Ticker':ticker,'Fundamental':'IMPROVING','Technical':'SETUP','Verified Specialists':3}


def _signal(ticker,index):
    return {'ticker':ticker,'setup_version':'2.0','signal_key':f'signal-{index}',
            'opportunity_key':f'opp-{index}','direction':'LONG','setup_id':'BREAKOUT_RVOL',
            'signal_at':NOW.isoformat(),'baseline_price':100.0+index,'baseline_atr':2.0}


def _confirmation(tickers):
    return {ticker:{'gate_pass':True,'confirmation_score':80,'weekly_bias':'BULLISH',
                    'daily_bias':'BULLISH','hourly_bias':'BULLISH','market_regime':'BULLISH'}
            for ticker in tickers}


def _official_story(ticker,title='Company raises guidance for fiscal year'):
    return {'ticker':ticker,'title':title,'summary':'Official investor-relations release.',
            'published_at':(NOW-pd.Timedelta(days=2)).isoformat(),'url':'https://issuer.example/ir',
            'primary_source':True,'material':True,'severity':4,'direction':'POSITIVE','category':'GUIDANCE'}


def _history(base):
    index=pd.bdate_range('2026-08-01',periods=20)
    close=base+np.sin(np.arange(20)/3)
    return pd.DataFrame({'Open':close,'High':close+1,'Low':close-1,'Close':close,'Volume':1_000_000},index=index)


def test_mandate_is_broker_free_and_accepts_only_fresh_primary_events():
    mandate=load_desk_mandate()
    assert mandate['broker_connections_allowed'] is False
    assert mandate['live_execution_allowed'] is False
    story={'primary':True,'title':'Company reaffirms guidance','published_at':(NOW-pd.Timedelta(days=3)).isoformat()}
    assert classify_official_catalyst(story)=='GUIDANCE_REAFFIRMED'
    assert qualifying_catalyst_evidence([story],mandate,NOW)[0]['verified'] is True
    assert qualifying_catalyst_evidence([{**story,'primary':False}],mandate,NOW)==[]
    assert qualifying_catalyst_evidence([{**story,'published_at':(NOW-pd.Timedelta(days=15)).isoformat()}],mandate,NOW)==[]
    cut={**story,'title':'Company cuts guidance after demand weakness'}
    assert invalidating_catalyst_evidence([cut],mandate,NOW)[0]['event_type']=='GUIDANCE_CUT'


def test_catalyst_mandate_blocks_thesis_only_and_allows_official_evidence():
    mandate=load_desk_mandate(); ticker='ABC'; signal=_signal(ticker,1)
    thesis=[{'ticker':ticker,'status':'ACTIVE','thesis':'Strong business.'}]
    blocked=build_opportunity_lifecycle([_seed(ticker)],[_verified(ticker)],[signal],theses=thesis,
                                        generated_at=NOW,confirmations=_confirmation([ticker]),mandate=mandate)
    assert blocked['candidates'][0]['stage']=='EVIDENCE_VERIFIED'
    assert 'NO_QUALIFYING_OFFICIAL_CATALYST' in blocked['candidates'][0]['gate_reasons']
    ready=build_opportunity_lifecycle([_seed(ticker)],[_verified(ticker)],[signal],theses=thesis,
                                      news_payload={'stories':[_official_story(ticker)]},generated_at=NOW,
                                      confirmations=_confirmation([ticker]),mandate=mandate)
    assert ready['candidates'][0]['stage']=='ENTRY_READY'
    assert ready['candidates'][0]['qualifying_catalyst_count']==1
    chased_confirmation=_confirmation([ticker]); chased_confirmation[ticker]['breakout_quality']={'atr_extension':2.0}
    chased=build_opportunity_lifecycle([_seed(ticker)],[_verified(ticker)],[signal],theses=thesis,
                                       news_payload={'stories':[_official_story(ticker)]},generated_at=NOW,
                                       confirmations=chased_confirmation,mandate=mandate)
    assert chased['candidates'][0]['stage']=='EVIDENCE_VERIFIED'
    assert 'PRICE_CHASED' in chased['candidates'][0]['gate_reasons']
    invalidated=build_opportunity_lifecycle(
        [_seed(ticker)],[_verified(ticker)],[signal],theses=thesis,
        news_payload={'stories':[_official_story(ticker),_official_story(ticker,'Company cuts guidance')]},
        generated_at=NOW,confirmations=_confirmation([ticker]),mandate=mandate)
    assert invalidated['candidates'][0]['stage']=='INVALIDATED'
    assert invalidated['candidates'][0]['official_thesis_invalidations'][0]['event_type']=='GUIDANCE_CUT'


def test_mandate_enforces_two_new_virtual_positions_and_starter_sizing():
    mandate=load_desk_mandate(); tickers=['AAA','BBB','CCC']
    signals=[_signal(ticker,index) for index,ticker in enumerate(tickers,1)]
    lifecycle=build_opportunity_lifecycle(
        [_seed(ticker) for ticker in tickers],[_verified(ticker) for ticker in tickers],signals,
        news_payload={'stories':[_official_story(ticker) for ticker in tickers]},generated_at=NOW,
        confirmations=_confirmation(tickers),mandate=mandate)
    book=update_shadow_book(lifecycle,signals,{ticker:_history(100+index*10) for index,ticker in enumerate(tickers)},
                            generated_at=NOW,mandate=mandate)
    assert book['weekly_new_positions']==2
    assert len(book['positions'])==2
    assert all(position['starter_fraction']==.7 for position in book['positions'])
    assert any(row['reason']=='WEEKLY_NEW_POSITION_CAP_EXHAUSTED' for row in book['new_rejections'])


def test_manual_csv_import_has_no_external_account_dependency():
    frame=normalize_positions_csv(StringIO('Symbol,Qty,Average Cost\nAAPL,3,180\n'))
    assert frame.to_dict('records')==[{'ticker':'AAPL','quantity':3,'avg_cost':180}]
    root=Path(__file__).resolve().parents[1]
    assert not (root/'core'/'broker_import.py').exists()
    assert not (root/'views'/'broker_data.py').exists()
    assert 'position_import.py' in (root/'app.py').read_text(encoding='utf-8')
    active='\n'.join((root/path).read_text(encoding='utf-8').lower() for path in (
        'app.py','.streamlit/secrets.toml.example','core/institutional_providers.py','views/system_health.py'))
    assert 'alpaca' not in active
