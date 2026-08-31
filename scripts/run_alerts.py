from pathlib import Path
import os
from datetime import datetime, timezone
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from core.storage import list_alerts,get_alert_state,set_alert_state
from core.market_data import download_prices
from core.alerts_engine import evaluate_rule,send_webhook,webhook_status
from core.alert_state import should_notify
from core.monitoring import log_event,log_exception
from core.production_storage import storage_mode
from core.notification_settings import get_user_webhook


def main():
    if os.getenv('GITHUB_ACTIONS','').lower()=='true' and storage_mode()!='POSTGRES':
        print('ERROR: DATABASE_URL is required for scheduled alerts in GitHub Actions.')
        return 2
    alerts=list_alerts(enabled_only=True)
    if alerts.empty:
        print('No enabled alerts'); return 0
    ticks=alerts['ticker'].dropna().astype(str).str.upper().unique().tolist()
    symbols=list(dict.fromkeys(ticks+['SPY']))
    print(f'Storage={storage_mode()} | Downloading {len(symbols)} symbols...')
    price_map=download_prices(symbols,period='2y'); spy=price_map.get('SPY')
    attempted=0; delivered_count=0; errors=0; evaluated=0
    now=datetime.now(timezone.utc)
    print('Notification routing=user-scoped webhook (server secret only falls back for DEV/OWNER user)')
    for _,alert in alerts.iterrows():
        aid=int(alert['id']); ticker=str(alert.get('ticker','UNKNOWN'))
        try:
            hit,message=evaluate_rule(alert,price_map,spy); evaluated+=1
            state=get_alert_state(aid)
            notify,reason=should_notify(
                hit,state,
                cooldown_minutes=int(alert.get('cooldown_minutes',240) or 240),
                repeat_while_true=bool(alert.get('repeat_while_true',False)),
                now=now,
            )
            delivered=False
            if notify:
                attempted+=1
                target=get_user_webhook(alert.get('user_id'))
                delivered=send_webhook(message,url=target) if target else False
                delivered_count+=int(delivered)
                print(f'HIT [{reason}] {message} | webhook={delivered}')
            else:
                print(f'NOOP [{reason}] {ticker} | hit={hit}')
            # If delivery fails, keep the edge unarmed so the next scheduled run retries.
            persisted_hit = bool(hit) if (not notify or delivered) else False
            set_alert_state(aid,persisted_hit,message,triggered=bool(notify and delivered),evaluated_at=now)
            log_event('alert_evaluated',alert_id=aid,ticker=ticker,hit=bool(hit),notify=bool(notify),reason=reason,webhook=delivered)
        except Exception as exc:
            errors+=1; print(f'ERROR {ticker}: {exc}'); log_exception('alert_evaluation_error',exc,alert_id=aid,ticker=ticker)
    print(f'Finished. evaluated={evaluated} attempted={attempted} delivered={delivered_count} errors={errors}')
    # A single provider/ticker error should not kill all alerts; systemic failures are visible in logs.
    return 0 if evaluated>0 or errors==0 else 1


if __name__=='__main__':
    raise SystemExit(main())
