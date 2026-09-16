"""Provider-neutral guardrail for an optional AI narrative rewrite.

The default report remains deterministic. A future model adapter may only
rewrite supplied sections and must preserve evidence references and numbers.
"""
from __future__ import annotations
import copy
import json
import re


def _numbers(value):
    return {token.lstrip('+').rstrip('0').rstrip('.') for token in
            re.findall(r'[-+]?\d+(?:\.\d+)?',str(value))}


def apply_grounded_narrator(report,packet,narrator=None):
    if narrator is None:
        report.setdefault('narrative_adapter',{'status':'DETERMINISTIC_FALLBACK','reason':'No external narrator configured'})
        return report
    try:
        candidate=narrator(copy.deepcopy(report),copy.deepcopy(packet))
        if not isinstance(candidate,dict): raise ValueError('Narrator output must be a mapping')
        permitted=set(report.get('evidence_refs') or [])
        refs=set(candidate.get('evidence_refs') or [])
        if not refs or not refs.issubset(permitted): raise ValueError('Unsupported evidence reference')
        sectors=candidate.get('sector_analysis') or []
        expected={row.get('sector') for row in report.get('sector_analysis') or []}
        if {row.get('sector') for row in sectors}!=expected: raise ValueError('Sector coverage changed')
        visible=' '.join([str(candidate.get('executive_summary') or ''),
                          ' '.join(candidate.get('macro_analysis') or []),
                          ' '.join(str(row.get('analysis') or '') for row in sectors)])
        allowed=_numbers(json.dumps(packet,ensure_ascii=False,default=str))
        invented=sorted(_numbers(visible)-allowed)
        if invented: raise ValueError('Unsupported numeric claims: '+','.join(invented[:8]))
        output=copy.deepcopy(report)
        for key in ('executive_summary','macro_analysis','sector_analysis','scenarios'):
            if key in candidate: output[key]=candidate[key]
        output['narrative_adapter']={'status':'AI_REWRITE_VERIFIED','unsupported_numbers':[]}
        return output
    except Exception as exc:
        report['narrative_adapter']={'status':'DETERMINISTIC_FALLBACK','reason':type(exc).__name__}
        return report
