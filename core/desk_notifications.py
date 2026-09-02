"""Material-only, user-scoped notifications for automated CIO outputs."""
from __future__ import annotations
from core.alerts_engine import send_webhook
from core.notification_settings import get_user_webhook
from core.desk_store import load_desk_output,save_desk_output


def format_cio_alert(brief):
    reasons=list(brief.get('material_reasons') or [])[:3]
    lines=['INVESTMENT DESK · SHADOW MODE',brief.get('headline','Material CIO review')]
    lines.extend(f'- {reason}' for reason in reasons)
    lines.append('Research only — no order was placed.')
    return '\n'.join(lines)


def notify_material_brief(user_id,brief,run_key,send_fn=send_webhook):
    """Deliver once per run key; failed or unconfigured delivery remains retriable."""
    uid=str(user_id or 'local-user'); key=str(run_key)
    if not brief.get('material'):
        return {'status':'NOT_MATERIAL','delivered':False,'attempted':False}
    prior=load_desk_output(uid,'cio_alert_delivery',key)
    if prior and bool((prior.get('payload') or {}).get('delivered')):
        return {'status':'DUPLICATE','delivered':True,'attempted':False}
    target=get_user_webhook(uid)
    if not target:
        payload={'status':'NOT_CONFIGURED','delivered':False,'attempted':False,'shadow_mode':True}
        save_desk_output(uid,'cio_alert_delivery',payload,run_key=key)
        return payload
    delivered=bool(send_fn(format_cio_alert(brief),url=target))
    payload={'status':'DELIVERED' if delivered else 'FAILED','delivered':delivered,'attempted':True,'shadow_mode':True}
    save_desk_output(uid,'cio_alert_delivery',payload,run_key=key)
    return payload
