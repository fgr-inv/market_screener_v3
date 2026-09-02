"""Persistent, user-scoped storage for automated Investment Desk outputs."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import json
import pandas as pd
from core.production_storage import cloud_available, ensure_production_schema, execute_sql, query_sql

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/'data'/'agent_outputs'; DIR.mkdir(parents=True,exist_ok=True)

def _safe(uid): return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in str(uid or 'local-user'))
def _now(): return datetime.now(timezone.utc).isoformat()

def save_desk_output(user_id, output_type, payload, run_key=None):
    uid=str(user_id or 'local-user'); typ=str(output_type); ts=_now(); key=str(run_key or ts)
    rec={'user_id':uid,'output_type':typ,'run_key':key,'created_at':ts,'payload':payload}
    p=DIR/f'{_safe(uid)}_{typ}.json'
    p.write_text(json.dumps(rec,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
    if cloud_available():
        ensure_production_schema()
        execute_sql('''INSERT INTO user_agent_outputs(user_id,output_type,run_key,created_at,payload_json)
            VALUES (:uid,:typ,:key,:ts,:payload)
            ON CONFLICT (user_id,output_type,run_key) DO UPDATE SET created_at=EXCLUDED.created_at,payload_json=EXCLUDED.payload_json''',
            {'uid':uid,'typ':typ,'key':key,'ts':ts,'payload':json.dumps(payload,ensure_ascii=False,default=str)})
    return rec

def load_latest_desk_output(user_id, output_type):
    uid=str(user_id or 'local-user'); typ=str(output_type)
    if cloud_available():
        df=query_sql('''SELECT created_at,payload_json FROM user_agent_outputs WHERE user_id=:uid AND output_type=:typ
                        ORDER BY created_at DESC LIMIT 1''',{'uid':uid,'typ':typ})
        if not df.empty:
            try: return {'created_at':str(df.iloc[0]['created_at']),'payload':json.loads(df.iloc[0]['payload_json'])}
            except Exception: pass
    p=DIR/f'{_safe(uid)}_{typ}.json'
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding='utf-8'))
    except Exception: return None
