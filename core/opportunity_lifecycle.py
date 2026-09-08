"""Professional opportunity lifecycle and coherent virtual Shadow Book.

This coordinator consumes existing verified research. It does not replace an
agent, mutate production rankings, connect to a broker, or create real orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
import pandas as pd

from core.alerts_engine import send_webhook
from core.desk_store import load_desk_output, load_latest_desk_output, save_desk_output
from core.notification_settings import get_user_webhook
from core.portfolio_positions import resolve_position_allocations
from core.factor_risk import factor_profile


LIFECYCLE_VERSION='1.0'
VIRTUAL_NAV=50_000.0
STOP_ATR=1.5
TARGET_R=2.0
MAX_WEEKLY_NEW_RISK_PCT=2.0
MAX_OPEN_POSITIONS=12
MAX_SECTOR_WEIGHT_PCT=30.0
SLEEVE_POLICY={
    'CORE':{'risk_pct':.75,'max_weight_pct':8.0,'slippage_bps':5.0,'commission_bps':2.0},
    'SMID':{'risk_pct':.50,'max_weight_pct':4.0,'slippage_bps':10.0,'commission_bps':2.0},
    'CRYPTO':{'risk_pct':.35,'max_weight_pct':3.0,'slippage_bps':15.0,'commission_bps':10.0},
}


def _finite(value,default=None):
    try:
        number=float(value)
        return number if math.isfinite(number) else default
    except Exception: return default


def _iso(value=None):
    stamp=pd.Timestamp(value or datetime.now(timezone.utc))
    if stamp.tzinfo is None: stamp=stamp.tz_localize('UTC')
    return stamp.tz_convert('UTC').isoformat()


def _clean_history(frame):
    if frame is None or frame.empty: return pd.DataFrame()
    out=frame.copy()
    if isinstance(out.columns,pd.MultiIndex): out.columns=[str(col[0]) for col in out.columns]
    required=['Open','High','Low','Close']
    if any(column not in out for column in required): return pd.DataFrame()
    return out.sort_index().apply(pd.to_numeric,errors='coerce').dropna(subset=required)


def classify_sleeve(row):
    ticker=str(row.get('Ticker') or row.get('ticker') or '').upper()
    source=str(row.get('Universe Source') or row.get('universe_source') or '')
    segment=str(row.get('Cap Segment') or row.get('market_cap_bucket') or '')
    if ticker.endswith('-USD'): return 'CRYPTO'
    if source=='S&P 500' or segment=='Large Cap': return 'CORE'
    return 'SMID'


def _news_map(news_payload):
    rows=(news_payload or {}).get('stories') or (news_payload or {}).get('actionable_events') or []
    output={}
    for raw in rows:
        story=((raw.get('metrics') or {}).get('story') or raw)
        ticker=str(story.get('ticker') or raw.get('ticker') or '').upper()
        if not ticker: continue
        material=bool(story.get('material') or int(story.get('severity') or raw.get('severity') or 0)>=4)
        primary=bool(story.get('primary_source'))
        if material: output.setdefault(ticker,[]).append({'primary':primary,'title':story.get('title'),
            'published_at':story.get('published_at'),'direction':story.get('direction'),'url':story.get('url')})
    return output


def build_opportunity_lifecycle(shortlist,verified,signals,theses=None,news_payload=None,generated_at=None,
                                confirmations=None):
    """Build transparent stages; absence of evidence never becomes a neutral pass."""
    verified_map={str(row.get('Ticker','')).upper():row for row in verified or []}
    signal_map={}
    for row in signals or []:
        if str(row.get('setup_version'))!='2.0': continue
        signal_map.setdefault(str(row.get('ticker','')).upper(),[]).append(row)
    thesis_map={str(row.get('ticker','')).upper():row for row in theses or []}
    news_map=_news_map(news_payload)
    confirmation_map={str(key).upper():value for key,value in (confirmations or {}).items()}
    candidates=[]
    for seed in shortlist or []:
        ticker=str(seed.get('Ticker','')).upper(); checked=verified_map.get(ticker); ticker_signals=signal_map.get(ticker,[])
        thesis=thesis_map.get(ticker,{}) or {}; stories=news_map.get(ticker,[])
        fundamental=str((checked or {}).get('Fundamental') or 'NOT_CHECKED').upper()
        technical=str((checked or {}).get('Technical') or 'NOT_CHECKED').upper()
        source_verified=any(story.get('primary') for story in stories)
        thesis_active=str(thesis.get('status') or '').upper() in {'ACTIVE','WATCH',''} and bool(thesis.get('thesis'))
        evidence_ok=bool(checked and fundamental in {'IMPROVING','INTACT'} and
                         int(_finite(checked.get('Verified Specialists'),0))>=2)
        thesis_or_catalyst=bool(thesis_active or source_verified)
        entry_score=_finite(seed.get('Entry Score'),0); rr=_finite(seed.get('RR'),0)
        signal_ok=bool(ticker_signals)
        confirmation=confirmation_map.get(ticker) or {}
        confirmation_ok=bool(confirmation.get('gate_pass'))
        reasons=[]
        if not checked: reasons.append('SPECIALIST_VERIFICATION_PENDING')
        if fundamental not in {'IMPROVING','INTACT'}: reasons.append('FUNDAMENTAL_GATE_NOT_PASSED')
        if not signal_ok: reasons.append('NO_CURRENT_TECHNICAL_TRIGGER')
        if signal_ok and not confirmation_ok: reasons.append('REGIME_OR_MULTITIMEFRAME_NOT_CONFIRMED')
        if not thesis_or_catalyst: reasons.append('NO_ACTIVE_THESIS_OR_PRIMARY_CATALYST')
        if entry_score<60: reasons.append('ENTRY_SCORE_BELOW_60')
        if rr and rr<1.5: reasons.append('RISK_REWARD_BELOW_1_5')
        if str(thesis.get('status') or '').upper()=='INVALIDATED': reasons.append('THESIS_INVALIDATED')
        if 'THESIS_INVALIDATED' in reasons: stage='INVALIDATED'
        elif evidence_ok and thesis_or_catalyst and signal_ok and confirmation_ok and entry_score>=60 and (rr==0 or rr>=1.5): stage='ENTRY_READY'
        elif evidence_ok: stage='EVIDENCE_VERIFIED'
        elif checked: stage='WATCHLIST'
        else: stage='DISCOVERED'
        sleeve=classify_sleeve(seed)
        key=hashlib.sha256(f"{ticker}|{pd.Timestamp(generated_at or datetime.now()).date()}".encode()).hexdigest()[:20]
        opportunity_key=next((row.get('opportunity_key') or row.get('signal_key')
                              for row in ticker_signals if row.get('opportunity_key') or row.get('signal_key')),None)
        candidates.append({**seed,'lifecycle_key':key,'ticker':ticker,'stage':stage,'sleeve':sleeve,
            'evidence_gate':evidence_ok,'thesis_or_catalyst_gate':thesis_or_catalyst,
            'technical_trigger':signal_ok,'fundamental_state':fundamental,
            'confirmation_gate':confirmation_ok,'confirmation':confirmation,
            'confirmation_score':confirmation.get('confirmation_score'),
            'weekly_bias':confirmation.get('weekly_bias'),'daily_bias':confirmation.get('daily_bias'),
            'hourly_bias':confirmation.get('hourly_bias'),'market_regime':confirmation.get('market_regime'),
            'volatility_regime':(confirmation.get('volatility_regime') or {}).get('state'),
            'relative_strength_spy_20d':(confirmation.get('relative_strength_spy') or {}).get('rs20_pct'),
            'relative_strength_sector_20d':(confirmation.get('relative_strength_sector') or {}).get('rs20_pct'),
            'breadth_state':(confirmation.get('breadth') or {}).get('state'),
            'breakout_quality':(confirmation.get('breakout_quality') or {}).get('score'),
            'technical_state':technical,'active_thesis':thesis_active,'primary_catalyst':source_verified,
            'material_catalysts':len(stories),'signal_keys':[row.get('signal_key') for row in ticker_signals],
            'opportunity_key':opportunity_key,
            'gate_reasons':reasons,'generated_at':_iso(generated_at),'shadow_mode':True,'no_execution':True})
    counts={stage:sum(row['stage']==stage for row in candidates) for stage in
            ('DISCOVERED','WATCHLIST','EVIDENCE_VERIFIED','ENTRY_READY','INVALIDATED')}
    return {'version':LIFECYCLE_VERSION,'generated_at':_iso(generated_at),'candidates':candidates,
            'stage_counts':counts,'shadow_mode':True,'no_execution':True}


def _max_correlation(ticker,active,history_map):
    candidate=_clean_history(history_map.get(ticker))
    if candidate.empty: return None,None
    best=None; peer=None
    for position in active:
        other=str(position.get('ticker','')).upper()
        if other==ticker: continue
        frame=_clean_history(history_map.get(other))
        if frame.empty: continue
        joined=pd.concat([candidate.Close.pct_change(),frame.Close.pct_change()],axis=1).dropna().tail(126)
        if len(joined)<30: continue
        value=_finite(joined.corr().iloc[0,1])
        if value is not None and (best is None or value>best): best=value; peer=other
    return best,peer


def _size_candidate(candidate,signal,active,history_map,weekly_risk_used,nav,factor_context=None):
    sleeve=candidate['sleeve']; policy=SLEEVE_POLICY[sleeve]
    if any(str(row.get('ticker','')).upper()==candidate['ticker'] for row in active):
        return None,'ALREADY_HELD_OR_ACTIVE'
    price=_finite(signal.get('baseline_price')); atr=_finite(signal.get('baseline_atr'))
    if not price or not atr: return None,'MISSING_PRICE_OR_ATR'
    risk_pct=policy['risk_pct']; correlation,peer=_max_correlation(candidate['ticker'],active,history_map)
    if correlation is not None and correlation>=.95: return None,f'CORRELATION_BLOCK_{peer}_{correlation:.2f}'
    if correlation is not None and correlation>=.80: risk_pct*=.5
    profile=factor_profile(candidate['ticker'],history_map)
    market_beta=_finite(profile.get('market_beta'))
    dominant=profile.get('dominant_factor')
    factor_weight=_finite(((factor_context or {}).get('dominant_factor_weights_pct') or {}).get(dominant),0)
    if market_beta is not None and abs(market_beta)>=2.25:
        return None,f'EXTREME_MARKET_BETA_{market_beta:.2f}'
    if factor_weight>=70: return None,f'FACTOR_CAP_EXCEEDED_{dominant}_{factor_weight:.1f}'
    if (market_beta is not None and abs(market_beta)>=1.50) or factor_weight>=50: risk_pct*=.5
    if weekly_risk_used+risk_pct>MAX_WEEKLY_NEW_RISK_PCT: return None,'WEEKLY_RISK_BUDGET_EXHAUSTED'
    risk_per_unit=STOP_ATR*atr
    units_by_risk=(nav*risk_pct/100)/risk_per_unit
    units_by_weight=(nav*policy['max_weight_pct']/100)/price
    units=max(0,min(units_by_risk,units_by_weight))
    weight_pct=units*price/nav*100
    sector=str(candidate.get('Sector') or 'Unknown')
    sector_weight=sum(_finite(row.get('planned_weight_pct'),0) for row in active if str(row.get('sector'))==sector)
    if sector_weight+weight_pct>MAX_SECTOR_WEIGHT_PCT: return None,'SECTOR_CAP_EXCEEDED'
    return {'risk_budget_pct':round(risk_pct,4),'planned_weight_pct':round(weight_pct,4),
            'planned_units':round(units,8),'reference_price':price,'atr':atr,'correlation':correlation,
            'correlation_peer':peer,'slippage_bps':policy['slippage_bps'],
            'commission_bps':policy['commission_bps'],'market_beta':market_beta,
            'dominant_factor':dominant,'portfolio_factor_weight_pct':factor_weight,'policy':policy},None


def _fill_pending(position,history):
    frame=_clean_history(history)
    if frame.empty: return position
    signal_date=pd.Timestamp(position['signal_at']).date()
    eligible=frame[[pd.Timestamp(index).date()>signal_date for index in frame.index]]
    if eligible.empty: return position
    date=eligible.index[0]; raw=float(eligible.iloc[0].Open); direction=1 if position['direction']=='LONG' else -1
    slip=position['slippage_bps']; entry=raw*(1+direction*slip/10000)
    risk=STOP_ATR*position['atr']
    return {**position,'status':'OPEN','entry_date':str(pd.Timestamp(date).date()),'raw_entry_price':round(raw,6),
            'entry_price':round(entry,6),'stop_price':round(entry-direction*risk,6),
            'target_price':round(entry+direction*risk*TARGET_R,6),'last_updated_at':_iso()}


def _update_open(position,history,now=None):
    frame=_clean_history(history)
    if frame.empty or not position.get('entry_date'): return position
    start=pd.Timestamp(position['entry_date']).date(); path=frame[[pd.Timestamp(i).date()>=start for i in frame.index]]
    if path.empty: return position
    direction=1 if position['direction']=='LONG' else -1; stop=float(position['stop_price']); target=float(position['target_price'])
    exit_price=None; reason=None; exit_date=None
    for index,row in path.iterrows():
        opening=float(row.Open)
        if direction>0:
            if opening<=stop: exit_price,reason=opening,'STOP_GAP'
            elif opening>=target: exit_price,reason=opening,'TARGET_GAP'
            elif float(row.Low)<=stop: exit_price,reason=stop,'STOP'
            elif float(row.High)>=target: exit_price,reason=target,'TARGET'
        else:
            if opening>=stop: exit_price,reason=opening,'STOP_GAP'
            elif opening<=target: exit_price,reason=opening,'TARGET_GAP'
            elif float(row.High)>=stop: exit_price,reason=stop,'STOP'
            elif float(row.Low)<=target: exit_price,reason=target,'TARGET'
        if reason: exit_date=index; break
    if reason is None and len(path)>=20:
        exit_price=float(path.iloc[19].Close); exit_date=path.index[19]; reason='TIME_20D'
    if reason is None:
        latest=float(path.iloc[-1].Close); unrealized=direction*(latest/float(position['entry_price'])-1)*100
        return {**position,'last_price':round(latest,6),'unrealized_pct':round(unrealized,4),'last_updated_at':_iso(now)}
    slip=float(position['slippage_bps']); net_exit=exit_price*(1-direction*slip/10000)
    gross=direction*(net_exit/float(position['entry_price'])-1)*100
    net=gross-2*float(position['commission_bps'])/100
    return {**position,'status':'EXITED','exit_date':str(pd.Timestamp(exit_date).date()),
            'raw_exit_price':round(exit_price,6),'exit_price':round(net_exit,6),'exit_reason':reason,
            'net_return_pct':round(net,4),'pnl_virtual':round(float(position['planned_units'])*(net_exit-float(position['entry_price']))*direction,2),
            'last_updated_at':_iso(now)}


def portfolio_risk_context(positions,histories):
    """Translate the authoritative saved portfolio into sizing-only constraints."""
    detail,meta=resolve_position_allocations(positions,histories)
    if detail is None or detail.empty or meta.get('status')=='OVER_ALLOCATED': return []
    return [{'ticker':str(row.get('Ticker','')).upper(),'sector':str(row.get('Sector') or 'Unknown'),
             'planned_weight_pct':_finite(row.get('Weight %'),0),'source':'SAVED_PORTFOLIO'}
            for _,row in detail.iterrows() if _finite(row.get('Weight %'),0)>0]


def update_shadow_book(lifecycle,signals,histories,existing=None,generated_at=None,nav=VIRTUAL_NAV,
                       portfolio_context=None,factor_context=None):
    book=list((existing or {}).get('positions') or []); signal_map={str(row.get('signal_key')):row for row in signals or []}
    updated=[]
    for position in book:
        if position.get('status')=='PENDING_ENTRY': position=_fill_pending(position,histories.get(position['ticker']))
        if position.get('status')=='OPEN': position=_update_open(position,histories.get(position['ticker']),generated_at)
        updated.append(position)
    active=[row for row in updated if row.get('status') in {'PENDING_ENTRY','OPEN'}]
    iso=pd.Timestamp(generated_at or datetime.now()).isocalendar(); week_key=f'{iso.year}-W{iso.week:02d}'
    weekly_risk=sum(_finite(row.get('risk_budget_pct'),0) for row in updated if row.get('created_week')==week_key)
    existing_opportunities={row.get('opportunity_key') for row in updated}
    rejected=[]
    ready=sorted([row for row in lifecycle.get('candidates',[]) if row.get('stage')=='ENTRY_READY'],
                 key=lambda row:_finite(row.get('Priority Score'),0),reverse=True)
    for candidate in ready:
        opportunity_key=candidate.get('opportunity_key')
        if not opportunity_key: continue
        if opportunity_key in existing_opportunities: continue
        if len(active)>=MAX_OPEN_POSITIONS:
            rejected.append({'ticker':candidate['ticker'],'reason':'MAX_OPEN_POSITIONS'}); continue
        signal=next((signal_map.get(key) for key in candidate.get('signal_keys',[]) if signal_map.get(key)),None)
        if not signal: continue
        sizing,reason=_size_candidate(candidate,signal,active+list(portfolio_context or []),histories,weekly_risk,nav,
                                      factor_context=factor_context)
        if reason:
            rejected.append({'ticker':candidate['ticker'],'reason':reason}); continue
        position={'book_key':hashlib.sha256(f"{candidate['opportunity_key']}|{LIFECYCLE_VERSION}".encode()).hexdigest()[:24],
            'opportunity_key':candidate['opportunity_key'],'ticker':candidate['ticker'],'sector':candidate.get('Sector','Unknown'),
            'sleeve':candidate['sleeve'],'direction':signal['direction'],'setup_id':signal['setup_id'],
            'signal_key':signal['signal_key'],'signal_at':signal['signal_at'],'status':'PENDING_ENTRY',
            'confirmation_score':candidate.get('confirmation_score'),'market_regime':candidate.get('market_regime'),
            'weekly_bias':candidate.get('weekly_bias'),'daily_bias':candidate.get('daily_bias'),
            'hourly_bias':candidate.get('hourly_bias'),
            'structural_invalidation':(candidate.get('confirmation') or {}).get('structural_invalidation'),
            'structural_invalidation_price':(candidate.get('confirmation') or {}).get('structural_invalidation_price'),
            'created_at':_iso(generated_at),'created_week':week_key,**sizing,'stop_atr':STOP_ATR,'target_r':TARGET_R,
            'shadow_mode':True,'no_execution':True}
        updated.append(position); active.append(position); existing_opportunities.add(opportunity_key)
        weekly_risk+=sizing['risk_budget_pct']
    statuses={name:sum(row.get('status')==name for row in updated) for name in ('PENDING_ENTRY','OPEN','EXITED','INVALIDATED')}
    return {'version':LIFECYCLE_VERSION,'updated_at':_iso(generated_at),'virtual_nav':float(nav),'positions':updated[-2000:],
            'status_counts':statuses,'new_rejections':rejected,'weekly_risk_used_pct':round(weekly_risk,4),
            'cash_is_valid':True,'shadow_mode':True,'no_execution':True}


def build_lifecycle_report(lifecycle,book,generated_at=None):
    exited=[row for row in book.get('positions',[]) if row.get('status')=='EXITED']
    return {'generated_at':_iso(generated_at),'stage_counts':lifecycle.get('stage_counts',{}),
            'candidates':lifecycle.get('candidates',[]),'book':book,
            'closed_trades':len(exited),'profitable_closed':sum(_finite(row.get('net_return_pct'),0)>0 for row in exited),
            'policy':{'max_weekly_new_risk_pct':MAX_WEEKLY_NEW_RISK_PCT,'max_open_positions':MAX_OPEN_POSITIONS,
                      'max_sector_weight_pct':MAX_SECTOR_WEIGHT_PCT,'sleeves':SLEEVE_POLICY},
            'shadow_mode':True,'no_execution':True}


def save_lifecycle_state(user_id,report,run_key):
    save_desk_output(user_id,'opportunity_lifecycle_report',report,run_key=run_key)
    return save_desk_output(user_id,'opportunity_shadow_book',report['book'],run_key='active')


def load_shadow_book(user_id):
    record=load_desk_output(user_id,'opportunity_shadow_book','active') or {}
    return record.get('payload') or {'positions':[]}


def notify_lifecycle(user_id,report,run_key,send_fn=send_webhook):
    prior=load_desk_output(user_id,'opportunity_lifecycle_delivery',run_key)
    if prior and (prior.get('payload') or {}).get('delivered'): return {'status':'DUPLICATE','delivered':True}
    stages=report.get('stage_counts') or {}; book=report.get('book') or {}
    report_date=pd.Timestamp(report.get('generated_at')).date()
    new_positions=[row for row in book.get('positions',[]) if
                   str(row.get('created_at',''))[:10]==str(report_date)]
    new_exits=[row for row in book.get('positions',[]) if row.get('status')=='EXITED' and
               str(row.get('exit_date',''))==str(report_date)]
    ready=[row for row in report.get('candidates',[]) if row.get('stage')=='ENTRY_READY']
    material=bool(ready or new_positions or new_exits)
    if not material: return {'status':'NOT_NEEDED','delivered':False}
    target=get_user_webhook(user_id)
    if not target: result={'status':'NOT_CONFIGURED','delivered':False}
    else:
        fields=[{'name':'Pipeline','value':' · '.join(f'{key}: **{value}**' for key,value in stages.items()),'inline':False},
                {'name':'Shadow Book','value':' · '.join(f'{key}: **{value}**' for key,value in (book.get('status_counts') or {}).items()),'inline':False},
                {'name':'Riesgo','value':f"Riesgo nuevo semanal: **{book.get('weekly_risk_used_pct',0):.2f}%** / {MAX_WEEKLY_NEW_RISK_PCT:.2f}% NAV",'inline':False},
                {'name':'Gobernanza','value':'Investigación y fills virtuales. Ninguna orden fue creada ni enviada.','inline':False}]
        factor_risk=report.get('factor_risk') or {}
        if factor_risk:
            betas=factor_risk.get('portfolio_factor_betas') or {}
            fields.insert(3,{'name':'Riesgo por factores (proxies)',
                'value':' · '.join(f'{key}: **{value:+.2f}β**' for key,value in betas.items()),'inline':False})
        for candidate in ready[:5]:
            ticker=candidate.get('ticker'); position=next((row for row in new_positions if row.get('ticker')==ticker),None)
            value=(f"**{candidate.get('sleeve')} · {candidate.get('fundamental_state')}**\n"
                   f"Señal: `{candidate.get('technical_state')}` · Entry score: **{_finite(candidate.get('Entry Score'),0):.0f}** · confirmación MTF: **{_finite(candidate.get('confirmation_score'),0):.0f}/100**\n"
                   f"Semanal/diario/1h: **{candidate.get('weekly_bias')} / {candidate.get('daily_bias')} / {candidate.get('hourly_bias')}**\n"
                   f"Catalizadores materiales: **{candidate.get('material_catalysts',0)}** · fuente primaria: **{'sí' if candidate.get('primary_catalyst') else 'no registrada'}**")
            if position:
                value+=(f"\nPeso virtual: **{position.get('planned_weight_pct',0):.2f}%** · riesgo: **{position.get('risk_budget_pct',0):.2f}% NAV**"
                        f" · β mercado: **{_finite(position.get('market_beta'),0):.2f}** · factor: **{position.get('dominant_factor','N/D')}**"
                        f" · entrada: próxima apertura")
            fields.append({'name':f"🧭 {ticker} · ENTRY READY",'value':value[:1024],'inline':False})
        for position in new_exits[:5]:
            fields.append({'name':f"📌 {position.get('ticker')} · VIRTUAL EXIT",
                           'value':(f"Motivo: **{position.get('exit_reason')}** · retorno neto: **{position.get('net_return_pct',0):.2f}%**\n"
                                    f"P&L virtual: **${position.get('pnl_virtual',0):,.2f}**")[:1024],'inline':False})
        embed={'author':{'name':'Market Screener Pro · Opportunity Lifecycle'},'title':'📚 Pipeline y Shadow Book',
               'description':'Del descubrimiento a la validación virtual, con riesgo y evidencia separados.',
               'color':0x3498DB,'fields':fields[:25],'timestamp':report.get('generated_at'),
               'footer':{'text':'SHADOW MODE · Sin broker · Cash es una posición válida'}}
        delivered=bool(send_fn('📚 OPPORTUNITY LIFECYCLE · SHADOW MODE',url=target,discord_embed=embed))
        result={'status':'DELIVERED' if delivered else 'FAILED','delivered':delivered}
    save_desk_output(user_id,'opportunity_lifecycle_delivery',result,run_key=run_key)
    return result


def load_latest_lifecycle_report(user_id): return load_latest_desk_output(user_id,'opportunity_lifecycle_report')
