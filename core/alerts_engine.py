import os
from datetime import datetime, timezone
import requests
import pandas as pd

from core.indicators import enrich_indicators
from core.market_data import classify_symbol, get_live_price
from core.asset_models import analyze_asset


def _evaluate_rule_result(rule, price_map, spy=None):
    t=str(rule['ticker']).upper(); raw=price_map.get(t)
    if raw is None or raw.empty: return False,'No market data',{}
    typ_asset=classify_symbol(t)
    h=enrich_indicators(raw); r=analyze_asset(t,h,spy,'Alert',typ_asset)
    typ=rule['rule_type']; th=float(rule['threshold']); hit=False; msg=''
    if typ=='EMA62_DISTANCE':
        v=r.get('Dist_EMA62_%')
        hit=pd.notna(v) and abs(float(v))<=th; msg=f"{t}: EMA62 distance {float(v):+.2f}%" if pd.notna(v) else f'{t}: EMA62 unavailable'
    elif typ=='EMA79_DISTANCE':
        v=r.get('Dist_EMA79_%')
        hit=pd.notna(v) and abs(float(v))<=th; msg=f"{t}: EMA79 distance {float(v):+.2f}%" if pd.notna(v) else f'{t}: EMA79 unavailable'
    elif typ=='ENTRY_SCORE_ABOVE':
        v=r.get('Entry_Score')
        hit=pd.notna(v) and float(v)>=th; msg=f"{t}: Entry Score {float(v):.1f} >= {th:.1f}" if pd.notna(v) else f'{t}: Entry Score unavailable'
    elif typ=='PRICE_BELOW':
        live=get_live_price(t); px=float(live if live is not None else r['Price'])
        hit=px<=th; msg=f"{t}: price {px:.6g} <= {th:.6g}"
    elif typ=='PRICE_ABOVE':
        live=get_live_price(t); px=float(live if live is not None else r['Price'])
        hit=px>=th; msg=f"{t}: price {px:.6g} >= {th:.6g}"
    elif typ=='RR_ABOVE':
        v=r.get('RR')
        hit=pd.notna(v) and float(v)>=th; msg=f"{t}: R/R {r.get('RR_Text',v)} >= {th:.2f}" if pd.notna(v) else f'{t}: R/R unavailable'
    else:
        raise ValueError(f'Unsupported alert rule: {typ}')
    return bool(hit),msg,r


def _number(value,digits=2):
    try:
        value=float(value)
        return round(value,digits) if pd.notna(value) else None
    except Exception:
        return None


def evaluate_rule_with_context(rule, price_map, spy=None):
    """Evaluate one rule and return the local technical evidence used by Discord."""
    hit,message,result=_evaluate_rule_result(rule,price_map,spy)
    context={
        'ticker':result.get('Ticker'),'price':_number(result.get('Price')),
        'trend':result.get('Trend'),'setup':result.get('Setup'),
        'technical_score':_number(result.get('Technical_Score'),0),
        'trend_score':_number(result.get('Trend_Score'),0),
        'entry_score':_number(result.get('Entry_Score'),0),
        'risk_score':_number(result.get('Risk_Score'),0),
        'rsi14':_number(result.get('RSI14'),1),'relative_volume':_number(result.get('Rel_Volume')),
        'relative_strength_63d_pct':_number(result.get('RS_63d_%')),
        'drawdown_pct':_number(result.get('Drawdown_%')),
        'distance_ema62_pct':_number(result.get('Dist_EMA62_%')),
        'distance_ema79_pct':_number(result.get('Dist_EMA79_%')),
        'distance_sma200_pct':_number(result.get('Dist_SMA200_%')),
        'entry_zone':result.get('Entry_Zone'),'invalidation':result.get('Invalidation'),
        'target':result.get('Target'),'rr':_number(result.get('RR')),
        'risk':result.get('Risk'),'comment':result.get('Comment'),
    }
    return hit,message,{key:value for key,value in context.items() if value not in (None,'')}


