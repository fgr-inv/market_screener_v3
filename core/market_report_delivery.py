"""Bounded multi-part delivery for developed macro/sector reports."""
from __future__ import annotations

from datetime import datetime, timezone
import re

from core.alerts_engine import send_webhook, webhook_status
from core.desk_store import load_desk_output, save_desk_output
from core.macro_sector_strategist import render_market_report_markdown
from core.notification_settings import get_user_webhook


def _clip(value,limit=1000):
    text=re.sub(r'\n{3,}','\n\n',str(value or '').strip())
    return text if len(text)<=limit else text[:limit-1].rstrip()+'…'


def build_market_report_embeds(report):
    frequency=report.get('report_type','daily'); color=0x3498DB if frequency=='daily' else 0x8E44AD
    first={'author':{'name':'Market Screener Pro · Market Strategist'},'title':report.get('title'),
           'description':_clip(report.get('executive_summary'),1400),'color':color,'fields':[],
           'timestamp':report.get('generated_at') or datetime.now(timezone.utc).isoformat(),
           'footer':{'text':'EVIDENCE-GROUNDED · SHADOW MODE · Sin órdenes'}}
    macro='\n\n'.join(report.get('macro_analysis') or [])
    first['fields'].append({'name':'🌍 Situación macro','value':_clip(macro,1024),'inline':False})
    scenarios=report.get('scenarios') or {}
    first['fields'].append({'name':'🧭 Escenarios','value':_clip(
        f"**Base:** {scenarios.get('base','N/D')}\n**Alcista:** {scenarios.get('bull','N/D')}\n**Bajista:** {scenarios.get('bear','N/D')}",1024),'inline':False})
    verification=report.get('verification') or {}
    first['fields'].append({'name':'✅ Verificación','value':_clip(
        f"{verification.get('status','N/D')} · {verification.get('sector_count',0)} sectores · snapshot {verification.get('snapshot_age_hours','N/D')} h",1024),'inline':False})
    embeds=[first]
    sectors=report.get('sector_analysis') or []
    for start in range(0,len(sectors),4):
        batch=sectors[start:start+4]
        embeds.append({'author':{'name':'Market Screener Pro · Sector Desk'},
                       'title':f'Análisis sectorial · parte {start//4+1}',
                       'description':'Lectura narrativa basada en amplitud, tendencia, fuerza relativa y contexto macro.',
                       'color':color,'fields':[{'name':f"{row.get('sector')} · {row.get('state')}",
                                               'value':_clip(row.get('analysis'),1024),'inline':False} for row in batch],
                       'timestamp':report.get('generated_at'),
                       'footer':{'text':'Los líderes citados son evidencia, no recomendaciones.'}})
    return embeds


def _text_chunks(text,limit=3500):
    paragraphs=str(text).split('\n\n'); chunks=[]; current=''
    for paragraph in paragraphs:
        candidate=(current+'\n\n'+paragraph).strip()
        if current and len(candidate)>limit:
            chunks.append(current); current=paragraph
        else: current=candidate
    if current: chunks.append(current)
    return chunks


def notify_market_report(user_id,report,run_key,send_fn=send_webhook):
    uid=str(user_id or 'local-user'); frequency=str(report.get('report_type') or 'daily')
    output_type=f'market_analysis_{frequency}_delivery'
    prior=load_desk_output(uid,output_type,run_key); prior_payload=(prior or {}).get('payload') or {}
    if prior_payload.get('delivered'):
        return {'status':'DUPLICATE','delivered':True,'attempted':False}
    if (report.get('verification') or {}).get('status')=='REJECTED':
        payload={'status':'REJECTED','delivered':False,'attempted':False,'reason':'REPORT_VERIFICATION_FAILED'}
        save_desk_output(uid,output_type,payload,run_key=run_key); return payload
    target=get_user_webhook(uid)
    if not target:
        payload={'status':'NOT_CONFIGURED','delivered':False,'attempted':False}
        save_desk_output(uid,output_type,payload,run_key=run_key); return payload
    provider=webhook_status(target)['provider']; results=[]
    completed={int(value) for value in prior_payload.get('delivered_parts') or []}
    parts=(build_market_report_embeds(report) if provider=='DISCORD'
           else _text_chunks(render_market_report_markdown(report)))
    for index,part in enumerate(parts,1):
        if index in completed:
            results.append(True); continue
        ok=bool(send_fn(f'{report.get("title")} · {index}',url=target,discord_embed=part)) if provider=='DISCORD' else bool(send_fn(part,url=target))
        results.append(ok)
        if ok:
            completed.add(index)
            save_desk_output(uid,output_type,{'status':'PARTIAL','delivered':False,'attempted':True,
                'parts':len(parts),'parts_delivered':len(completed),'delivered_parts':sorted(completed),
                'report_version':report.get('schema_version')},run_key=run_key)
    delivered=bool(parts) and len(completed)==len(parts)
    payload={'status':'DELIVERED' if delivered else 'FAILED','delivered':delivered,'attempted':True,
             'parts':len(parts),'parts_delivered':len(completed),'delivered_parts':sorted(completed),
             'report_version':report.get('schema_version')}
    save_desk_output(uid,output_type,payload,run_key=run_key); return payload
