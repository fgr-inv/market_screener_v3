from datetime import datetime, timedelta, timezone

from core.agent_playbooks import build_agent_playbooks, guidance_for_result
from core.agent_contracts import AgentResult
from core.alerts_engine import build_discord_rule_alert
from core.desk_notifications import build_discord_cio_embed


def _shadow_rows(sample=30):
    decisions=[]; outcomes=[]; start=datetime(2026,1,1,tzinfo=timezone.utc)
    for index in range(sample):
        key=f'd{index}'
        decisions.append({'decision_key':key,'decision_at':(start+timedelta(days=index)).isoformat(),
                          'ticker':f'T{index%10}','source_agent':'Technical Signal',
                          'signal_state':'SETUP','skill_version':'1.0','confidence':.7,
                          'verification_status':'VERIFIED'})
        outcomes.append({'decision_key':key,'horizon_days':5,'status':'MATURED',
                         'evaluated_at':(start+timedelta(days=index+10)).isoformat(),
                         'success':index<21,'signed_alpha_pct':1 if index<21 else -1})
    return decisions,outcomes


def test_playbook_entries_are_atomic_evidence_backed_and_non_executing():
    decisions,outcomes=_shadow_rows()
    playbooks=build_agent_playbooks(decisions,outcomes,previous={},generated_at='2026-09-17')
    entry=next(iter(playbooks['entries'].values()))
    assert entry['status']=='ACTIVE' and entry['confidence']=='HIGH'
    assert entry['hits']==21 and entry['misses']==9 and entry['sample']==30
    assert entry['when'].startswith('Technical Signal emite SETUP')
    assert entry['automatic_effect']=='NARRATIVE_CONTEXT_ONLY'
    assert playbooks['delta_operations'][0]['operation']=='ADD'
    assert playbooks['no_execution'] is True
    result=AgentResult('Technical Signal','1.0','technical_entry_review','1.0','NVDA','SETUP',.8,'ok')
    assert guidance_for_result(result,playbooks)['entry_id']==entry['entry_id']


def test_playbook_updates_with_deltas_instead_of_bulk_rewrite():
    decisions,outcomes=_shadow_rows(20)
    first=build_agent_playbooks(decisions,outcomes,previous={},generated_at='2026-08-01')
    more_decisions,more_outcomes=_shadow_rows(21)
    second=build_agent_playbooks(more_decisions,more_outcomes,previous=first,generated_at='2026-08-08')
    operations=[row['operation'] for row in second['delta_operations']]
    assert 'HIT' in operations or 'MISS' in operations
    assert second['policy']['bulk_rewrite_forbidden'] is True


def test_cio_alert_translates_internal_codes_into_professional_explanation():
    brief={
        'headline':'raw','material':False,'events_considered':[],
        'market_regime':{'state':'NEUTRAL','confidence':.9,
            'summary':'NEUTRAL - STAGFLATION RISK - DETERIORATING - leaders: Energy',
            'professional_context':{'macro_score':46,'economic_regime':'STAGFLATION_RISK',
                                    'momentum':'DETERIORATING','vix':17.7,
                                    'leaders':['Energy'],'laggards':['Utilities'],'snapshot_age_hours':2}},
        'principal_risk':{'state':'BALANCED','summary':'Portfolio risk: BALANCED',
            'professional_context':{'largest_positions':[('UBER',.09)],
                                    'largest_sectors':[('Technology',.36)],'cash_pct':4}},
        'top_opportunities':[{'Ticker':'LNC','Priority Score':92.5,'Technical':'SETUP',
                              'Fundamental':'IMPROVING','Entry Score':94,'Trend Score':88,'RR':2.59}],
        'decisions_needed':[],
    }
    embed=build_discord_cio_embed(brief,'daily')
    fields={row['name']:row['value'] for row in embed['fields']}
    assert 'STAGFLATION RISK' not in fields['🌎 Régimen de mercado']
    assert 'riesgo de estanflación' in fields['🌎 Régimen de mercado'].lower()
    assert 'impacto marginal' in fields['🛡️ Riesgo principal']
    assert 'encabeza la preselección' in fields['🎯 Oportunidades verificadas']
    assert 'no constituye una señal automática' in fields['🎯 Oportunidades verificadas']


def test_saved_alert_explains_technical_evidence_in_sentences():
    alert={'ticker':'NVDA','rule_type':'ENTRY_SCORE_ABOVE','threshold':75}
    context={'price':180,'trend':'Strong Uptrend','setup':'Pullback','entry_score':80,
             'trend_score':85,'relative_volume':1.4,'rr':2.4,'current_weight_pct':8}
    embed=build_discord_rule_alert(alert,'NVDA: Entry Score 80 >= 75','EDGE',
                                   datetime(2026,9,17,tzinfo=timezone.utc),context)
    fields={row['name']:row['value'] for row in embed['fields']}
    assert 'La tendencia se clasifica' in fields['📈 Lectura técnica']
    assert 'participación superior a la media' in fields['🔬 Confluencia y participación']
    assert 'cambia si se modifica' in fields['🛡️ Mapa de riesgo']
