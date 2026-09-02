"""Daily pre-market CIO brief. Shadow mode; no order execution."""
from __future__ import annotations
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from core.storage import load_positions,load_latest_snapshot
from core.desk_runner import run_desk_review
from core.desk_store import load_desk_output

def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    now=datetime.now(ZoneInfo('America/New_York'))
    if now.weekday()>=5: print('CIO brief skipped: weekend'); return 0
    if not (now.hour==7 and 20 <= now.minute <= 40):
        print('CIO brief skipped: not the 07:30 ET slot'); return 0
    pos=load_positions(user_id=uid); holdings=[] if pos.empty else pos['ticker'].dropna().astype(str).str.upper().tolist()
    snap=load_latest_snapshot('latest_screener'); candidates=[]
    if snap is not None and not snap.empty and 'Ticker' in snap.columns:
        score='Opportunity_Score' if 'Opportunity_Score' in snap.columns else ('Entry_Score' if 'Entry_Score' in snap.columns else None)
        x=snap.sort_values(score,ascending=False) if score else snap
        candidates=x['Ticker'].dropna().astype(str).str.upper().head(12).tolist()
    tickers=list(dict.fromkeys(holdings+candidates))[:25]
    if not tickers: print('CIO brief skipped: no tickers'); return 0
    run_key=f"daily-{now.date().isoformat()}"
    previous=load_desk_output(uid,'daily_cio_brief',run_key)
    if previous and previous.get('payload'):
        print('CIO brief skipped: already generated for this market date'); return 0
    out=run_desk_review(uid,tickers,False,'daily_cio_brief',run_key=run_key)
    print(out['brief']['headline']); return 0

if __name__=='__main__': raise SystemExit(main())