def evaluate_rule(rule, price_map, spy=None):
    """Backwards-compatible two-value alert evaluator."""
    hit,message,_=_evaluate_rule_result(rule,price_map,spy)
    return hit,message


def _webhook_url(url=''):
    value=str(url or os.getenv('ALERT_WEBHOOK_URL','') or '').strip()
    if value: return value
    try:
        import streamlit as st
        return str(st.secrets.get('ALERT_WEBHOOK_URL','') or '').strip()
    except Exception:
        return ''


def webhook_status(url=''):
    value=_webhook_url(url)
    if not value: return {'configured':False,'provider':'NONE'}
    low=value.lower()
    provider='DISCORD' if 'discord.com/api/webhooks' in low or 'discordapp.com/api/webhooks' in low else 'SLACK' if 'hooks.slack.com' in low else 'GENERIC'
    return {'configured':True,'provider':provider}


RULE_REPORT_LABELS={
    'PRICE_BELOW':'Precio por debajo del nivel','PRICE_ABOVE':'Precio por encima del nivel',
    'ENTRY_SCORE_ABOVE':'Entry Score por encima del mínimo','RR_ABOVE':'R/R por encima del mínimo',
    'EMA62_DISTANCE':'Precio cerca de EMA62','EMA79_DISTANCE':'Precio cerca de EMA79',
}


def _report_clip(value,limit):
    text=str(value or '').strip().replace('\x00','')
    return text if len(text)<=limit else text[:max(0,limit-1)].rstrip()+'…'


def _fmt_number(value,decimals=1,suffix=''):
    try: return f'{float(value):.{decimals}f}{suffix}'
    except Exception: return 'N/D'


def _technical_reading(context):
    bits=[]
    if context.get('price') is not None: bits.append(f"Precio **${float(context['price']):,.2f}**")
    if context.get('trend'): bits.append(f"Tendencia **{_report_clip(context['trend'],45)}**")
    if context.get('setup'): bits.append(f"Setup **{_report_clip(context['setup'],55)}**")
    scores=[]
    for key,label in (('technical_score','Técnico'),('trend_score','Trend'),('entry_score','Entry'),('risk_score','Riesgo')):
        if context.get(key) is not None: scores.append(f"{label} **{float(context[key]):.0f}/100**")
    if scores: bits.append(' · '.join(scores))
    if context.get('comment'): bits.append(_report_clip(context['comment'],300))
    return '\n'.join(bits)


def _participation_reading(context):
    bits=[]
    if context.get('rsi14') is not None: bits.append(f"RSI14 **{_fmt_number(context['rsi14'])}**")
    if context.get('relative_volume') is not None: bits.append(f"Volumen relativo **{_fmt_number(context['relative_volume'],2,'x')}**")
    if context.get('relative_strength_63d_pct') is not None:
        bits.append(f"Fuerza vs SPY 63d **{_fmt_number(context['relative_strength_63d_pct'],1,'%')}**")
    distances=[]
    for key,label in (('distance_ema62_pct','EMA62'),('distance_ema79_pct','EMA79'),('distance_sma200_pct','SMA200')):
        if context.get(key) is not None: distances.append(f"{label} {_fmt_number(context[key],1,'%')}")
    if distances: bits.append('Distancias: '+ ' · '.join(distances))
    if context.get('drawdown_pct') is not None: bits.append(f"Drawdown desde máximo: **{_fmt_number(context['drawdown_pct'],1,'%')}**")
    return '\n'.join(bits)


def _risk_map(context):
    levels=[]
    for key,label in (('entry_zone','Zona observada'),('invalidation','Invalidación técnica'),('target','Referencia técnica')):
        if context.get(key): levels.append(f'{label}: **{_report_clip(context[key],80)}**')
    if context.get('rr') is not None: levels.append(f"R/R estimado: **{float(context['rr']):.2f}:1**")
    if context.get('risk'): levels.append(f"Riesgo técnico: **{_report_clip(context['risk'],35)}**")
    if levels: levels.append('Los niveles son referencias del modelo, no una orden ni una recomendación personalizada.')
    return '\n'.join(levels)


