from datetime import datetime, timezone
from pathlib import Path

import core.alerts_engine as alerts_engine
import core.desk_notifications as notifications


NOW=datetime(2026,9,3,14,30,tzinfo=timezone.utc)


def _brief(direction='NEGATIVE',state='MATERIAL_NEGATIVE',material=True):
    story={'ticker':'AMD','title':'AMD updates its financial outlook','category':'GUIDANCE',
           'direction':direction,'severity':5,'thesis_impact':'POTENTIAL_THESIS_RISK',
           'publisher':'AMD Investor Relations','published_at':'2026-09-03T14:00:00+00:00',
           'url':'https://example.test/amd-release','primary_source':True}
    event={'ticker':'AMD','severity':5,'event_types':['news_catalyst','news_guidance'],
           'reasons':['GUIDANCE: AMD updates its financial outlook'],'metrics':{'story':story}}
    return {'headline':'1 verified item requires review','material':material,
            'material_reasons':['AMD guidance changed'],'events_considered':[event],
            'market_regime':{'state':'RISK_OFF','confidence':.82,'summary':'Credit and breadth are defensive.'},
            'principal_risk':{'state':'ELEVATED','summary':'Portfolio concentration remains elevated.'},
            'top_opportunities':[{'Ticker':'MSFT','Priority Score':81.4,'Technical':'SETUP','Fundamental':'INTACT'}],
            'decisions_needed':[{'subject':'AMD','agent':'News & Catalyst','state':state,'confidence':.88,
                                 'verification_status':'VERIFIED'}]}


def _embed_characters(embed):
    total=sum(len(str(embed.get(key) or '')) for key in ('title','description'))
    total+=len(str((embed.get('author') or {}).get('name') or ''))
    total+=len(str((embed.get('footer') or {}).get('text') or ''))
    total+=sum(len(str(field.get('name') or ''))+len(str(field.get('value') or '')) for field in embed.get('fields') or [])
    return total


def test_material_discord_report_leads_with_event_and_source():
    embed=notifications.build_discord_cio_embed(_brief(),'material')
    assert 'AMD' in embed['title'] and embed['url']=='https://example.test/amd-release'
    assert embed['color']==notifications.COLORS['NEGATIVE']
    assert embed['fields'][0]['name'].startswith('🔴 AMD')
    assert '[AMD Investor Relations](https://example.test/amd-release)' in embed['fields'][0]['value']
    assert 'Fuente primaria' in embed['fields'][0]['value']
    assert 'Ninguna orden fue enviada' in embed['footer']['text']


def test_daily_report_prioritizes_market_risk_and_opportunities():
    embed=notifications.build_discord_cio_embed(_brief(direction='POSITIVE',state='MATERIAL_POSITIVE'),'daily')
    names=[field['name'] for field in embed['fields']]
    assert embed['title']=='📊 Informe premarket del CIO'
    assert names[:3]==['🌎 Régimen de mercado','🛡️ Riesgo principal','🎯 Oportunidades verificadas']
    assert 'MSFT' in embed['fields'][2]['value']
    assert 'Setup técnico' in embed['fields'][2]['value'] and 'Tesis intacta' in embed['fields'][2]['value']
    decisions=next(field['value'] for field in embed['fields'] if field['name']=='📋 Decisiones para revisar')
    assert 'verificación: Verificado' in decisions


def test_discord_embed_is_bounded_under_platform_limits():
    brief=_brief(); brief['headline']='x'*9000
    brief['market_regime']['summary']='m'*9000; brief['principal_risk']['summary']='r'*9000
    brief['events_considered']=brief['events_considered']*10
    embed=notifications.build_discord_cio_embed(brief,'daily')
    assert len(embed['title'])<=256 and len(embed['description'])<=4096 and len(embed['fields'])<=25
    assert all(len(field['name'])<=256 and len(field['value'])<=1024 for field in embed['fields'])
    assert _embed_characters(embed)<=5900


