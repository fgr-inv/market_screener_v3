from pathlib import Path
from datetime import datetime, timezone
import json
import logging
import time
import traceback

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
LOG_DIR=ROOT/'data'/'logs'; LOG_DIR.mkdir(parents=True,exist_ok=True)
METRICS_FILE=LOG_DIR/'metrics.jsonl'
ERROR_FILE=LOG_DIR/'errors.jsonl'

logger=logging.getLogger('market_screener')
if not logger.handlers:
    logger.setLevel(logging.INFO)
    fh=logging.FileHandler(LOG_DIR/'app.log',encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(fh)


def _append(path, rec):
    try:
        with path.open('a',encoding='utf-8') as f:
            f.write(json.dumps(rec,ensure_ascii=False,default=str)+'\n')
    except Exception:
        pass


def log_event(event, **fields):
    rec={'ts':datetime.now(timezone.utc).isoformat(),'event':event,**fields}
    _append(METRICS_FILE,rec)
    logger.info('%s %s',event,fields)
    return rec


def log_exception(event, exc, **fields):
    rec={
        'ts':datetime.now(timezone.utc).isoformat(),'event':event,'error_type':type(exc).__name__,
        'error':str(exc)[:500],'traceback':traceback.format_exc(limit=8),**fields,
    }
    _append(ERROR_FILE,rec); logger.error('%s %s',event,rec)
    return rec


def recent_errors(limit=100):
    if not ERROR_FILE.exists(): return pd.DataFrame()
    rows=[]
    try:
        with ERROR_FILE.open('r',encoding='utf-8') as f:
            for line in f:
                try: rows.append(json.loads(line))
                except Exception: pass
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame(rows).tail(limit).iloc[::-1] if rows else pd.DataFrame()


class timer:
    def __init__(self,event,**fields): self.event=event; self.fields=fields
    def __enter__(self): self.start=time.time(); return self
    def __exit__(self,exc_type,exc,tb):
        log_event(self.event,latency_ms=round((time.time()-self.start)*1000),success=exc is None,**self.fields)
        if exc is not None: log_exception(self.event,exc,**self.fields)
        return False
