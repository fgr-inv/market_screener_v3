"""Scheduled Investment Desk worker. Shadow mode only; no broker/execution code."""
from __future__ import annotations
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import pandas as pd
from core.storage import load_positions,load_latest_snapshot
from core.event_detector import detect_snapshot_events
from core.desk_runner import run_desk_review
from core.desk_store import save_desk_output

ROOT=Path(__file__).resolve().parents[1]

def _previous_snapshot():
    files=sorted((ROOT/'data'/'snapshots').glob('history_scores_*.parquet'))
    if len(files)<2: return pd.DataFrame()
    try: return pd.read_parquet(files[-2])
    except Exception: return pd.DataFrame()

def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    now=datetime.now(ZoneInfo('America/New_York'))
    if now.weekday()>=5:
        print('Desk skipped: weekend'); return 0
    minutes=now.hour*60+now.minute
    if not (9*60+30 <= minutes <= 16*60):
        print('Desk skipped: outside US cash session'); return 0
    pos=load_positions(user_id=uid); holdings=[] if pos.empty else pos['ticker'].dropna().astype(str).str.upper().tolist()
    latest=load_latest_snapshot('latest_screener')
    events=detect_snapshot_events(latest,_previous_snapshot(),holdings,max_events=12)
    save_desk_output(uid,'event_scan',{'shadow_mode':True,'events':events,'market_time':now.isoformat()})
    # Cheap scans run often; specialists wake only when an event exists.
    if not events:
        print('Desk scan: no material event'); return 0
    tickers=[e['ticker'] for e in events]
    out=run_desk_review(uid,tickers,force_fundamental=False,output_type='scheduled_review')
    print(out['brief']['headline']); print('reviewed:',','.join(tickers)); return 0

if __name__=='__main__': raise SystemExit(main())