def _portfolio_market_reading(context):
    bits=[]
    if context.get('current_weight_pct') is not None:
        bits.append(f"Posición actual: **{float(context['current_weight_pct']):.1f}%**")
    else: bits.append('Posición actual: **no registrada en la cartera**')
    if context.get('sector'):
        sector=f"Sector: **{_report_clip(context['sector'],55)}**"
        if context.get('sector_weight_pct') is not None: sector+=f" · exposición **{float(context['sector_weight_pct']):.1f}%**"
        bits.append(sector)
    if context.get('cash_pct') is not None: bits.append(f"Efectivo/no asignado: **{float(context['cash_pct']):.1f}%**")
    market=[]
    if context.get('market_regime'): market.append(_report_clip(context['market_regime'],45))
    if context.get('macro_score') is not None: market.append(f"Macro {float(context['macro_score']):.0f}/100")
    if context.get('vix') is not None: market.append(f"VIX {float(context['vix']):.1f}")
    if context.get('breadth') is not None: market.append(f"Breadth {float(context['breadth']):.0f}/100")
    if market: bits.append('Mercado: **'+' · '.join(market)+'**')
    universe=[]
    if context.get('universe_source'): universe.append(_report_clip(context['universe_source'],45))
    if context.get('liquidity_tier'): universe.append('liquidez '+_report_clip(context['liquidity_tier'],25))
    if context.get('opportunity_score') is not None: universe.append(f"Opportunity {float(context['opportunity_score']):.0f}/100")
    if universe: bits.append('Universo: '+' · '.join(universe))
    return '\n'.join(bits)


def _alert_scenario(rule,context):
    typ=str(rule or '')
    if typ in {'PRICE_ABOVE','PRICE_BELOW'}:
        confirmation='Confirmar que el nivel se sostenga al cierre y no sea solamente un movimiento intradiario.'
        invalidation='La lectura pierde validez si el precio revierte y vuelve a cruzar el umbral en sentido contrario.'
    elif typ.startswith('EMA'):
        confirmation='Buscar reacción constructiva alrededor de la media, con estructura y participación consistentes.'
        invalidation='La proximidad a una media no alcanza si el precio rompe soporte o la tendencia se deteriora.'
    elif typ=='ENTRY_SCORE_ABOVE':
        confirmation='Verificar que Entry, tendencia y riesgo permanezcan alineados en el próximo cierre.'
        invalidation='El caso se debilita si el Entry Score cae o aparecen extensión, bajo volumen o ruptura de estructura.'
    else:
        confirmation='Confirmar que el R/R conserve niveles coherentes con la estructura y la volatilidad actuales.'
        invalidation='El R/R deja de ser representativo si cambian la entrada, la invalidación o la referencia técnica.'
    contradictions=[]
    if context.get('entry_score') is not None and float(context['entry_score'])<55: contradictions.append('Entry débil')
    if context.get('trend_score') is not None and float(context['trend_score'])<55: contradictions.append('tendencia débil')
    if context.get('relative_volume') is not None and float(context['relative_volume'])<.8: contradictions.append('participación inferior a la media')
    if contradictions: invalidation+=' Contrastes actuales: '+', '.join(contradictions)+'.'
    return f'**Confirmación:** {confirmation}\n**Invalidación:** {invalidation}'


