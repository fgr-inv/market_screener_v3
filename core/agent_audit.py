"""Append-only, user-scoped audit trail for investment-desk handoffs."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import json
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
AUDIT_DIR=ROOT/'data'/'agent_audit'; AUDIT_DIR.mkdir(parents=True,exist_ok=True)

def _safe_user(user_id):
    return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in str(user_id or 'local-user'))

def audit_path(user_id): return AUDIT_DIR/f'{_safe_user(user_id)}.jsonl'

def append_agent_audit(user_id, event_type, payload):
    rec={'ts':datetime.now(timezone.utc).isoformat(),'user_id':str(user_id),'event_type':str(event_type),'payload':payload}
    with audit_path(user_id).open('a',encoding='utf-8') as f: f.write(json.dumps(rec,ensure_ascii=False,default=str)+'\n')
    return rec

def load_agent_audit(user_id, limit=200):
    p=audit_path(user_id)
    if not p.exists(): return pd.DataFrame()
    rows=[]
    for line in p.read_text(encoding='utf-8').splitlines():
        try: rows.append(json.loads(line))
        except Exception: pass
    return pd.DataFrame(rows[-int(limit):]) if rows else pd.DataFrame()
