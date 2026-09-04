"""Freshness checks and low-noise notifications for scheduled automation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from core.alerts_engine import send_webhook
from core.desk_store import load_desk_output, load_latest_desk_output, save_desk_output
from core.notification_settings import get_user_webhook
from core.storage import load_json_snapshot, load_positions
from core.market_calendar import (is_us_equity_session,previous_us_equity_session,
                                  expected_market_date as calendar_expected_market_date)


NEW_YORK=ZoneInfo('America/New_York')
PROCESS_LABELS={
    'saved_alerts':'Alertas guardadas',
    'intraday_desk':'Cartera y watchlist intradiaria',
    'portfolio_news':'Noticias prioritarias de cartera',
    'watchlist_news':'Noticias de cartera y watchlist',
    'daily_cio':'Informe premarket del CIO',
    'daily_snapshot':'Snapshot completo del mercado',
    'opportunity_hunt':'Búsqueda diaria de oportunidades',
    'shadow_validation':'Validación Shadow 1/5/20',
    'skill_calibration':'Calibración semanal',
    'continuous_improvement':'Mejora continua semanal',
}


def _utc(value):
    if isinstance(value,datetime):
        stamp=value
    else:
        try: stamp=datetime.fromisoformat(str(value or '').replace('Z','+00:00'))
        except Exception: return None
    if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _local(value=None):
    stamp=value if isinstance(value,datetime) else datetime.now(NEW_YORK)
    if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=NEW_YORK)
    return stamp.astimezone(NEW_YORK)


def _record_time(record):
    if not record: return None
    payload=record.get('payload') or {}
    return _utc(payload.get('observed_at') or payload.get('market_time') or record.get('created_at'))


def _age_minutes(record,now):
    observed=_record_time(record)
    if observed is None: return None
    return max(0,(now.astimezone(timezone.utc)-observed).total_seconds()/60)


def _expected_market_date(now,cutoff_minutes):
    return calendar_expected_market_date(now,cutoff_minutes)


def _record_local_date(record):
    stamp=_record_time(record)
    return stamp.astimezone(NEW_YORK).date() if stamp else None


def _check_age(process,record,due,max_age_minutes,now,detail=''):
    label=PROCESS_LABELS[process]
    if not due:
        return {'process':process,'label':label,'status':'NOT_DUE','age_minutes':None,
                'max_age_minutes':max_age_minutes,'last_success_at':None,'detail':detail}
    age=_age_minutes(record,now); observed=_record_time(record)
    if age is None: status='MISSING'
    elif age>max_age_minutes: status='STALE'
    else: status='CURRENT'
    return {'process':process,'label':label,'status':status,
            'age_minutes':None if age is None else round(age,1),'max_age_minutes':max_age_minutes,
            'last_success_at':observed.isoformat() if observed else None,'detail':detail}


def _check_business_date(process,record,due,expected_date,now,detail=''):
    label=PROCESS_LABELS[process]; observed=_record_time(record); actual=_record_local_date(record)
    if not due:
        status='NOT_DUE'
    elif actual is None:
        status='MISSING'
    elif actual<expected_date:
        status='STALE'
    else:
        status='CURRENT'
    age=_age_minutes(record,now)
    return {'process':process,'label':label,'status':status,
            'age_minutes':None if age is None else round(age,1),'max_age_minutes':None,
            'expected_market_date':expected_date.isoformat(),
            'last_success_at':observed.isoformat() if observed else None,'detail':detail}


def record_automation_heartbeat(user_id,process,status='CURRENT',details=None,now=None):
    """Persist only the latest heartbeat; frequent monitors do not grow one row per run."""
    uid=str(user_id or 'local-user'); name=re.sub(r'[^a-z0-9_]+','_',str(process).lower()).strip('_')
    payload={'process':name,'status':str(status or 'CURRENT').upper(),
             'observed_at':_local(now).astimezone(timezone.utc).isoformat(),
             'details':details or {},'shadow_mode':True}
    return save_desk_output(uid,f'automation_heartbeat_{name}',payload,run_key='latest')


def build_automation_health(user_id,now=None,current_failures=None):
    """Evaluate only processes that should already have run at the supplied market time."""
    uid=str(user_id or 'local-user'); local_now=_local(now); minutes=local_now.hour*60+local_now.minute
    market_day=is_us_equity_session(local_now); weekday=local_now.weekday()<5
    cash_window=market_day and 10*60+15<=minutes<=16*60+15
    news_window=weekday and 8*60+30<=minutes<=19*60+45
    positions=load_positions(user_id=uid)
    has_positions=bool(positions is not None and not positions.empty)

    checks=[]
    alert_limit=55 if cash_window else 105
    checks.append(_check_age('saved_alerts',load_latest_desk_output(uid,'automation_heartbeat_saved_alerts'),
                             True,alert_limit,local_now,'Cada 15 min en mercado; cada hora fuera de mercado.'))
    checks.append(_check_age('intraday_desk',load_latest_desk_output(uid,'event_scan'),cash_window,55,local_now,
                             'Cartera y watchlist prioritaria durante la sesión de EE. UU.'))
    full_news=load_latest_desk_output(uid,'news_catalyst_scan')
    priority_news=load_latest_desk_output(uid,'news_catalyst_priority_scan')
    priority_source=priority_news or full_news
    priority_limit=80 if priority_news else 45
    priority_detail=('Solo posiciones actuales; cada 30 minutos.' if priority_news else
                     'Cobertura temporal del pase completo hasta que se registre el primer pase prioritario.')
    checks.append(_check_age('portfolio_news',priority_source,bool(news_window and has_positions),
                             priority_limit,local_now,priority_detail))
    checks.append(_check_age('watchlist_news',full_news,
                             news_window,110,local_now,'Cartera y watchlist; cada hora.'))

    cio_expected=_expected_market_date(local_now,9*60)
    checks.append(_check_business_date('daily_cio',load_latest_desk_output(uid,'daily_cio_brief'),
                                       market_day and minutes>=9*60,cio_expected,local_now,'Una vez antes de la apertura.'))
    postclose_due=market_day and minutes>=20*60+30
    postclose_expected=_expected_market_date(local_now,20*60+30)
    meta=load_json_snapshot('latest_meta') or {}
    snapshot_record={'created_at':meta.get('generated_at'),'payload':{}} if meta.get('generated_at') else None
    checks.append(_check_business_date('daily_snapshot',snapshot_record,postclose_due,postclose_expected,local_now,
                                       'Universo amplio después del cierre.'))
    checks.append(_check_business_date('opportunity_hunt',load_latest_desk_output(uid,'daily_opportunity_hunt'),
                                       postclose_due,postclose_expected,local_now,'Shortlist diaria verificada.'))
    checks.append(_check_business_date('shadow_validation',load_latest_desk_output(uid,'shadow_validation'),
                                       postclose_due,postclose_expected,local_now,'Resultados a 1, 5 y 20 ruedas.'))
    calibration_due=local_now.weekday()==5 and minutes>=11*60
    checks.append(_check_age('skill_calibration',load_latest_desk_output(uid,'automation_heartbeat_skill_calibration'),
                             calibration_due,7*24*60+180,local_now,'Revisión semanal del sábado.'))
    improvement_due=local_now.weekday()==5 and minutes>=12*60
    checks.append(_check_age('continuous_improvement',
                             load_latest_desk_output(uid,'automation_heartbeat_continuous_improvement'),
                             improvement_due,7*24*60+180,local_now,
                             'Champion/challenger semanal; ajustes automáticos limitados a confianza.'))

    failures={str(key):str(value) for key,value in (current_failures or {}).items() if value}
    for process,reason in failures.items():
        match=next((row for row in checks if row['process']==process),None)
        if match:
            match['status']='FAILED'; match['detail']=reason
        else:
            checks.append({'process':process,'label':PROCESS_LABELS.get(process,process.replace('_',' ').title()),
                           'status':'FAILED','age_minutes':None,'max_age_minutes':None,
                           'last_success_at':None,'detail':reason})
    issues=[row for row in checks if row['status'] in {'MISSING','STALE','FAILED'}]
    signature=hashlib.sha256(json.dumps([(row['process'],row['status']) for row in issues],sort_keys=True).encode()).hexdigest()[:20]
    return {'status':'DEGRADED' if issues else 'HEALTHY','generated_at':local_now.astimezone(timezone.utc).isoformat(),
            'market_time':local_now.isoformat(),'checks':checks,'issues':issues,'issue_count':len(issues),
            'signature':signature,'shadow_mode':True}


def _clip(value,limit):
    text=re.sub(r'[ \t]+',' ',str(value or '').strip().replace('\x00',''))
    return text if len(text)<=limit else text[:max(0,limit-1)].rstrip()+'…'


def build_discord_health_embed(report,recovered=False):
    issues=report.get('issues') or []
    if recovered:
        title='✅ Automatización recuperada'; description='Todos los procesos que correspondía ejecutar volvieron a estar actualizados.'; color=0x2ECC71
        fields=[{'name':'Estado','value':'**HEALTHY** · El monitoreo automático continúa normalmente.','inline':False}]
    else:
        title='⚠️ Automatización atrasada'; description=f'{len(issues)} proceso(s) requieren revisión. Las demás automatizaciones continúan funcionando.'; color=0xE74C3C
        fields=[]
        for row in issues[:8]:
            age='sin ejecución registrada' if row.get('age_minutes') is None else f"hace {row['age_minutes']:.0f} min"
            detail=row.get('detail') or 'No se recibió una actualización dentro de la ventana esperada.'
            fields.append({'name':_clip(f"🔴 {row.get('label')} · {row.get('status')}",256),
                           'value':_clip(f'Último dato: {age}\n{detail}',1024),'inline':False})
        fields.append({'name':'Próximo paso','value':'Abrir GitHub Actions, localizar el workflow rojo o atrasado y ejecutarlo manualmente. No se modificó ninguna posición.','inline':False})
    return {'author':{'name':'Market Screener Pro · Automation Watchdog'},'title':title,
            'description':description,'color':color,'fields':fields[:25],
            'timestamp':report.get('generated_at') or datetime.now(timezone.utc).isoformat(),
            'footer':{'text':'SHADOW MODE · Control de infraestructura · Ninguna orden fue enviada'}}


def format_health_notification(report,recovered=False):
    if recovered: return '✅ AUTOMATIZACIÓN RECUPERADA\nTodos los procesos esperados volvieron a estar actualizados.'
    lines=['⚠️ AUTOMATIZACIÓN ATRASADA']
    for row in (report.get('issues') or [])[:8]:
        age='sin registro' if row.get('age_minutes') is None else f"{row['age_minutes']:.0f} min"
        lines.append(f"- {row.get('label')}: {row.get('status')} ({age})")
    lines.extend(['Revisar GitHub Actions.','SHADOW MODE · Ninguna orden fue enviada.'])
    return _clip('\n'.join(lines),3900)


def notify_automation_health(user_id,report,now=None,send_fn=send_webhook,reminder_hours=6):
    """Notify on a new incident, changed issue set, periodic reminder, or recovery."""
    uid=str(user_id or 'local-user'); current=_local(now).astimezone(timezone.utc)
    previous_record=load_desk_output(uid,'automation_health_state','current') or {}
    previous=previous_record.get('payload') or {}; status=str(report.get('status') or 'HEALTHY')
    prior_status=str(previous.get('status') or 'UNKNOWN'); same_signature=report.get('signature')==previous.get('signature')
    last_alert=_utc(previous.get('last_notification_at'))
    reminder_due=last_alert is None or (current-last_alert).total_seconds()>=float(reminder_hours)*3600
    recovered=(status=='HEALTHY' and prior_status=='DEGRADED' and
               bool(previous.get('last_notification_at')))
    new_incident=status=='DEGRADED' and (prior_status!='DEGRADED' or not same_signature)
    repeated_incident=status=='DEGRADED' and same_signature and reminder_due
    should_send=bool(recovered or new_incident or repeated_incident)
    notification={'status':'NOT_NEEDED','attempted':False,'delivered':False,'recovered':recovered}
    if should_send:
        target=get_user_webhook(uid)
        if not target:
            notification={'status':'NOT_CONFIGURED','attempted':False,'delivered':False,'recovered':recovered}
        else:
            delivered=bool(send_fn(format_health_notification(report,recovered),url=target,
                                   discord_embed=build_discord_health_embed(report,recovered)))
            notification={'status':'DELIVERED' if delivered else 'FAILED','attempted':True,
                          'delivered':delivered,'recovered':recovered}
    incident_started=(previous.get('incident_started_at') if status=='DEGRADED' and prior_status=='DEGRADED' and same_signature
                      else current.isoformat() if status=='DEGRADED' else None)
    last_notification=(current.isoformat() if notification.get('delivered') else previous.get('last_notification_at'))
    state={**report,'incident_started_at':incident_started,'last_notification_at':last_notification,
           'notification':notification}
    save_desk_output(uid,'automation_health_state',state,run_key='current')
    return notification
