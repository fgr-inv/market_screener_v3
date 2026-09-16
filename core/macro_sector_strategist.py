"""Evidence-grounded macro and sector narrative agent.

The strategist never fetches data, calculates portfolio actions, or invents
causality.  It receives a frozen evidence packet built from persisted snapshots,
writes a professional Spanish narrative, and exposes every evidence reference
to a deterministic verifier.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re

import pandas as pd


REPORT_VERSION='1.0'
EXPECTED_SECTORS=('Technology','Communication Services','Consumer Discretionary','Industrials',
                  'Financials','Real Estate','Utilities','Consumer Staples','Health Care','Materials','Energy')
SECTOR_CONTEXT={
    'Technology':('tasas reales, inversión empresarial y liquidez','suba de rendimientos, concentración y valuaciones exigentes'),
    'Communication Services':('publicidad, consumo digital y liquidez','desaceleración publicitaria, regulación y concentración'),
    'Consumer Discretionary':('empleo, ingreso disponible, crédito y tasas','debilidad del consumo, morosidad y financiación cara'),
    'Industrials':('actividad, pedidos, infraestructura y capex','desaceleración de pedidos, costos y ejecución de backlog'),
    'Financials':('curva de tasas, crédito y calidad de activos','deterioro crediticio, depósitos y compresión de márgenes'),
    'Real Estate':('rendimientos largos, financiación y ocupación','refinanciación, vacancia y tasas reales elevadas'),
    'Utilities':('tasas, inflación y demanda defensiva','rendimientos largos, capex elevado y presión regulatoria'),
    'Consumer Staples':('ingreso real, inflación y defensividad','elasticidad de precios, costos y rotación hacia riesgo'),
    'Health Care':('demanda defensiva, innovación y financiación','regulación, patentes, ensayos y presión de precios'),
    'Materials':('ciclo global, dólar y materias primas','China débil, dólar firme y compresión de márgenes'),
    'Energy':('petróleo, oferta, inventarios y disciplina de capital','caída del crudo, demanda débil y riesgo político'),
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


def _primitive(value):
    if isinstance(value,(str,bool,int)) or value is None: return value
    number=_finite(value)
    return round(number,4) if number is not None else str(value)


def _age_hours(value,now=None):
    try:
        stamp=pd.Timestamp(value)
        if stamp.tzinfo is None: stamp=stamp.tz_localize('UTC')
        current=pd.Timestamp(now or datetime.now(timezone.utc))
        if current.tzinfo is None: current=current.tz_localize('UTC')
        return round(max(0,(current.tz_convert('UTC')-stamp.tz_convert('UTC')).total_seconds()/3600),2)
    except Exception: return None


def _prior_packet(previous):
    payload=(previous or {}).get('payload') or previous or {}
    return payload.get('evidence_packet') or {}


def _sector_aggregate(screener,sector):
    if screener is None or screener.empty or 'Sector' not in screener: return {}
    frame=screener[screener['Sector'].astype(str)==sector].copy()
    if frame.empty: return {}
    def median(column):
        return _finite(pd.to_numeric(frame.get(column),errors='coerce').median()) if column in frame else None
    trend=frame.get('Trend',pd.Series(index=frame.index,dtype=str)).astype(str).str.lower()
    action=frame.get('Action',pd.Series(index=frame.index,dtype=str)).astype(str).str.upper()
    leaders=[]
    ranking=next((column for column in ('RS_Composite_Percentile','RS_63d_%','Trend_Score') if column in frame),None)
    if ranking:
        selected=frame.sort_values(ranking,ascending=False,na_position='last').head(3)
        leaders=[str(value).upper() for value in selected.get('Ticker',pd.Series(dtype=str)).dropna()]
    return {'constituents':int(len(frame)),'uptrend_pct':round(float(trend.eq('uptrend').mean()*100),1),
            'above_sma200_pct':round(float((pd.to_numeric(frame.get('Dist_SMA200_%'),errors='coerce')>0).mean()*100),1) if 'Dist_SMA200_%' in frame else None,
            'median_rs63_pct':round(median('RS_63d_%'),2) if median('RS_63d_%') is not None else None,
            'median_rs1m_spy_pct':round(median('RS_1M_vs_SPY_%'),2) if median('RS_1M_vs_SPY_%') is not None else None,
            'buy_zone_count':int(action.isin({'BUY','BUY ZONE'}).sum()),
            'avoid_count':int(action.eq('AVOID').sum()),'leaders':leaders}


def build_market_evidence(macro,sectors,breadth,screener,meta,frequency='daily',previous=None,now=None,calendar=None):
    """Freeze the data used by the report and calculate only transparent aggregates."""
    current=_iso(now); meta=meta or {}; macro=macro or {}
    generated_at=meta.get('generated_at') or current
    prior=_prior_packet(previous); prior_macro=prior.get('macro') or {}
    macro_keys=('Institutional_Regime','Economic_Regime_Slow','Momentum','Growth','Slow_Growth',
                'Inflation_Pressure','Slow_Inflation_Pressure','Rates','Slow_Policy','Credit','Liquidity',
                'Risk_Appetite','Breadth','VIX','Core_CPI_YoY','Core_PCE_YoY','Unemployment',
                'Payroll_3m_Avg_Change','Fed_Funds','Fed_Funds_6m_Change','10Y_2Y','10Y_Breakeven',
                'NFCI','US10Y_20d_bps','Dollar_20d','HYG_IEF_20d','Oil_20d','Copper_Gold_20d',
                'Data_Quality_%','Missing')
    macro_packet={key:_primitive(macro.get(key)) for key in macro_keys if key in macro}
    macro_packet['changes']={}
    for key in ('Growth','Inflation_Pressure','Rates','Credit','Liquidity','Risk_Appetite','Breadth','VIX'):
        current_value=_finite(macro_packet.get(key)); prior_value=_finite(prior_macro.get(key))
        if current_value is not None and prior_value is not None:
            macro_packet['changes'][key]=round(current_value-prior_value,2)
    sector_rows=[]; sector_frame=sectors if isinstance(sectors,pd.DataFrame) else pd.DataFrame()
    prior_sectors={row.get('sector'):row for row in prior.get('sectors') or []}
    for sector in EXPECTED_SECTORS:
        match=sector_frame[sector_frame.get('Sector',pd.Series(index=sector_frame.index,dtype=str)).astype(str)==sector]
        snapshot={} if match.empty else match.iloc[0].to_dict()
        aggregate=_sector_aggregate(screener,sector); old=prior_sectors.get(sector) or {}
        row={'sector':sector,'etf':str(snapshot.get('ETF') or ''),'rank':None,
             'strength':_finite(snapshot.get('Strength')),'entry':_finite(snapshot.get('Entry')),
             'macro_fit':_finite(snapshot.get('Macro')),'status':str(snapshot.get('Status') or 'NOT_CHECKED'),**aggregate}
        for key in ('uptrend_pct','above_sma200_pct','median_rs63_pct','median_rs1m_spy_pct','strength','macro_fit'):
            value=_finite(row.get(key)); old_value=_finite(old.get(key))
            row[f'{key}_change']=None if value is None or old_value is None else round(value-old_value,2)
        sector_rows.append(row)
    ranked=sorted([row for row in sector_rows if row.get('strength') is not None],key=lambda row:row['strength'],reverse=True)
    for rank,row in enumerate(ranked,1): row['rank']=rank
    breadth_rows=[] if breadth is None or breadth.empty else breadth.to_dict('records')
    events=[] if calendar is None or getattr(calendar,'empty',True) else calendar.head(12).to_dict('records')
    return {'schema_version':REPORT_VERSION,'frequency':str(frequency),'generated_at':current,
            'snapshot_generated_at':str(generated_at),'snapshot_age_hours':_age_hours(generated_at,now),
            'macro':macro_packet,'sectors':sector_rows,'breadth':breadth_rows,'calendar':events,
            'coverage':{'sector_count':sum(bool(row.get('constituents')) for row in sector_rows),
                        'equity_rows':int(len(screener)) if screener is not None else 0,
                        'macro_quality_pct':_finite(macro.get('Data_Quality_%')),
                        'symbols_scored':int(_finite(meta.get('symbols_scored'),0) or 0)},
            'sources':['FRED','persisted market-price snapshots','sector ETF model','equity universe snapshot'],
            'no_execution':True}


def _direction(value,positive='mejoró',negative='se deterioró',flat='se mantuvo estable',threshold=1.5):
    number=_finite(value)
    if number is None: return 'no tiene comparación histórica suficiente'
    return positive if number>=threshold else negative if number<=-threshold else flat


def _band(value,high,low,high_text,low_text,mid_text):
    number=_finite(value)
    if number is None: return 'sin lectura suficiente'
    return high_text if number>=high else low_text if number<=low else mid_text


def _macro_analysis(packet):
    m=packet['macro']; frequency=packet['frequency']; horizon='la semana' if frequency=='weekly' else 'la última sesión disponible'
    regime=str(m.get('Economic_Regime_Slow') or m.get('Institutional_Regime') or 'no confirmado').replace('_',' ').lower()
    growth=_band(m.get('Slow_Growth',m.get('Growth')),55,45,'expansivo','débil','moderado')
    inflation=_band(m.get('Slow_Inflation_Pressure',m.get('Inflation_Pressure')),60,45,'todavía elevada','benigna','intermedia')
    paragraph1=(f'El entorno macro se clasifica como **{regime}**. El crecimiento luce {growth} y la presión inflacionaria '
                f'permanece {inflation}. Durante {horizon}, el balance entre actividad e inflación '
                f'{_direction((m.get("changes") or {}).get("Growth"),"mejoró","perdió impulso")}; esto importa porque define cuánto margen tiene la política monetaria para apoyar activos de riesgo.')
    fed=_finite(m.get('Fed_Funds')); curve=_finite(m.get('10Y_2Y')); yields=_finite(m.get('US10Y_20d_bps'))
    rate_parts=[]
    if fed is not None: rate_parts.append(f'Fed Funds se ubica en {fed:.2f}%')
    if curve is not None: rate_parts.append(f'la pendiente 10Y–2Y es {curve:+.2f} puntos porcentuales')
    if yields is not None: rate_parts.append(f'el rendimiento a 10 años cambió {yields:+.0f} puntos básicos en 20 ruedas')
    paragraph2=(('En tasas, '+', mientras '.join(rate_parts)+'. ') if rate_parts else 'La capa de tasas no tiene cobertura completa. ')
    paragraph2+=('Una curva más positiva puede favorecer intermediación financiera si no viene acompañada de estrés crediticio; '
                 'rendimientos largos ascendentes, en cambio, elevan la tasa de descuento para tecnología, real estate y utilities.')
    credit=_band(m.get('Credit'),60,40,'saludables','tensionadas','estables')
    liquidity=_band(m.get('Liquidity'),60,40,'favorables','restrictivas','neutrales')
    risk=_band(m.get('Risk_Appetite'),60,40,'constructivo','defensivo','selectivo')
    vix=_finite(m.get('VIX')); hyg=_finite(m.get('HYG_IEF_20d'))
    paragraph3=(f'Las condiciones de crédito aparecen {credit}, la liquidez es {liquidity} y el apetito por riesgo es {risk}. '
                + (f'El VIX está en {vix:.1f}. ' if vix is not None else '')
                + (f'La relación HYG/IEF cambió {hyg:+.1%} en 20 ruedas, una señal de cómo el crédito riesgoso se comporta frente a Treasuries. ' if hyg is not None else '')
                + 'La lectura conjunta es más importante que cualquier indicador aislado: crédito firme y volatilidad contenida validan mejor un avance que una suba concentrada en pocos nombres.')
    breadth=_finite(m.get('Breadth')); dollar=_finite(m.get('Dollar_20d')); oil=_finite(m.get('Oil_20d'))
    breadth_text=_band(breadth,60,40,'amplia','estrecha','mixta')
    paragraph4=(f'La participación interna es {breadth_text}. '
                + (f'El dólar cambió {dollar:+.1%} en 20 ruedas y ' if dollar is not None else '')
                + (f'el petróleo {oil:+.1%}. ' if oil is not None else '')
                + 'La combinación ayuda a distinguir un mercado sano de uno sostenido únicamente por capitalización: una amplitud débil obliga a ser más selectivo incluso cuando los índices principales resisten.')
    return [paragraph1,paragraph2,paragraph3,paragraph4]


def _sector_state(row):
    rank=row.get('rank'); up=_finite(row.get('uptrend_pct')); rs=_finite(row.get('median_rs63_pct'))
    if rank is not None and rank<=3 and (up is None or up>=45) and (rs is None or rs>=0): return 'LIDERAZGO'
    if rank is not None and rank>=9 and (up is None or up<45): return 'REZAGO'
    if _finite(row.get('strength_change')) is not None and row['strength_change']>=5: return 'MEJORANDO'
    if _finite(row.get('strength_change')) is not None and row['strength_change']<=-5: return 'DETERIORANDO'
    return 'TRANSICIÓN'


def _sector_analysis(row,frequency):
    sector=row['sector']; driver,risk=SECTOR_CONTEXT[sector]; state=_sector_state(row)
    up=_finite(row.get('uptrend_pct')); above=_finite(row.get('above_sma200_pct')); rs=_finite(row.get('median_rs63_pct'))
    breadth=('sin amplitud suficiente' if up is None else 'amplia' if up>=60 else 'débil' if up<35 else 'selectiva')
    relative=('sin ventaja relativa clara' if rs is None else 'con ventaja relativa frente al mercado' if rs>2 else
              'con rezago relativo frente al mercado' if rs<-2 else 'en línea con el mercado')
    change=_direction(row.get('strength_change'),'ganó fortaleza','perdió fortaleza')
    leaders=', '.join(row.get('leaders') or []) or 'sin líderes confirmados por cobertura'
    first=(f'**{state}.** {sector} presenta una participación {breadth} y se mantiene {relative}. '
           f'{("En la comparación semanal" if frequency=="weekly" else "Frente al informe anterior")}, {change}. '
           + (f'El {up:.1f}% de sus componentes está en tendencia alcista' if up is not None else 'No hay una medición completa de tendencias')
           + (f' y el {above:.1f}% cotiza sobre la SMA200. ' if above is not None else '. ')
           + f'Los nombres con mayor fortaleza interna son {leaders}; se mencionan como evidencia de liderazgo, no como recomendaciones.')
    macro=_band(row.get('macro_fit'),60,40,'favorable','adverso','neutral')
    second=(f'El marco macro es {macro} para el sector y sus variables dominantes son {driver}. '
            f'El principal riesgo a controlar es {risk}. La lectura mejoraría con expansión de la amplitud y continuidad de la fuerza relativa; '
            'se deterioraría si el liderazgo queda concentrado, aumenta el número de componentes bajo tendencia o cambia el régimen macro relevante.')
    refs=[f'sector:{sector}','macro:regime','macro:rates','macro:credit']
    return {'sector':sector,'etf':row.get('etf'),'state':state,'analysis':first+'\n\n'+second,
            'drivers':driver,'risks':risk,'leaders':row.get('leaders') or [],'evidence_refs':refs}


def _executive_summary(packet,sectors):
    m=packet['macro']; leaders=[row['sector'] for row in sectors if row['state']=='LIDERAZGO'][:3]
    laggards=[row['sector'] for row in sectors if row['state']=='REZAGO'][:3]
    regime=str(m.get('Economic_Regime_Slow') or m.get('Institutional_Regime') or 'no confirmado').replace('_',' ').lower()
    breadth=_band(m.get('Breadth'),60,40,'amplia','estrecha','mixta')
    return (f'El escenario central es **{regime}**, con participación de mercado {breadth}. '
            f'El liderazgo se concentra en {", ".join(leaders) if leaders else "sectores todavía no confirmados"}, '
            f'mientras {", ".join(laggards) if laggards else "no hay rezagos extremos confirmados"} muestran la lectura relativa más débil. '
            'La conclusión operativa es mantener selectividad: la fortaleza de un índice no sustituye la confirmación por amplitud, crédito y tendencia interna. '
            'Cash continúa siendo una posición válida cuando la evidencia no está alineada.')


def _scenarios(packet):
    m=packet['macro']; breadth=_finite(m.get('Breadth')); credit=_finite(m.get('Credit')); rates=_finite(m.get('Rates'))
    return {
        'base':'Crecimiento moderado, inflación todavía relevante y liderazgo selectivo. Priorizar confirmación y evitar perseguir extensiones.',
        'bull':('La participación se amplía, crédito y liquidez mejoran y los rendimientos dejan de presionar valuaciones. '
                'La confirmación exige breadth por encima de su zona neutral y más sectores ganando tendencia.'),
        'bear':('El crédito se deteriora, la volatilidad aumenta y la amplitud pierde soporte mientras las tasas permanecen restrictivas. '
                'La señal de alerta sería la combinación, no un movimiento aislado.'),
        'current_signals':{'breadth':breadth,'credit':credit,'rates':rates},
    }


def build_market_report(packet):
    sectors=[_sector_analysis(row,packet['frequency']) for row in packet.get('sectors') or [] if row.get('constituents')]
    report={'schema_version':REPORT_VERSION,'report_type':packet['frequency'],'generated_at':packet['generated_at'],
            'snapshot_generated_at':packet['snapshot_generated_at'],
            'title':('Informe semanal macro y sectorial' if packet['frequency']=='weekly' else 'Informe diario macro y sectorial'),
            'executive_summary':_executive_summary(packet,sectors),'macro_analysis':_macro_analysis(packet),
            'sector_analysis':sectors,'scenarios':_scenarios(packet),'calendar':packet.get('calendar') or [],
            'evidence_refs':['macro:regime','macro:rates','macro:credit','macro:breadth']+
                            [f"sector:{row['sector']}" for row in sectors],
            'evidence_packet':packet,'limitations':[],
            'agent':{'name':'Market Strategist','version':REPORT_VERSION,'mode':'DETERMINISTIC_GROUNDED_NARRATIVE'},
            'shadow_mode':True,'no_execution':True}
    return verify_market_report(report,packet)


def verify_market_report(report,packet):
    available={'macro:regime','macro:rates','macro:credit','macro:breadth'}
    available.update(f"sector:{row.get('sector')}" for row in packet.get('sectors') or [] if row.get('constituents'))
    referenced=set(report.get('evidence_refs') or [])
    for section in report.get('sector_analysis') or []: referenced.update(section.get('evidence_refs') or [])
    unsupported=sorted(referenced-available); issues=[]
    age=_finite(packet.get('snapshot_age_hours'))
    maximum_age=72 if packet.get('frequency')=='weekly' else 36
    if age is None: issues.append('SNAPSHOT_AGE_NOT_CHECKED')
    elif age>maximum_age: issues.append('STALE_SNAPSHOT')
    sector_count=len(report.get('sector_analysis') or [])
    if sector_count<8: issues.append('INSUFFICIENT_SECTOR_COVERAGE')
    if (_finite((packet.get('coverage') or {}).get('macro_quality_pct'),0) or 0)<60: issues.append('LOW_MACRO_COVERAGE')
    if unsupported: issues.append('UNSUPPORTED_EVIDENCE_REFERENCE')
    status='REJECTED' if unsupported or sector_count<8 else 'PARTIALLY_VERIFIED' if issues else 'VERIFIED'
    report['verification']={'status':status,'issues':issues,'unsupported_refs':unsupported,
                            'sector_count':sector_count,'snapshot_age_hours':age,
                            'verified_at':_iso(),'method':'Deterministic evidence-reference and freshness validation'}
    if issues: report['limitations']=[issue.replace('_',' ').title() for issue in issues]
    return report


def render_market_report_markdown(report):
    lines=[f"# {report.get('title','Informe macro y sectorial')}",
           f"_Generado: {report.get('generated_at','N/D')} · Verificación: {(report.get('verification') or {}).get('status','N/D')}_",
           '', '## Resumen ejecutivo','',report.get('executive_summary','')]
    if report.get('limitations'):
        lines.extend(['', '> Limitaciones: '+', '.join(report['limitations'])])
    lines.extend(['','## Situación macro',''])
    for paragraph in report.get('macro_analysis') or []: lines.extend([paragraph,''])
    lines.extend(['## Escenarios','',f"- **Base:** {(report.get('scenarios') or {}).get('base','N/D')}",
                  f"- **Alcista:** {(report.get('scenarios') or {}).get('bull','N/D')}",
                  f"- **Bajista:** {(report.get('scenarios') or {}).get('bear','N/D')}",'','## Análisis sectorial',''])
    for section in report.get('sector_analysis') or []:
        lines.extend([f"### {section.get('sector')} ({section.get('etf') or 'N/D'}) · {section.get('state')}",'',section.get('analysis',''),''])
    lines.extend(['---','*Investigación y simulación interna. No constituye una recomendación ni puede generar órdenes.*'])
    return '\n'.join(lines)
