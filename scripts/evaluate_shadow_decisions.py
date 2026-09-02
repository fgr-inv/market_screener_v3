"""Daily forward evaluation of Shadow Mode decisions. No broker/order path."""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
import os
from core.market_data import download_prices
from core.shadow_validation import (HORIZONS,load_shadow_decisions,load_shadow_outcomes,evaluate_decisions,
                                    persist_shadow_outcomes,shadow_validation_summary)
from core.desk_store import load_desk_output,save_desk_output
from core.agent_audit import append_agent_audit
from core.production_storage import storage_mode


def main():
    uid=str(os.getenv('DEV_USER_ID','local-user') or 'local-user')
    if os.getenv('GITHUB_ACTIONS','').lower()=='true' and storage_mode()!='POSTGRES':
        print('ERROR: DATABASE_URL is required for scheduled shadow validation.'); return 2
    now=datetime.now(ZoneInfo('America/New_York'))
    if now.weekday()>=5: print('Shadow validation skipped: weekend'); return 0
    run_key=f"shadow-validation-{now.date().isoformat()}"
    if load_desk_output(uid,'shadow_validation',run_key):
        print('Shadow validation skipped: already evaluated for this market date'); return 0
    decisions=load_shadow_decisions(uid); existing=load_shadow_outcomes(uid)
    completed={r.get('decision_key') for r in existing if r.get('status')=='MATURED' and int(r.get('horizon_days') or 0)==max(HORIZONS)}
    open_decisions=[r for r in decisions if r.get('decision_key') not in completed]
    tickers=list(dict.fromkeys([str(r.get('ticker','')).upper() for r in open_decisions if r.get('ticker')]+['SPY'])) if open_decisions else []
    histories=download_prices(tickers,period='6mo',max_age_minutes=15) if tickers else {}
    evaluated=evaluate_decisions(open_decisions,histories,evaluated_at=now)
    persistence=persist_shadow_outcomes(uid,evaluated)
    outcomes=load_shadow_outcomes(uid)
    summary=shadow_validation_summary(decisions,outcomes)
    payload={'shadow_mode':True,'summary':summary,'evaluated_decisions':len(open_decisions),
             'outcomes_written':len(evaluated),'persistence':persistence}
    append_agent_audit(uid,'shadow_forward_validation',{'run_key':run_key,**payload})
    if persistence.get('status')=='FAILED':
        print('ERROR: shadow outcomes were not fully persisted; run remains retriable.'); return 1
    save_desk_output(uid,'shadow_validation',payload,run_key=run_key)
    print(f"Shadow validation: decisions={summary['decisions']} matured={summary['matured_outcomes']} status={summary['status']}")
    return 0


if __name__=='__main__': raise SystemExit(main())
