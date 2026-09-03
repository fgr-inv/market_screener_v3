"""Professional Discord/Slack reports for automated Investment Desk outputs."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import urlparse

from core.alerts_engine import send_webhook
from core.notification_settings import get_user_webhook
from core.desk_store import load_desk_output,save_desk_output


REPORT_VERSION='2.0'
COLORS={'POSITIVE':0x2ECC71,'NEGATIVE':0xE74C3C,'WARNING':0xF39C12,'NEUTRAL':0x3498DB}
STATE_LABELS={
    'SETUP':'Setup técnico','WATCH':'En observación','BROKEN_SETUP':'Setup invalidado',
    'IMPROVING':'Fundamentales mejorando','INTACT':'Tesis intacta','MIXED':'Señales mixtas',
    'DETERIORATING':'Fundamentales deteriorándose','RISK_ON':'Riesgo favorable',
    'RISK_OFF':'Riesgo defensivo','ELEVATED':'Riesgo elevado','HIGH_RISK':'Riesgo alto',
    'MATERIAL_POSITIVE':'Catalizador positivo','MATERIAL_NEGATIVE':'Catalizador negativo',
    'MATERIAL_REVIEW':'Catalizador a revisar','MIXED_CATALYSTS':'Catalizadores mixtos',
    'MONITOR':'Monitorear','NOT_CHECKED':'No evaluado','NEUTRAL':'Neutral',
}
DIRECTION_LABELS={'POSITIVE':'Positiva','NEGATIVE':'Negativa','NEUTRAL':'Neutral'}
THESIS_LABELS={
    'CATALYST_MATCH':'Coincide con un catalizador guardado',
    'POTENTIAL_INVALIDATION_MATCH':'Coincide con una condición de invalidación',
    'POTENTIAL_THESIS_RISK':'Riesgo potencial para la tesis',
    'POTENTIAL_THESIS_SUPPORT':'Soporte potencial para la tesis',
    'REVIEW_REQUIRED':'Requiere revisión','NO_MATERIAL_LINK':'Sin vínculo material detectado',
}
VERIFICATION_LABELS={
    'VERIFIED':'Verificado','VERIFIED_CANDIDATE':'Candidata verificada',
    'PARTIALLY_VERIFIED':'Verificación parcial','UNVERIFIED':'No verificado',
    'NOT_CHECKED':'No evaluado','FAILED':'No superó la verificación',
}


def _clip(value,limit):
    text=str(value or '').strip().replace('\x00','')
    text=re.sub(r'[ \t]+',' ',text); text=re.sub(r'\n{3,}','\n\n',text)
    return text if len(text)<=limit else text[:max(0,limit-1)].rstrip()+'…'


def _pct(value):
    try: return f'{float(value)*100:.0f}%'
    except Exception: return 'N/D'


def _state(value):
    raw=str(value or 'NOT_CHECKED').upper()
    return STATE_LABELS.get(raw,raw.replace('_',' ').title())


def _safe_url(value):
    url=str(value or '').strip()
    try: return url if urlparse(url).scheme in {'http','https'} else ''
    except Exception: return ''


def _discord_time(value):
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return f'<t:{int(dt.timestamp())}:f> · <t:{int(dt.timestamp())}:R>'
    except Exception:
        return _clip(value,80) or 'Hora no disponible'


def _field(name,value,inline=False):
    return {'name':_clip(name,256) or 'Detalle','value':_clip(value,1024) or 'N/D','inline':bool(inline)}


def _material_events(brief):
    return [event for event in brief.get('events_considered') or [] if int(event.get('severity') or 0)>=4]


def _event_field(event,index=0):
    story=((event.get('metrics') or {}).get('story') or {})
    ticker=str(event.get('ticker') or story.get('ticker') or 'MERCADO').upper()
    category=str(story.get('category') or ', '.join(event.get('event_types') or []) or 'EVENTO').replace('_',' ')
    direction=str(story.get('direction') or 'NEUTRAL').upper(); emoji={'POSITIVE':'🟢','NEGATIVE':'🔴'}.get(direction,'🟡')
    title=story.get('title') or '; '.join(event.get('reasons') or []) or 'Evento material detectado'
    lines=[f'**{_clip(title,420)}**',
           f'{emoji} Dirección: **{DIRECTION_LABELS.get(direction,direction.title())}** · Severidad: **{int(event.get("severity") or story.get("severity") or 0)}/5**']
    impact=THESIS_LABELS.get(str(story.get('thesis_impact') or ''),str(story.get('thesis_impact') or '').replace('_',' ').title())
    if impact: lines.append(f'🧩 Tesis: {impact}')
    if story.get('published_at'): lines.append(f'🕒 {_discord_time(story.get("published_at"))}')
    source=_clip(story.get('publisher') or (event.get('metrics') or {}).get('source'),100)
    url=_safe_url(story.get('url'))
    source_status='Fuente primaria' if story.get('primary_source') else 'Fuente secundaria; confirmar documento original'
    if source or url:
        label=source or 'Abrir fuente'; linked=f'[{label}]({url})' if url else label
        lines.append(f'🔗 {linked} · {source_status}')
    return _field(f'{emoji} {ticker} · {category}', '\n'.join(lines),False)


def _opportunity_text(rows):
    lines=[]
    for row in list(rows or [])[:5]:
        ticker=str(row.get('Ticker') or row.get('subject') or 'N/D').upper()
        score=row.get('Priority Score'); score_text='N/D'
        try: score_text=f'{float(score):.1f}'
        except Exception: pass
        technical=_state(row.get('Technical','N/D')); fundamental=_state(row.get('Fundamental','N/D'))
        lines.append(f'**{ticker}** · prioridad **{score_text}** · Técnico: {technical} · Fundamental: {fundamental}')
    return '\n'.join(lines)


def _decision_text(rows):
    lines=[]
    for row in list(rows or [])[:5]:
        subject=str(row.get('subject') or 'N/D').upper(); state=_state(row.get('state'))
        verification=str(row.get('verification_status') or 'NOT_CHECKED').upper()
        verification=VERIFICATION_LABELS.get(verification,verification.replace('_',' ').title())
        lines.append(f'**{subject}** · {state} · confianza {_pct(row.get("confidence"))} · verificación: {verification}')
    return '\n'.join(lines)


def _next_action(brief):
    states={str(row.get('state') or '').upper() for row in brief.get('decisions_needed') or []}
    if states & {'MATERIAL_NEGATIVE','BROKEN_SETUP','DETERIORATING','HIGH_RISK'}:
        return 'Revisar la tesis, su condición de invalidación y el riesgo de posición antes de tomar cualquier decisión.'
    if 'MIXED_CATALYSTS' in states:
        return 'Resolver las señales contradictorias y abrir las fuentes originales antes de decidir.'
    if states & {'MATERIAL_POSITIVE','SETUP','IMPROVING'}:
        return 'Confirmar la fuente primaria y exigir validación técnica, fundamental y de cartera antes de actuar.'
    return 'Revisar Investment Desk para ver la evidencia completa. No se requiere una operación automática.'


def _tone(brief):
    states={str(row.get('state') or '').upper() for row in brief.get('decisions_needed') or []}
    directions={str((((event.get('metrics') or {}).get('story') or {}).get('direction') or '')).upper()
                for event in _material_events(brief)}
    if states & {'BROKEN_SETUP','DETERIORATING','HIGH_RISK','RISK_OFF'}:
        return 'NEGATIVE'
    if states & {'MIXED_CATALYSTS','MATERIAL_REVIEW','ELEVATED'} or ({'POSITIVE','NEGATIVE'}<=directions):
        return 'WARNING'
    if 'MATERIAL_NEGATIVE' in states or 'NEGATIVE' in directions:
        return 'NEGATIVE'
    if states & {'MATERIAL_POSITIVE','SETUP','IMPROVING'} or 'POSITIVE' in directions:
        return 'POSITIVE'
    return 'NEUTRAL'


def _headline(brief,daily=False):
    raw=str(brief.get('headline') or '')
    if daily:
        decisions=len(brief.get('decisions_needed') or [])
        return ('No hay decisiones urgentes; el monitoreo continúa.' if not decisions else
                f'{decisions} elemento(s) requieren revisión humana antes de la apertura.')
    events=_material_events(brief)
    if events: return f'Se detectaron {len(events)} evento(s) material(es) que requieren revisión.'
    if raw: return raw
    return 'El Investment Desk detectó un cambio material.'


def build_discord_cio_embed(brief,report_type='material'):
    """Build a bounded Discord embed without exposing secrets or implying a trade."""
    daily=report_type=='daily'; events=_material_events(brief); fields=[]
    market=brief.get('market_regime') or {}; risk=brief.get('principal_risk') or {}
    if daily:
        if str(market.get('state') or 'NOT_CHECKED')!='NOT_CHECKED':
            fields.append(_field('🌎 Régimen de mercado',f'**{_state(market.get("state"))}** · confianza {_pct(market.get("confidence"))}\n{market.get("summary") or "Sin observación adicional."}'))
        if str(risk.get('state') or 'NOT_CHECKED')!='NOT_CHECKED':
            fields.append(_field('🛡️ Riesgo principal',f'**{_state(risk.get("state"))}**\n{risk.get("summary") or "Sin observación adicional."}'))
        opportunities=_opportunity_text(brief.get('top_opportunities'))
        if opportunities: fields.append(_field('🎯 Oportunidades verificadas',opportunities))
    for index,event in enumerate(events[:3]): fields.append(_event_field(event,index))
    if not daily:
        if str(risk.get('state') or 'NOT_CHECKED')!='NOT_CHECKED':
            fields.append(_field('🛡️ Riesgo principal',f'**{_state(risk.get("state"))}**\n{risk.get("summary") or "Sin observación adicional."}'))
        if str(market.get('state') or 'NOT_CHECKED')!='NOT_CHECKED':
            fields.append(_field('🌎 Contexto de mercado',f'**{_state(market.get("state"))}** · confianza {_pct(market.get("confidence"))}\n{market.get("summary") or "Sin observación adicional."}'))
    decisions=_decision_text(brief.get('decisions_needed'))
    if decisions: fields.append(_field('📋 Decisiones para revisar',decisions))
    reasons=list(brief.get('material_reasons') or [])
    if reasons and not events:
        fields.append(_field('⚠️ Motivos materiales','\n'.join(f'• {_clip(reason,430)}' for reason in reasons[:4])))
    fields.append(_field('➡️ Próximo paso',_next_action(brief)))
    first_story=((((events[0].get('metrics') or {}).get('story') or {}) if events else {}))
    first_ticker=str(events[0].get('ticker') or '') if events else ''
    if daily: title='📊 Informe premarket del CIO'
    elif len(events)==1: title=f'🚨 {first_ticker} · {first_story.get("category") or "evento material"}'
    else: title=f'🚨 Alerta material del Investment Desk ({max(len(events),1)})'
    embed={'author':{'name':'Market Screener Pro · Investment Desk'},'title':_clip(title,256),
           'description':_clip(_headline(brief,daily),1200),'color':COLORS[_tone(brief)],
           'fields':fields[:25],'timestamp':datetime.now(timezone.utc).isoformat(),
           'footer':{'text':f'SHADOW MODE · Investigación solamente · Informe v{REPORT_VERSION} · Ninguna orden fue enviada'}}
    source_url=_safe_url(first_story.get('url'))
    if source_url: embed['url']=source_url
    fixed=sum(len(str(embed.get(key) or '')) for key in ('title','description'))
    fixed+=len(embed['author']['name'])+len(embed['footer']['text'])
    bounded=[]; used=fixed
    for field in embed['fields']:
        name=_clip(field.get('name'),256); available=5900-used-len(name)
        if available<40: break
        value=_clip(field.get('value'),min(1024,available))
        bounded.append({'name':name,'value':value,'inline':bool(field.get('inline'))})
        used+=len(name)+len(value)
    embed['fields']=bounded
    return embed


def format_cio_alert(brief,report_type='material'):
    """Readable fallback for Slack and generic webhooks."""
    daily=report_type=='daily'; lines=[('📊 INFORME PREMARKET DEL CIO' if daily else '🚨 ALERTA MATERIAL DEL INVESTMENT DESK'),
                                      _headline(brief,daily)]
    market=brief.get('market_regime') or {}; risk=brief.get('principal_risk') or {}
    if daily and str(market.get('state') or '')!='NOT_CHECKED': lines.append(f'🌎 Mercado: {_state(market.get("state"))} — {market.get("summary","")}')
    if str(risk.get('state') or '')!='NOT_CHECKED': lines.append(f'🛡️ Riesgo: {_state(risk.get("state"))} — {risk.get("summary","")}')
    opportunities=_opportunity_text(brief.get('top_opportunities'))
    if daily and opportunities: lines.extend(['🎯 Oportunidades:',opportunities.replace('**','')])
    for event in _material_events(brief)[:3]:
        story=((event.get('metrics') or {}).get('story') or {}); ticker=str(event.get('ticker') or 'N/D').upper()
        direction=str(story.get('direction') or 'NEUTRAL').upper()
        lines.append(f'• {ticker} · {story.get("category","EVENTO")} · {DIRECTION_LABELS.get(direction,"Neutral")} · severidad {event.get("severity","N/D")}/5')
        lines.append(f'  {_clip(story.get("title") or "; ".join(event.get("reasons") or []),500)}')
        if story.get('thesis_impact'): lines.append(f'  Tesis: {THESIS_LABELS.get(story.get("thesis_impact"),story.get("thesis_impact"))}')
        if _safe_url(story.get('url')): lines.append(f'  Fuente: {story.get("url")}')
    lines.extend([f'➡️ {_next_action(brief)}','SHADOW MODE · Investigación solamente · Ninguna orden fue enviada.'])
    return _clip('\n'.join(line for line in lines if str(line).strip()),3900)


def _notify(user_id,brief,run_key,output_type,report_type,require_material,send_fn=None):
    uid=str(user_id or 'local-user'); key=str(run_key)
    if require_material and not brief.get('material'):
        return {'status':'NOT_MATERIAL','delivered':False,'attempted':False,'report_type':report_type}
    prior=load_desk_output(uid,output_type,key)
    if prior and bool((prior.get('payload') or {}).get('delivered')):
        return {'status':'DUPLICATE','delivered':True,'attempted':False,'report_type':report_type}
    target=get_user_webhook(uid)
    if not target:
        payload={'status':'NOT_CONFIGURED','delivered':False,'attempted':False,'report_type':report_type,
                 'report_version':REPORT_VERSION,'shadow_mode':True}
        save_desk_output(uid,output_type,payload,run_key=key); return payload
    sender=send_fn or send_webhook; message=format_cio_alert(brief,report_type)
    embed=build_discord_cio_embed(brief,report_type)
    try: delivered=bool(sender(message,url=target,discord_embed=embed))
    except TypeError as exc:
        if 'discord_embed' not in str(exc): raise
        delivered=bool(sender(message,url=target))
    payload={'status':'DELIVERED' if delivered else 'FAILED','delivered':delivered,'attempted':True,
             'report_type':report_type,'report_version':REPORT_VERSION,'shadow_mode':True}
    save_desk_output(uid,output_type,payload,run_key=key); return payload


def notify_material_brief(user_id,brief,run_key,send_fn=send_webhook):
    """Deliver material alerts once; failed sends remain retriable."""
    return _notify(user_id,brief,run_key,'cio_alert_delivery','material',True,send_fn)


def notify_daily_cio_brief(user_id,brief,run_key):
    """Deliver exactly one premarket report per market date, even without an urgent event."""
    return _notify(user_id,brief,run_key,'cio_daily_delivery','daily',False)
