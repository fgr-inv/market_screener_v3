"""Daily technical-signal experiments and weekly evidence review.

The lab is deliberately separated from the production ranking.  It records
virtual signals, evaluates them forward without look-ahead, and may only
*propose* structural changes.  It never changes a rule or sends an order.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
import pandas as pd

from core.alerts_engine import send_webhook
from core.desk_store import load_desk_output, load_latest_desk_output, save_desk_output
from core.notification_settings import get_user_webhook


LAB_VERSION = '1.0'
HORIZONS = (1, 3, 5, 10, 20)
PRIMARY_HORIZON = 5
MAX_SIGNALS = 2500
MAX_OUTCOMES = 12500
MIN_REVIEW_SAMPLE = 30
MIN_REVIEW_VALIDATION = 10
MIN_REVIEW_TICKERS = 5

# Finite, interpretable variants.  "champion" is the conservative reference;
# challengers are evaluated but cannot promote themselves into production.
SETUPS = (
    {'id':'BREAKOUT_RVOL','variant':'base','role':'CHAMPION','lookback':20,'rvol':1.5},
    {'id':'BREAKOUT_RVOL','variant':'rvol_1_0','role':'CHALLENGER','lookback':20,'rvol':1.0},
    {'id':'BREAKOUT_RVOL','variant':'rvol_2_0','role':'CHALLENGER','lookback':20,'rvol':2.0},
    {'id':'EMA_PULLBACK','variant':'ema20','role':'CHAMPION','ema':20,'adx':18},
    {'id':'EMA_PULLBACK','variant':'ema50','role':'CHALLENGER','ema':50,'adx':18},
    {'id':'VWAP_RECLAIM','variant':'rolling20','role':'CHAMPION','window':20,'rvol':1.0},
    {'id':'DMI_ADX_TREND','variant':'adx20','role':'CHAMPION','adx':20},
    {'id':'DMI_ADX_TREND','variant':'adx25','role':'CHALLENGER','adx':25},
    {'id':'VOLATILITY_EXPANSION','variant':'base','role':'CHAMPION','rvol':1.25},
    {'id':'CANDLE_CONTEXT','variant':'engulfing','role':'CHAMPION','pattern':'engulfing'},
    {'id':'RELATIVE_STRENGTH','variant':'spy_20d','role':'CHAMPION','lookback':20},
)


def _finite(value):
    try:
        number=float(value)
        return number if math.isfinite(number) else None
    except Exception:
        return None


def _iso(value=None):
    if value is None: return datetime.now(timezone.utc).isoformat()
    stamp=pd.Timestamp(value)
    if stamp.tzinfo is None: stamp=stamp.tz_localize('UTC')
    return stamp.tz_convert('UTC').isoformat()


def _clean_history(frame):
    if frame is None or frame.empty: return pd.DataFrame()
    out=frame.copy()
    if isinstance(out.columns,pd.MultiIndex):
        out.columns=[str(col[0]) for col in out.columns]
    wanted=['Open','High','Low','Close','Volume']
    if any(col not in out for col in wanted): return pd.DataFrame()
    out=out[wanted].apply(pd.to_numeric,errors='coerce').dropna(subset=['Open','High','Low','Close'])
    out=out[~out.index.duplicated(keep='last')].sort_index()
    return out


def technical_feature_frame(history, benchmark=None):
    """Calculate past-and-present-only features for every daily bar."""
    x=_clean_history(history)
    if len(x)<60: return pd.DataFrame()
    close=x['Close']; high=x['High']; low=x['Low']; volume=x['Volume'].fillna(0)
    previous=close.shift(1)
    tr=pd.concat([(high-low),(high-previous).abs(),(low-previous).abs()],axis=1).max(axis=1)
    x['ATR14']=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    x['EMA20']=close.ewm(span=20,adjust=False).mean()
    x['EMA50']=close.ewm(span=50,adjust=False).mean()
    x['EMA200']=close.ewm(span=200,adjust=False,min_periods=150).mean()
    x['VOL20']=volume.shift(1).rolling(20,min_periods=10).mean()
    x['RVOL']=volume/x['VOL20'].replace(0,pd.NA)
    typical=(high+low+close)/3
    x['RVWAP20']=(typical*volume).rolling(20,min_periods=10).sum()/volume.rolling(20,min_periods=10).sum().replace(0,pd.NA)
    delta=close.diff(); gain=delta.clip(lower=0); loss=(-delta.clip(upper=0))
    rs=gain.ewm(alpha=1/14,adjust=False,min_periods=14).mean()/loss.ewm(alpha=1/14,adjust=False,min_periods=14).mean().replace(0,pd.NA)
    x['RSI14']=100-(100/(1+rs))
    up=high.diff(); down=-low.diff()
    plus_dm=up.where((up>down)&(up>0),0.0); minus_dm=down.where((down>up)&(down>0),0.0)
    atr=x['ATR14'].replace(0,pd.NA)
    x['PLUS_DI']=100*plus_dm.ewm(alpha=1/14,adjust=False,min_periods=14).mean()/atr
    x['MINUS_DI']=100*minus_dm.ewm(alpha=1/14,adjust=False,min_periods=14).mean()/atr
    dx=100*(x['PLUS_DI']-x['MINUS_DI']).abs()/(x['PLUS_DI']+x['MINUS_DI']).replace(0,pd.NA)
    x['ADX']=dx.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    x['PRIOR_HIGH20']=high.shift(1).rolling(20,min_periods=20).max()
    x['PRIOR_LOW20']=low.shift(1).rolling(20,min_periods=20).min()
    middle=close.rolling(20,min_periods=20).mean(); std=close.rolling(20,min_periods=20).std()
    x['BB_WIDTH']=(4*std/middle.replace(0,pd.NA)).abs()
    x['BB_LOW_Q']=x['BB_WIDTH'].shift(1).rolling(60,min_periods=30).quantile(.25)
    if benchmark is not None:
        bench=_clean_history(benchmark)
        if not bench.empty:
            bclose=bench['Close'].reindex(x.index).ffill()
            x['RS20']=(close/close.shift(20))/(bclose/bclose.shift(20))-1
            x['BENCH_CLOSE']=bclose
    return x


def _trigger(frame, setup):
    if len(frame)<3: return None
    row=frame.iloc[-1]; prev=frame.iloc[-2]
    close=_finite(row.Close); prior_close=_finite(prev.Close); atr=_finite(row.ATR14)
    if not close or not prior_close or not atr: return None
    sid=setup['id']; direction=None
    if sid=='BREAKOUT_RVOL':
        hi=_finite(row.PRIOR_HIGH20); lo=_finite(row.PRIOR_LOW20); rv=_finite(row.RVOL) or 0
        prev_hi=_finite(prev.PRIOR_HIGH20) or hi; prev_lo=_finite(prev.PRIOR_LOW20) or lo
        if hi and prev_hi and close>hi and prior_close<=prev_hi and rv>=setup['rvol']: direction='LONG'
        elif lo and prev_lo and close<lo and prior_close>=prev_lo and rv>=setup['rvol']: direction='SHORT'
    elif sid=='EMA_PULLBACK':
        ema=_finite(row[f"EMA{setup['ema']}"]); pema=_finite(prev[f"EMA{setup['ema']}"])
        trend_up=close>_finite(row.EMA50) and (_finite(row.EMA200) is None or _finite(row.EMA50)>_finite(row.EMA200))
        trend_down=close<_finite(row.EMA50) and (_finite(row.EMA200) is None or _finite(row.EMA50)<_finite(row.EMA200))
        if ema and pema and trend_up and row.Low<=ema and close>ema and prior_close<=pema and (_finite(row.ADX) or 0)>=setup['adx']: direction='LONG'
        elif ema and pema and trend_down and row.High>=ema and close<ema and prior_close>=pema and (_finite(row.ADX) or 0)>=setup['adx']: direction='SHORT'
    elif sid=='VWAP_RECLAIM':
        level=_finite(row.RVWAP20); plevel=_finite(prev.RVWAP20); rv=_finite(row.RVOL) or 0
        if level and plevel and rv>=setup['rvol']:
            if close>level and prior_close<=plevel: direction='LONG'
            elif close<level and prior_close>=plevel: direction='SHORT'
    elif sid=='DMI_ADX_TREND':
        adx=_finite(row.ADX) or 0; padx=_finite(prev.ADX) or 0
        long_now=row.PLUS_DI>row.MINUS_DI and close>row.EMA50 and adx>=setup['adx']
        short_now=row.MINUS_DI>row.PLUS_DI and close<row.EMA50 and adx>=setup['adx']
        long_before=prev.PLUS_DI>prev.MINUS_DI and prior_close>prev.EMA50 and padx>=setup['adx']
        short_before=prev.MINUS_DI>prev.PLUS_DI and prior_close<prev.EMA50 and padx>=setup['adx']
        if long_now and not long_before: direction='LONG'
        elif short_now and not short_before: direction='SHORT'
    elif sid=='VOLATILITY_EXPANSION':
        width=_finite(row.BB_WIDTH); old=_finite(prev.BB_WIDTH); lowq=_finite(row.BB_LOW_Q); rv=_finite(row.RVOL) or 0
        released=width and old and lowq and old<=lowq and width>old*1.10 and rv>=setup['rvol']
        if released and close>row.EMA20: direction='LONG'
        elif released and close<row.EMA20: direction='SHORT'
    elif sid=='CANDLE_CONTEXT':
        bullish=row.Close>row.Open and prev.Close<prev.Open and row.Open<=prev.Close and row.Close>=prev.Open
        bearish=row.Close<row.Open and prev.Close>prev.Open and row.Open>=prev.Close and row.Close<=prev.Open
        if bullish and row.Low<=row.EMA20 and close>row.EMA50: direction='LONG'
        elif bearish and row.High>=row.EMA20 and close<row.EMA50: direction='SHORT'
    elif sid=='RELATIVE_STRENGTH':
        rs=_finite(row.get('RS20')); prs=_finite(prev.get('RS20'))
        if rs is not None and prs is not None:
            if rs>0 and prs<=0 and close>row.EMA50: direction='LONG'
            elif rs<0 and prs>=0 and close<row.EMA50: direction='SHORT'
    return direction


def detect_signal_experiments(ticker, history, benchmark=None, metadata=None, observed_at=None):
    frame=technical_feature_frame(history,benchmark)
    if frame.empty: return []
    row=frame.iloc[-1]; date=pd.Timestamp(frame.index[-1]).date().isoformat(); meta=metadata or {}
    results=[]
    for setup in SETUPS:
        direction=_trigger(frame,setup)
        if not direction: continue
        identity=f"{ticker}|{setup['id']}|{setup['variant']}|{date}|{direction}|{LAB_VERSION}"
        key=hashlib.sha256(identity.encode()).hexdigest()[:24]
        results.append({
            'signal_key':key,'ticker':str(ticker).upper(),'signal_at':date,
            'recorded_at':_iso(observed_at),'setup_id':setup['id'],'variant':setup['variant'],
            'role':setup['role'],'setup_version':LAB_VERSION,'direction':direction,
            'baseline_price':round(float(row.Close),6),'benchmark_price':_finite(row.get('BENCH_CLOSE')),
            'baseline_atr':round(float(row.ATR14),6),'rvol':_finite(row.RVOL),'adx':_finite(row.ADX),
            'rsi14':_finite(row.RSI14),'distance_ema20_atr':round((row.Close-row.EMA20)/row.ATR14,4),
            'distance_vwap_atr':round((row.Close-row.RVWAP20)/row.ATR14,4),
            'regime':'UPTREND' if row.Close>row.EMA50 else 'DOWNTREND',
            'sector':str(meta.get('sector') or 'Unknown'),'universe_source':str(meta.get('universe_source') or 'Unknown'),
            'market_cap_bucket':str(meta.get('market_cap_bucket') or meta.get('universe_source') or 'Unknown'),
            'shadow_mode':True,'no_execution':True,
        })
    return results


def evaluate_signal_experiments(signals, histories, benchmark=None, existing=None, evaluated_at=None):
    existing_keys={(str(x.get('signal_key')),int(x.get('horizon_days') or 0)) for x in existing or []}
    bench=_clean_history(benchmark); outcomes=[]
    for signal in signals or []:
        hist=_clean_history(histories.get(str(signal.get('ticker')).upper()))
        if hist.empty: continue
        dates=pd.Index(pd.to_datetime(hist.index).date); start=pd.Timestamp(signal.get('signal_at')).date()
        positions=[i for i,value in enumerate(dates) if value>=start]
        if not positions: continue
        base_pos=positions[0]; base=float(signal.get('baseline_price') or hist.iloc[base_pos].Close)
        direction=1 if signal.get('direction')=='LONG' else -1; atr=float(signal.get('baseline_atr') or 0)
        for horizon in HORIZONS:
            key=(str(signal.get('signal_key')),horizon)
            if key in existing_keys or base_pos+horizon>=len(hist): continue
            future=hist.iloc[base_pos+horizon]; path=hist.iloc[base_pos+1:base_pos+horizon+1]
            asset_return=(float(future.Close)/base-1)*100
            bench_return=0.0
            if not bench.empty:
                b=bench.reindex(hist.index).ffill(); b0=_finite(b.iloc[base_pos].Close); b1=_finite(b.iloc[base_pos+horizon].Close)
                if b0 and b1: bench_return=(b1/b0-1)*100
            signed_return=direction*asset_return; signed_alpha=direction*(asset_return-bench_return)
            favorable=((float(path.High.max())/base-1)*100 if direction>0 else (1-float(path.Low.min())/base)*100)
            adverse=((float(path.Low.min())/base-1)*100 if direction>0 else (1-float(path.High.max())/base)*100)
            outcomes.append({
                'outcome_key':f"{signal['signal_key']}:{horizon}",'signal_key':signal['signal_key'],
                'ticker':signal['ticker'],'setup_id':signal['setup_id'],'variant':signal['variant'],
                'role':signal['role'],'direction':signal['direction'],'signal_at':signal['signal_at'],
                'horizon_days':horizon,'status':'MATURED','evaluated_at':_iso(evaluated_at),
                'asset_return_pct':round(asset_return,4),'benchmark_return_pct':round(bench_return,4),
                'signed_return_pct':round(signed_return,4),'signed_alpha_pct':round(signed_alpha,4),
                'mfe_pct':round(favorable,4),'mae_pct':round(adverse,4),
                'mfe_atr':None if not atr else round(favorable/(atr/base*100),4),
                'mae_atr':None if not atr else round(adverse/(atr/base*100),4),
                'success':bool(signed_return>0 and signed_alpha>0),'shadow_mode':True,
            })
    return outcomes


def load_signal_lab_ledger(user_id):
    record=load_desk_output(user_id,'signal_lab_ledger','active') or {}
    payload=record.get('payload') or {}
    return {'signals':list(payload.get('signals') or []),'outcomes':list(payload.get('outcomes') or [])}


def save_signal_lab_ledger(user_id, signals, outcomes):
    payload={'lab_version':LAB_VERSION,'updated_at':_iso(),'signals':list(signals)[-MAX_SIGNALS:],
             'outcomes':list(outcomes)[-MAX_OUTCOMES:],'shadow_mode':True,'no_execution':True}
    return save_desk_output(user_id,'signal_lab_ledger',payload,run_key='active')


def merge_signal_lab_ledger(ledger, new_signals, new_outcomes):
    signals={str(row.get('signal_key')):row for row in ledger.get('signals') or []}
    signals.update({str(row.get('signal_key')):row for row in new_signals or []})
    outcomes={(str(row.get('signal_key')),int(row.get('horizon_days') or 0)):row for row in ledger.get('outcomes') or []}
    outcomes.update({(str(row.get('signal_key')),int(row.get('horizon_days') or 0)):row for row in new_outcomes or []})
    return {'signals':sorted(signals.values(),key=lambda x:(str(x.get('signal_at')),str(x.get('signal_key')))),
            'outcomes':sorted(outcomes.values(),key=lambda x:(str(x.get('evaluated_at')),str(x.get('outcome_key'))))}


def build_daily_signal_lab_report(signals, new_outcomes, universe_size, failures=None, generated_at=None):
    primary=[row for row in new_outcomes if int(row.get('horizon_days') or 0)==PRIMARY_HORIZON]
    return {'status':'CURRENT','generated_at':_iso(generated_at),'lab_version':LAB_VERSION,
            'universe_size':int(universe_size),'new_signals':len(signals),'matured_outcomes':len(new_outcomes),
            'primary_horizon_matured':len(primary),'primary_hit_rate_pct':None if not primary else round(100*sum(bool(x.get('success')) for x in primary)/len(primary),1),
            'signals':list(signals)[:40],'failures':list(failures or [])[:30],
            'policy':'Experiments only. Results do not alter production rules automatically.',
            'shadow_mode':True,'no_execution':True}


def _mean(rows,key):
    values=[_finite(row.get(key)) for row in rows]; values=[x for x in values if x is not None]
    return None if not values else sum(values)/len(values)


def build_weekly_signal_lab_review(signals, outcomes, generated_at=None):
    signal_map={str(row.get('signal_key')):row for row in signals or []}
    groups={}
    for outcome in outcomes or []:
        if int(outcome.get('horizon_days') or 0)!=PRIMARY_HORIZON: continue
        signal=signal_map.get(str(outcome.get('signal_key')))
        if not signal: continue
        key=(str(signal.get('setup_id')),str(signal.get('variant')))
        groups.setdefault(key,[]).append({**outcome,'ticker':signal.get('ticker'),'role':signal.get('role')})
    rows=[]
    for (setup,variant), sample in sorted(groups.items()):
        sample.sort(key=lambda x:(str(x.get('signal_at')),str(x.get('signal_key'))))
        validation_size=max(MIN_REVIEW_VALIDATION,int(round(len(sample)*.30)))
        validation=sample[max(0,len(sample)-validation_size):]
        rows.append({'setup_id':setup,'variant':variant,'role':sample[0].get('role'),'sample':len(sample),
                     'validation_sample':len(validation),'unique_tickers':len({x.get('ticker') for x in sample}),
                     'hit_rate_pct':round(100*sum(bool(x.get('success')) for x in validation)/len(validation),1) if validation else None,
                     'expectancy_alpha_pct':None if not validation else round(_mean(validation,'signed_alpha_pct'),4),
                     'mean_mfe_pct':None if not validation else round(_mean(validation,'mfe_pct'),4),
                     'mean_mae_pct':None if not validation else round(_mean(validation,'mae_pct'),4),
                     'eligible':len(sample)>=MIN_REVIEW_SAMPLE and len(validation)>=MIN_REVIEW_VALIDATION and len({x.get('ticker') for x in sample})>=MIN_REVIEW_TICKERS})
    proposals=[]
    for challenger in [x for x in rows if x['role']=='CHALLENGER' and x['eligible']]:
        champion=next((x for x in rows if x['setup_id']==challenger['setup_id'] and x['role']=='CHAMPION' and x['eligible']),None)
        if not champion: continue
        edge=(challenger['expectancy_alpha_pct'] or 0)-(champion['expectancy_alpha_pct'] or 0)
        hit_guard=(challenger['hit_rate_pct'] or 0)>=(champion['hit_rate_pct'] or 0)-5
        risk_guard=(challenger['mean_mae_pct'] or -999)>=(champion['mean_mae_pct'] or -999)-.5
        if edge>=.15 and hit_guard and risk_guard:
            proposals.append({'setup_id':challenger['setup_id'],'champion':champion['variant'],'challenger':challenger['variant'],
                              'validation_edge_pct':round(edge,4),'status':'HUMAN_REVIEW_REQUIRED'})
    status='REVIEW_PROPOSED' if proposals else 'CHAMPION_RETAINED' if any(x['eligible'] for x in rows) else 'NOT_ENOUGH_DATA'
    return {'status':status,'generated_at':_iso(generated_at),'lab_version':LAB_VERSION,'primary_horizon_days':PRIMARY_HORIZON,
            'setups_reviewed':len(rows),'eligible_variants':sum(bool(x['eligible']) for x in rows),'proposals':proposals,
            'scorecard':rows,'automatic_rule_changes':0,'structural_changes':'HUMAN_REVIEW_REQUIRED',
            'method':'Chronological 70/30 split; comparison uses only the most recent 30% as validation.',
            'shadow_mode':True,'no_execution':True}


def _clip(value,limit=1000):
    text=str(value or '')
    return text if len(text)<=limit else text[:limit-1]+'…'


def build_signal_lab_embed(report, weekly=False):
    if weekly:
        fields=[]
        for row in (report.get('scorecard') or [])[:8]:
            fields.append({'name':_clip(f"{row['setup_id']} · {row['variant']}",256),
                           'value':_clip(f"Rol: **{row['role']}** · muestra: **{row['sample']}** · validación: **{row['validation_sample']}**\nHit: **{row['hit_rate_pct']}%** · alpha esperado: **{row['expectancy_alpha_pct']}%** · elegible: **{row['eligible']}**"),
                           'inline':False})
        fields.append({'name':'Gobernanza','value':'Las propuestas requieren revisión humana. No se cambiaron reglas, código ni posiciones.','inline':False})
        return {'author':{'name':'Market Screener Pro · Technical Signal Lab'},'title':'🧪 Revisión semanal Champion / Challenger',
                'description':f"Estado: **{report.get('status')}** · propuestas: **{len(report.get('proposals') or [])}**",
                'color':0x9B59B6,'fields':fields[:25],'timestamp':report.get('generated_at'),
                'footer':{'text':'SHADOW MODE · Validación cronológica · Sin órdenes ni cambios autónomos'}}
    signals=report.get('signals') or []; lines=[]
    for row in signals[:12]: lines.append(f"**{row.get('ticker')}** · {row.get('direction')} · {row.get('setup_id')} / {row.get('variant')}")
    return {'author':{'name':'Market Screener Pro · Technical Signal Lab'},'title':'📊 Laboratorio diario de señales',
            'description':f"Universo: **{report.get('universe_size')}** · señales nuevas: **{report.get('new_signals')}** · resultados maduros: **{report.get('matured_outcomes')}**",
            'color':0x3498DB,'fields':[{'name':'Señales virtuales','value':_clip('\n'.join(lines) or 'Sin señales nuevas hoy.'),'inline':False},
                     {'name':'Límite','value':'Experimentos estadísticos; no son recomendaciones ni modifican el ranking de producción.','inline':False}],
            'timestamp':report.get('generated_at'),'footer':{'text':'SHADOW MODE · Ninguna orden fue enviada'}}


def notify_signal_lab(user_id, report, run_key, weekly=False, send_fn=send_webhook):
    typ='signal_lab_weekly_delivery' if weekly else 'signal_lab_daily_delivery'
    prior=load_desk_output(user_id,typ,run_key)
    if prior and (prior.get('payload') or {}).get('delivered'): return {'status':'DUPLICATE','delivered':True}
    target=get_user_webhook(user_id)
    if not target: result={'status':'NOT_CONFIGURED','delivered':False}
    else:
        material=weekly or bool(report.get('new_signals')) or bool(report.get('matured_outcomes'))
        if not material: return {'status':'NOT_NEEDED','delivered':False}
        message=('🧪 REVISIÓN SEMANAL DE SEÑALES' if weekly else '📊 LABORATORIO DIARIO DE SEÑALES')+'\nSHADOW MODE · Sin órdenes.'
        delivered=bool(send_fn(message,url=target,discord_embed=build_signal_lab_embed(report,weekly)))
        result={'status':'DELIVERED' if delivered else 'FAILED','delivered':delivered}
    save_desk_output(user_id,typ,{**result,'shadow_mode':True},run_key=run_key)
    return result


def load_latest_signal_lab_report(user_id): return load_latest_desk_output(user_id,'signal_lab_daily_report')
def load_latest_signal_lab_review(user_id): return load_latest_desk_output(user_id,'signal_lab_weekly_review')