def test_discord_webhook_uses_embed_and_disables_mentions(monkeypatch):
    captured={}
    class Response: status_code=204
    def post(url,**kwargs): captured.update({'url':url,**kwargs}); return Response()
    monkeypatch.setattr(alerts_engine.requests,'post',post)
    embed=notifications.build_discord_cio_embed(_brief(),'material')
    ok=alerts_engine.send_webhook('fallback',url='https://discord.com/api/webhooks/id/token',discord_embed=embed)
    assert ok is True and captured['json']['embeds']==[embed]
    assert captured['json']['allowed_mentions']=={'parse':[]}
    assert 'content' not in captured['json']
    assert captured['params']=={'wait':'true'}


def test_slack_keeps_text_fallback(monkeypatch):
    captured={}
    class Response: status_code=200
    monkeypatch.setattr(alerts_engine.requests,'post',lambda url,**kwargs:(captured.update(kwargs['json']) or Response()))
    assert alerts_engine.send_webhook('plain report',url='https://hooks.slack.com/services/a/b/c',discord_embed={'title':'ignored'})
    assert captured=={'text':'plain report'}


def test_saved_alert_has_distinct_compact_report():
    alert={'ticker':'NVDA','rule_type':'ENTRY_SCORE_ABOVE','threshold':75,'note':'Revisar entrada'}
    embed=alerts_engine.build_discord_rule_alert(alert,'NVDA: Entry Score 82 >= 75','EDGE',NOW)
    assert 'NVDA' in embed['title'] and embed['color']==0x2ECC71
    assert any(field['name']=='Tu nota' and 'Revisar entrada' in field['value'] for field in embed['fields'])
    assert embed['timestamp'].startswith('2026-09-03T14:30:00')


def test_channel_test_previews_both_report_types():
    embed=alerts_engine.build_discord_channel_test(NOW)
    assert 'Alertas' in embed['fields'][0]['name'] and 'premarket' in embed['fields'][1]['name']
    assert embed['color']==0x2ECC71


def test_daily_report_is_sent_without_material_event_and_is_idempotent(monkeypatch):
    stored={}; calls=[]
    monkeypatch.setattr(notifications,'get_user_webhook',lambda uid:'https://discord.com/api/webhooks/id/token')
    monkeypatch.setattr(notifications,'load_desk_output',lambda uid,typ,key:stored.get((typ,key)))
    monkeypatch.setattr(notifications,'save_desk_output',lambda uid,typ,payload,run_key=None:stored.update({(typ,run_key):{'payload':payload}}))
    monkeypatch.setattr(notifications,'send_webhook',lambda *args,**kwargs:(calls.append(kwargs) or True))
    brief=_brief(material=False); brief['events_considered']=[]; brief['decisions_needed']=[]
    first=notifications.notify_daily_cio_brief('u',brief,'daily-2026-09-03')
    second=notifications.notify_daily_cio_brief('u',brief,'daily-2026-09-03')
    assert first['status']=='DELIVERED' and second['status']=='DUPLICATE' and len(calls)==1
    assert calls[0]['discord_embed']['title']=='📊 Informe premarket del CIO'


def test_v11361_contract_and_manual_daily_retry():
    config=Path('core/config.py').read_text(encoding='utf-8')
    daily=Path('scripts/run_daily_cio_brief.py').read_text(encoding='utf-8')
    alert_worker=Path('scripts/run_alerts.py').read_text(encoding='utf-8')
    saved_alerts=Path('views/saved_alerts.py').read_text(encoding='utf-8')
    assert 'APP_VERSION = "11.36.1"' in config
    assert "GITHUB_EVENT_NAME" in daily and 'notify_daily_cio_brief' in daily
    assert 'build_discord_rule_alert' in alert_worker
    assert 'build_discord_channel_test' in saved_alerts
    assert 'Informe premarket en Discord' in Path('views/alerts.py').read_text(encoding='utf-8')
    assert all(term not in daily.lower() for term in ('place_order','submit_order','tradingclient'))