def build_discord_rule_alert(alert,message,trigger_reason='EDGE',now=None,context=None):
    """Build a professional saved-alert embed without interpreting it as a trade signal."""
    ticker=str(alert.get('ticker') or 'ACTIVO').upper(); rule=str(alert.get('rule_type') or 'ALERTA')
    reason={'EDGE':'Nueva activación','COOLDOWN':'Repetición después del cooldown'}.get(str(trigger_reason),str(trigger_reason))
    fields=[{'name':'Condición','value':_report_clip(RULE_REPORT_LABELS.get(rule,rule.replace('_',' ').title()),1024),'inline':True},
            {'name':'Umbral configurado','value':_report_clip(alert.get('threshold','N/D'),1024),'inline':True},
            {'name':'Tipo de aviso','value':_report_clip(reason,1024),'inline':True}]
    context=dict(context or {})
    technical=_technical_reading(context)
    if technical: fields.append({'name':'📈 Lectura técnica','value':_report_clip(technical,1024),'inline':False})
    participation=_participation_reading(context)
    if participation: fields.append({'name':'🔬 Confluencia y participación','value':_report_clip(participation,1024),'inline':False})
    risk_map=_risk_map(context)
    if risk_map: fields.append({'name':'🛡️ Mapa de riesgo','value':_report_clip(risk_map,1024),'inline':False})
    portfolio_market=_portfolio_market_reading(context) if context else ''
    if portfolio_market: fields.append({'name':'🧩 Cartera, mercado y universo','value':_report_clip(portfolio_market,1024),'inline':False})
    note=str(alert.get('note') or '').strip()
    if note: fields.append({'name':'Tu nota','value':_report_clip(note,1024),'inline':False})
    if context: fields.append({'name':'🧭 Escenario y validación','value':_report_clip(_alert_scenario(rule,context),1024),'inline':False})
    fields.append({'name':'➡️ Próximo paso','value':'Abrir el activo en Investment Desk, contrastar la evidencia y revisar el efecto sobre la cartera antes de decidir.','inline':False})
    stamp=now if isinstance(now,datetime) else datetime.now(timezone.utc)
    if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
    color=0x2ECC71 if rule in {'PRICE_ABOVE','ENTRY_SCORE_ABOVE','RR_ABOVE'} else 0xF39C12 if rule.startswith('EMA') else 0x3498DB
    embed={'author':{'name':'Market Screener Pro · Saved Alerts'},'title':_report_clip(f'🔔 {ticker} · condición alcanzada',256),
           'description':_report_clip(message,1400),'color':color,'fields':fields[:25],
           'timestamp':stamp.astimezone(timezone.utc).isoformat(),
           'footer':{'text':'SHADOW MODE · Alerta informativa · Ninguna orden fue enviada'}}
    used=len(embed['author']['name'])+len(embed['title'])+len(embed['description'])+len(embed['footer']['text'])
    bounded=[]
    for field in embed['fields']:
        name=_report_clip(field.get('name'),256); available=5900-used-len(name)
        if available<40: break
        value=_report_clip(field.get('value'),min(1024,available))
        bounded.append({'name':name,'value':value,'inline':bool(field.get('inline'))})
        used+=len(name)+len(value)
    embed['fields']=bounded
    return embed


def build_discord_channel_test(now=None):
    stamp=now if isinstance(now,datetime) else datetime.now(timezone.utc)
    if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
    return {'author':{'name':'Market Screener Pro · Investment Desk'},
            'title':'✅ Canal de informes conectado',
            'description':'Discord está listo para recibir los nuevos informes estructurados.',
            'color':0x2ECC71,
            'fields':[{'name':'Alertas inmediatas','value':'Solo ante eventos materiales o reglas guardadas que se activen.','inline':False},
                      {'name':'Informe premarket','value':'Un resumen del CIO por cada día hábil.','inline':False}],
            'timestamp':stamp.astimezone(timezone.utc).isoformat(),
            'footer':{'text':'SHADOW MODE · Prueba de formato · Ninguna orden fue enviada'}}


def send_webhook(message, url='', discord_embed=None):
    target=_webhook_url(url)
    if not target: return False
    provider=webhook_status(target)['provider']
    if provider=='DISCORD' and isinstance(discord_embed,dict):
        payload={'username':'Investment Desk','embeds':[discord_embed],'allowed_mentions':{'parse':[]}}
    elif provider=='DISCORD': payload={'content':_report_clip(message,1950),'allowed_mentions':{'parse':[]}}
    elif provider=='SLACK': payload={'text':str(message)}
    else: payload={'text':str(message),'content':str(message)}
    try:
        request_kwargs={'json':payload,'timeout':10}
        if provider=='DISCORD': request_kwargs['params']={'wait':'true'}
        r=requests.post(target,**request_kwargs)
        return 200<=r.status_code<300
    except Exception:
        return False
