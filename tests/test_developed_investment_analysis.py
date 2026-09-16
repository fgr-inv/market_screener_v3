from datetime import datetime, timezone

from core.alerts_engine import build_discord_rule_alert
from core.desk_notifications import build_discord_cio_embed


NOW = datetime(2026, 9, 16, 13, 0, tzinfo=timezone.utc)


def test_saved_alert_explains_evidence_in_narrative_form():
    embed = build_discord_rule_alert(
        {'ticker': 'NVDA', 'rule_type': 'ENTRY_SCORE_ABOVE', 'threshold': 75},
        'NVDA: Entry Score 82 >= 75', now=NOW,
        context={'price': 182.4, 'trend': 'Strong Uptrend', 'setup': 'Uptrend Pullback',
                 'entry_score': 82, 'trend_score': 74, 'technical_score': 79,
                 'relative_volume': 1.3, 'relative_strength_63d_pct': 7.8,
                 'entry_zone': '$176-$184', 'invalidation': '<$169', 'rr': 2.35,
                 'portfolio_weight_pct': 4.2, 'market_regime': 'RISK_ON'},
    )
    fields = {field['name']: field['value'] for field in embed['fields']}
    narrative = fields['📚 Análisis desarrollado']
    assert 'no constituye por sí solo una tesis' in narrative
    assert 'La combinación importa más que el score aislado' in narrative
    assert '📈 Lectura técnica' in fields and '🛡️ Mapa de riesgo' in fields
    assert '🧭 Escenario y validación' in fields and '📌 Conclusión para el desk' in fields
    assert 'cash continúa siendo una posición válida' in fields['📌 Conclusión para el desk']


def test_material_cio_alert_opens_with_interpretation_not_only_score():
    story = {'title': 'La compañía actualizó su guía', 'category': 'GUIDANCE',
             'direction': 'NEGATIVE', 'severity': 5, 'publisher': 'Investor Relations',
             'url': 'https://example.test/release', 'primary_source': True}
    brief = {
        'events_considered': [{'ticker': 'ACME', 'severity': 5,
                               'metrics': {'story': story}}],
        'market_regime': {'state': 'RISK_OFF', 'confidence': .8,
                          'summary': 'Crédito y amplitud defensivos.'},
        'principal_risk': {'state': 'ELEVATED', 'summary': 'Concentración elevada.'},
        'decisions_needed': [{'subject': 'ACME', 'agent': 'News & Catalyst',
                              'state': 'MATERIAL_NEGATIVE', 'confidence': .83,
                              'verification_status': 'VERIFIED',
                              'key_evidence': [{'claim': 'Guía', 'value': 'recortada'}]}],
    }
    embed = build_discord_cio_embed(brief, 'material')
    reading = next(field['value'] for field in embed['fields']
                   if field['name'] == '🔎 Lectura profesional')
    assert 'requiere una revisión desarrollada' in embed['description']
    assert 'no reemplaza la confirmación de la fuente' in reading
    assert 'La evidencia que sostiene esta lectura' in reading
    assert len(reading.split()) >= 35
