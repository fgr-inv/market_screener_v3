"""Frozen regime and multi-timeframe evidence for post-close opportunities.

Every value is calculated from bars available at the observation time. The
module describes confirmation and contradiction; it does not forecast returns.
"""
from __future__ import annotations

import math
import pandas as pd


CONFIRMATION_VERSION='1.0'


def _finite(value,default=None):
    try:
        number=float(value)
        return number if math.isfinite(number) else default
    except Exception: return default


def _clean(frame):
    if frame is None or frame.empty: return pd.DataFrame()
    out=frame.copy()
    if isinstance(out.columns,pd.MultiIndex): out.columns=[str(column[0]) for column in out.columns]
    required=['Open','High','Low','Close']
    if any(column not in out for column in required): return pd.DataFrame()
    if 'Volume' not in out: out['Volume']=0.0
    out=out[required+['Volume']].apply(pd.to_numeric,errors='coerce').dropna(subset=required)
    return out[~out.index.duplicated(keep='last')].sort_index()


def _weekly(frame):
    x=_clean(frame)
    if x.empty: return x
    return x.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()


def _trend(frame,fast=20,slow=50,structural=200):
    x=_clean(frame)
    if x.empty: return {'bias':'NOT_CHECKED','score':None,'price':None,'ema_fast':None,'ema_slow':None,'ema_structural':None}
    close=x.Close
    if len(close)<slow+5: return {'bias':'NOT_CHECKED','score':None,'price':None,'ema_fast':None,'ema_slow':None,'ema_structural':None}
    ef=close.ewm(span=fast,adjust=False).mean(); es=close.ewm(span=slow,adjust=False).mean()
    structural_series=close.ewm(span=structural,adjust=False,min_periods=min(150,structural)).mean()
    price=float(close.iloc[-1]); fast_now=float(ef.iloc[-1]); slow_now=float(es.iloc[-1])
    structural_now=_finite(structural_series.iloc[-1]); slow_slope=float(es.iloc[-1]/es.iloc[-6]-1)
    bullish=price>fast_now>slow_now and slow_slope>0 and (structural_now is None or slow_now>structural_now)
    bearish=price<fast_now<slow_now and slow_slope<0 and (structural_now is None or slow_now<structural_now)
    bias='BULLISH' if bullish else 'BEARISH' if bearish else 'NEUTRAL'
    score=100 if bullish else 0 if bearish else 50
    return {'bias':bias,'score':score,'price':round(price,6),'ema_fast':round(fast_now,6),
            'ema_slow':round(slow_now,6),'ema_structural':None if structural_now is None else round(structural_now,6)}


def _return(close,periods):
    if len(close)<=periods: return None
    old=_finite(close.iloc[-periods-1]); current=_finite(close.iloc[-1])
    return None if not old or current is None else (current/old-1)*100


def _relative_strength(asset,benchmark):
    a=_clean(asset); b=_clean(benchmark)
    if a.empty or b.empty: return {'rs20_pct':None,'rs63_pct':None,'ratio_slope20_pct':None}
    pair=pd.concat([a.Close.rename('asset'),b.Close.rename('benchmark')],axis=1).dropna()
    if len(pair)<25: return {'rs20_pct':None,'rs63_pct':None,'ratio_slope20_pct':None}
    ratio=pair.asset/pair.benchmark
    output={}
    for horizon in (20,63):
        asset_return=_return(pair.asset,horizon); benchmark_return=_return(pair.benchmark,horizon)
        output[f'rs{horizon}_pct']=(None if asset_return is None or benchmark_return is None
                                    else round(asset_return-benchmark_return,3))
    output['ratio_slope20_pct']=None if len(ratio)<=20 else round((ratio.iloc[-1]/ratio.iloc[-21]-1)*100,3)
    return output


