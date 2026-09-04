from datetime import datetime
import os
from zoneinfo import ZoneInfo

from core.refresh import build_market_snapshot
from core.market_calendar import is_us_equity_session

if __name__=='__main__':
    now=datetime.now(ZoneInfo('America/New_York'))
    manual=os.getenv('GITHUB_EVENT_NAME','').lower()=='workflow_dispatch'
    recovery=os.getenv('AUTOMATION_RECOVERY','').lower()=='true'
    if not is_us_equity_session(now) and not (manual or recovery):
        print('Snapshot skipped: US equity market holiday/weekend')
        raise SystemExit(0)
    # One broad cheap scan per weekday. Specialist/fundamental work is deferred
    # to the bounded opportunity-hunt shortlist.
    snap=build_market_snapshot(scan_limit=2200)
    print('snapshot rows:',len(snap['results']))
    print('generated:',snap['meta']['generated_at'])
