from pathlib import Path
from datetime import datetime, timezone
import os

import duckdb
import pandas as pd

from core.production_storage import cloud_available, ensure_production_schema, execute_sql, query_sql

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data'/'market_screener.duckdb'


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _default_user_id():
    value=os.getenv('DEV_USER_ID','')
    if not value:
        try:
            import streamlit as st
            value=str(st.secrets.get('DEV_USER_ID',''))
        except Exception:
            pass
    return str(value or 'local-user').strip() or 'local-user'


def _global_webhook():
    value=os.getenv('ALERT_WEBHOOK_URL','')
    if value: return str(value).strip()
    try:
        import streamlit as st
        return str(st.secrets.get('ALERT_WEBHOOK_URL','') or '').strip()
    except Exception:
        return ''


def _con():
    c=duckdb.connect(str(DB))
    c.execute('''CREATE TABLE IF NOT EXISTS user_notification_settings (
        user_id VARCHAR PRIMARY KEY, webhook_url VARCHAR, enabled BOOLEAN DEFAULT TRUE, updated_at TIMESTAMP
    )''')
    return c


def set_user_webhook(user_id, webhook_url, enabled=True):
    uid=str(user_id or _default_user_id()); url=str(webhook_url or '').strip()
    if url and not (url.startswith('https://') or url.startswith('http://')):
        raise ValueError('El webhook debe comenzar con https:// o http://')
    now=_now(); c=_con()
    c.execute('''INSERT INTO user_notification_settings VALUES (?,?,?,?)
                 ON CONFLICT (user_id) DO UPDATE SET webhook_url=EXCLUDED.webhook_url,enabled=EXCLUDED.enabled,updated_at=EXCLUDED.updated_at''',
              [uid,url,bool(enabled),now]); c.close()
    if cloud_available():
        ensure_production_schema()
        ok,msg=execute_sql('''INSERT INTO user_notification_settings (user_id,webhook_url,enabled,updated_at)
            VALUES (:uid,:url,:enabled,:updated)
            ON CONFLICT (user_id) DO UPDATE SET webhook_url=EXCLUDED.webhook_url,enabled=EXCLUDED.enabled,updated_at=EXCLUDED.updated_at''',
            {'uid':uid,'url':url,'enabled':bool(enabled),'updated':now})
        if not ok: raise RuntimeError(f'No se pudo guardar el canal en Postgres: {msg}')
    return True


def clear_user_webhook(user_id):
    return set_user_webhook(user_id,'',enabled=False)


def user_webhook_record(user_id):
    uid=str(user_id or _default_user_id())
    if cloud_available():
        x=query_sql('SELECT user_id,webhook_url,enabled,updated_at FROM user_notification_settings WHERE user_id=:uid',{'uid':uid})
        if not x.empty: return x.iloc[0].to_dict()
    c=_con(); x=c.execute('SELECT user_id,webhook_url,enabled,updated_at FROM user_notification_settings WHERE user_id=?',[uid]).df(); c.close()
    return x.iloc[0].to_dict() if not x.empty else None


def get_user_webhook(user_id, allow_owner_global_fallback=True):
    uid=str(user_id or _default_user_id()); rec=user_webhook_record(uid)
    if rec and bool(rec.get('enabled',True)) and str(rec.get('webhook_url','') or '').strip():
        return str(rec['webhook_url']).strip()
    # The server-level secret is only a fallback for the configured server owner/dev user,
    # never for arbitrary SaaS users.
    if allow_owner_global_fallback and uid==_default_user_id():
        return _global_webhook()
    return ''


def masked_webhook(user_id):
    url=get_user_webhook(user_id)
    if not url: return 'NOT CONFIGURED'
    if len(url)<=18: return 'CONFIGURED'
    return url[:12]+'…'+url[-6:]