def _breakout_quality(frame,direction='LONG',lookback=20):
    x=_clean(frame)
    if len(x)<lookback+15: return {'score':None,'state':'NOT_CHECKED','rvol':None,'close_location':None,'atr_extension':None}
    previous=x.Close.shift(1); tr=pd.concat([(x.High-x.Low),(x.High-previous).abs(),(x.Low-previous).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); row=x.iloc[-1]
    prior_high=float(x.High.iloc[-lookback-1:-1].max()); prior_low=float(x.Low.iloc[-lookback-1:-1].min())
    avg_volume=float(x.Volume.shift(1).rolling(20,min_periods=10).mean().iloc[-1])
    rvol=None if avg_volume<=0 else float(row.Volume)/avg_volume
    bar_range=max(float(row.High-row.Low),1e-12)
    close_location=(float(row.Close-row.Low)/bar_range if direction=='LONG'
                    else float(row.High-row.Close)/bar_range)
    level=prior_high if direction=='LONG' else prior_low
    breakout=(float(row.Close)>prior_high if direction=='LONG' else float(row.Close)<prior_low)
    extension=abs(float(row.Close-level))/_finite(atr.iloc[-1],1e-12)
    score=0
    score+=30 if breakout else 12 if abs(float(row.Close/level-1))*100<=2 else 0
    score+=25 if rvol is not None and rvol>=1.5 else 15 if rvol is not None and rvol>=1 else 0
    score+=25 if close_location>=.75 else 15 if close_location>=.55 else 0
    score+=20 if extension<=1 else 10 if extension<=1.75 else 0
    state=('CONFIRMED' if breakout and score>=70 else 'LOW_QUALITY_BREAKOUT' if breakout else
           'NEAR_LEVEL' if abs(float(row.Close/level-1))*100<=2 else 'NO_BREAKOUT')
    return {'score':int(score),'state':state,'rvol':None if rvol is None else round(rvol,3),
            'close_location':round(close_location,3),'atr_extension':round(extension,3),
            'reference_level':round(level,6)}


def _breadth_context(breadth,universe_source=''):
    if breadth is None or breadth.empty: return {'score':None,'state':'NOT_CHECKED','universe':None}
    source=str(universe_source or '')
    target=('S&P SmallCap 600' if 'Small' in source else 'S&P MidCap 400' if 'Mid' in source
            else 'Nasdaq 100' if 'Nasdaq' in source else 'S&P 500')
    rows=breadth[breadth.get('Universe',pd.Series(index=breadth.index,dtype=str)).astype(str)==target]
    if rows.empty: rows=breadth
    score=_finite(rows.iloc[0].get('Score'))
    state='STRONG' if score is not None and score>=65 else 'WEAK' if score is not None and score<40 else 'NEUTRAL' if score is not None else 'NOT_CHECKED'
    return {'score':score,'state':state,'universe':str(rows.iloc[0].get('Universe') or target)}


def _volatility_regime(frame):
    x=_clean(frame)
    if len(x)<80: return {'state':'NOT_CHECKED','atr_pct':None,'percentile':None}
    previous=x.Close.shift(1)
    tr=pd.concat([(x.High-x.Low),(x.High-previous).abs(),(x.Low-previous).abs()],axis=1).max(axis=1)
    atr_pct=(tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()/x.Close*100).dropna()
    if atr_pct.empty: return {'state':'NOT_CHECKED','atr_pct':None,'percentile':None}
    current=float(atr_pct.iloc[-1]); sample=atr_pct.tail(252)
    percentile=float((sample<=current).mean()*100)
    state='HIGH' if percentile>=80 else 'LOW' if percentile<=20 else 'NORMAL'
    return {'state':state,'atr_pct':round(current,3),'percentile':round(percentile,1)}


def _structural_invalidation(frame,direction):
    x=_clean(frame)
    if len(x)<21: return None
    values=x.Low.iloc[-21:-1] if direction!='SHORT' else x.High.iloc[-21:-1]
    return round(float(values.min() if direction!='SHORT' else values.max()),6)


def event_anchored_vwap(frame,anchor_date=None):
    """Volume-weighted price from a known event date, using no future bars."""
    x=_clean(frame)
    if x.empty or not anchor_date: return {'state':'NOT_AVAILABLE','anchor_date':None,'value':None,'distance_pct':None}
    try: anchor=pd.Timestamp(anchor_date).date()
    except (TypeError,ValueError): return {'state':'INVALID_ANCHOR','anchor_date':str(anchor_date),'value':None,'distance_pct':None}
    sample=x[[pd.Timestamp(index).date()>=anchor for index in x.index]]
    if sample.empty or float(sample.Volume.sum())<=0:
        return {'state':'NOT_AVAILABLE','anchor_date':str(anchor),'value':None,'distance_pct':None}
    typical=(sample.High+sample.Low+sample.Close)/3
    value=float((typical*sample.Volume).sum()/sample.Volume.sum()); close=float(sample.Close.iloc[-1])
    return {'state':'ABOVE' if close>value else 'BELOW' if close<value else 'AT_ANCHOR',
            'anchor_date':str(anchor),'value':round(value,6),'distance_pct':round((close/value-1)*100,3)}


def analyze_regime_multitimeframe(ticker,daily,hourly,benchmark,sector_history=None,breadth=None,
                                  universe_source='',direction='LONG',setup_id='',event_anchor_date=None):
    """Return a direction-aware confirmation gate with explicit contradictions."""
    direction=str(direction or 'LONG').upper(); long=direction!='SHORT'
    daily_trend=_trend(daily); weekly_trend=_trend(_weekly(daily),fast=10,slow=30,structural=40)
    hourly_trend=_trend(hourly,fast=20,slow=50,structural=100)
    market_trend=_trend(benchmark); market_bias=market_trend['bias']
    volatility=_volatility_regime(benchmark)
    rs_market=_relative_strength(daily,benchmark)
    rs_sector=_relative_strength(daily,sector_history) if sector_history is not None else {'rs20_pct':None,'rs63_pct':None,'ratio_slope20_pct':None}
    breakout=_breakout_quality(daily,direction)
    breadth_context=_breadth_context(breadth,universe_source)
    anchored=event_anchored_vwap(daily,event_anchor_date)
    desired='BULLISH' if long else 'BEARISH'; opposite='BEARISH' if long else 'BULLISH'
    contradictions=[]
    if weekly_trend['bias']=='NOT_CHECKED': contradictions.append('WEEKLY_CONFIRMATION_UNAVAILABLE')
    if daily_trend['bias']=='NOT_CHECKED': contradictions.append('DAILY_CONFIRMATION_UNAVAILABLE')
    if weekly_trend['bias']==opposite: contradictions.append('WEEKLY_TREND_OPPOSES_SIGNAL')
    if daily_trend['bias']==opposite: contradictions.append('DAILY_TREND_OPPOSES_SIGNAL')
    if hourly_trend['bias']==opposite: contradictions.append('HOURLY_TREND_OPPOSES_SIGNAL')
    if hourly_trend['bias']=='NOT_CHECKED': contradictions.append('HOURLY_CONFIRMATION_UNAVAILABLE')
    if market_bias=='NOT_CHECKED': contradictions.append('MARKET_REGIME_UNAVAILABLE')
    if (long and market_bias=='BEARISH') or (not long and market_bias=='BULLISH'):
        contradictions.append('MARKET_REGIME_OPPOSES_SIGNAL')
    signed_rs=rs_market.get('rs20_pct')
    if signed_rs is None: contradictions.append('RELATIVE_STRENGTH_UNAVAILABLE')
    if signed_rs is not None and ((long and signed_rs<-2) or (not long and signed_rs>2)):
        contradictions.append('WEAK_RELATIVE_STRENGTH_VS_SPY')
    if breadth_context['state']=='WEAK' and long: contradictions.append('WEAK_MARKET_BREADTH')
    if breadth_context['state']=='NOT_CHECKED': contradictions.append('MARKET_BREADTH_UNAVAILABLE')
    if breadth_context['state']=='STRONG' and not long: contradictions.append('STRONG_MARKET_BREADTH_OPPOSES_SHORT')
    if 'BREAKOUT' in str(setup_id).upper() and breakout['score'] is not None and breakout['score']<55:
        contradictions.append('LOW_BREAKOUT_QUALITY')
    if 'BREAKOUT' in str(setup_id).upper() and breakout['score'] is None:
        contradictions.append('BREAKOUT_QUALITY_UNAVAILABLE')
    score=0
    score+=10 if weekly_trend['bias']==desired else 5 if weekly_trend['bias']=='NEUTRAL' else 0
    score+=15 if daily_trend['bias']==desired else 7 if daily_trend['bias']=='NEUTRAL' else 0
    score+=10 if hourly_trend['bias']==desired else 5 if hourly_trend['bias']=='NEUTRAL' else 0
    score+=10 if market_bias==desired else 6 if market_bias=='NEUTRAL' else 0
    if signed_rs is not None: score+=15 if (signed_rs>=3 if long else signed_rs<=-3) else 8 if (signed_rs>=-1 if long else signed_rs<=1) else 0
    sector_rs=rs_sector.get('rs20_pct')
    if sector_rs is not None: score+=10 if (sector_rs>=2 if long else sector_rs<=-2) else 5 if (sector_rs>=-1 if long else sector_rs<=1) else 0
    if breadth_context['score'] is not None:
        supportive=(breadth_context['state']=='STRONG' if long else breadth_context['state']=='WEAK')
        score+=10 if supportive else 6 if breadth_context['state']=='NEUTRAL' else 0
    score+=20 if breakout['score'] is None else round(breakout['score']*.20)
    score=int(max(0,min(100,score)))
    critical={'WEEKLY_CONFIRMATION_UNAVAILABLE','DAILY_CONFIRMATION_UNAVAILABLE','HOURLY_CONFIRMATION_UNAVAILABLE',
              'MARKET_REGIME_UNAVAILABLE','RELATIVE_STRENGTH_UNAVAILABLE','MARKET_BREADTH_UNAVAILABLE',
              'WEEKLY_TREND_OPPOSES_SIGNAL','DAILY_TREND_OPPOSES_SIGNAL',
              'MARKET_REGIME_OPPOSES_SIGNAL','WEAK_MARKET_BREADTH','LOW_BREAKOUT_QUALITY'}
    critical.update({'BREAKOUT_QUALITY_UNAVAILABLE','STRONG_MARKET_BREADTH_OPPOSES_SHORT'})
    gate_pass=score>=60 and not any(reason in critical for reason in contradictions)
    status='CONFIRMED' if gate_pass else 'BLOCKED' if any(reason in critical for reason in contradictions) else 'MIXED'
    invalidation=('Close below the latest daily swing low / loss of daily EMA50 and relative-strength deterioration.' if long
                  else 'Close above the latest daily swing high / recovery of daily EMA50 and relative-strength deterioration.')
    return {'version':CONFIRMATION_VERSION,'ticker':str(ticker).upper(),'direction':direction,'status':status,
            'gate_pass':gate_pass,'confirmation_score':score,'weekly_bias':weekly_trend['bias'],
            'daily_bias':daily_trend['bias'],'hourly_bias':hourly_trend['bias'],'market_regime':market_bias,
            'volatility_regime':volatility,
            'relative_strength_spy':rs_market,'relative_strength_sector':rs_sector,
            'breadth':breadth_context,'breakout_quality':breakout,'contradictions':contradictions,
            'event_anchored_vwap':anchored,
            'structural_invalidation':invalidation,
            'structural_invalidation_price':_structural_invalidation(daily,direction),
            'frozen_at_signal':True,'no_lookahead':True,
            'shadow_mode':True,'no_execution':True}
