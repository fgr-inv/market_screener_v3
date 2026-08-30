from pathlib import Path
from datetime import datetime, timezone
import json
import pandas as pd
from core.model_registry import model_label

ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / 'data' / 'audit'
AUDIT_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_FILE = AUDIT_DIR / 'score_audit.jsonl'


def append_score_audit(row, reason=None):
    rec = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'model': model_label(),
        'ticker': row.get('Ticker'),
        'price': row.get('Price'),
        'technical': row.get('Technical_Score'),
        'trend': row.get('Trend_Score'),
        'entry': row.get('Entry_Score'),
        'quality': row.get('Quality_Score'),
        'valuation': row.get('Valuation_Score'),
        'revisions': row.get('Revision_Score'),
        'rs_percentile': row.get('RS_Percentile'),
        'sector': row.get('Sector_Score'),
        'macro': row.get('Macro_Fit'),
        'confidence': row.get('Confidence_Score'),
        'opportunity': row.get('Opportunity_Score'),
        'action': row.get('Action'),
        'rr': row.get('RR'),
        'event_risk': row.get('Event_Risk'),
        'reason': reason or '',
    }
    with AUDIT_FILE.open('a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return rec


def load_audit(ticker=None, limit=500):
    if not AUDIT_FILE.exists():
        return pd.DataFrame()
    rows=[]
    with AUDIT_FILE.open('r', encoding='utf-8') as f:
        for line in f:
            try:
                r=json.loads(line)
                if ticker and r.get('ticker') != ticker:
                    continue
                rows.append(r)
            except Exception:
                pass
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).tail(limit)
