from pathlib import Path
import os
from datetime import datetime, timezone
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from core.storage import (list_alerts,get_alert_state,set_alert_state,load_latest_snapshot,
                          load_json_snapshot,load_positions)
from core.market_data import download_prices
from core.alerts_engine import evaluate_rule_with_context,send_webhook,webhook_status,build_discord_rule_alert
from core.alert_state import should_notify
from core.monitoring import log_event,log_exception
from core.production_storage import storage_mode
from core.notification_settings import get_user_webhook
from core.automation_health import record_automation_heartbeat
from core.portfolio_positions import resolve_position_allocations


def _heartbeat_users(alerts):
    users=[str(os.getenv('DEV_USER_ID','local-user') or 'local-user')]
    if alerts is not None and not alerts.empty and 'user_id' in alerts:
        users.extend(alerts['user_id'].dropna().astype(str).tolist())
    return list(dict.fromkeys(user for user in users if user))


def _record_alert_heartbeats(alerts,status,details):
    for user_id in _heartbeat_users(alerts):
        record_automation_heartbeat(user_id,'saved_alerts',status=status,details=details)


def _finite(value):
    try:
        value=float(value)
        return value if pd.notna(value) else None
    except Exception:
        return None


def _user_id(value):
    return 'local-user' if value is None or (not isinstance(value,str) and pd.isna(value)) else str(value or 'local-user')


def _snapshot_lookup(snapshot):
    if snapshot is None or snapshot.empty or 'Ticker' not in snapshot: return {}
    return {str(row.get('Ticker','')).upper():row.to_dict() for _,row in snapshot.iterrows() if row.get('Ticker')}


def _snapshot_context(ticker,lookup):
    row=lookup.get(str(ticker).upper()) or {}; out={}
    for source,target in (
        ('Sector','sector'),('Universe Source','universe_source'),('Liquidity Tier','liquidity_tier'),
        ('Opportunity_Score','opportunity_score'),('Confidence_Score','confidence_score'),('Action','snapshot_action'),
    ):
        value=row.get(source)
        if value is not None and not (not isinstance(value,str) and pd.isna(value)): out[target]=value
    return out


def _macro_context(macro):
    macro=macro or {}; out={}
    regime=macro.get('Institutional_Regime') or macro.get('Risk_Regime')
    if regime: out['market_regime']=str(regime)
    for source,target in (('Macro_Score','macro_score'),('VIX','vix'),('Breadth','breadth')):
        value=_finite(macro.get(source))
        if value is not None: out[target]=value
    return out


def _portfolio_context(user_id,price_map,cache,position_frames=None):
    uid=_user_id(user_id)
    if uid not in cache:
        positions=(position_frames or {}).get(uid)
        if positions is None: positions=load_positions(user_id=uid)
        detail,meta=resolve_position_allocations(positions,price_map)
        weights={}; sectors={}; position_sectors={}
        if detail is not None and not detail.empty:
            for _,row in detail.iterrows():
                ticker=str(row.get('Ticker','')).upper(); weight=_finite(row.get('Weight %'))
                sector=str(row.get('Sector') or 'Unknown')
                if ticker and weight is not None:
                    weights[ticker]=weight; position_sectors[ticker]=sector
                    sectors[sector]=sectors.get(sector,0.0)+weight
        cache[uid]={'weights':weights,'sectors':sectors,'position_sectors':position_sectors,
                    'cash_pct':_finite(meta.get('cash_pct'))}
    return cache[uid]


def _position_context(ticker,portfolio):
    ticker=str(ticker).upper(); out={}
    if ticker in portfolio.get('weights',{}): out['current_weight_pct']=portfolio['weights'][ticker]
    sector=portfolio.get('position_sectors',{}).get(ticker)
    if sector:
        out['sector']=sector
        out['sector_weight_pct']=portfolio.get('sectors',{}).get(sector)
    if portfolio.get('cash_pct') is not None: out['cash_pct']=portfolio['cash_pct']
    return out


def main():
    if os.getenv('GITHUB_ACTIONS','').lower()=='true' and storage_mode()!='POSTGRES':
        print('ERROR: DATABASE_URL is required for scheduled alerts in GitHub Actions.')
        return 2
    alerts=list_alerts(enabled_only=True)
    if alerts.empty:
        _record_alert_heartbeats(alerts,'IDLE',{'enabled_alerts':0,'evaluated':0})
        print('No enabled alerts'); return 0
    ticks=alerts['ticker'].dropna().astype(str).str.upper().unique().tolist()
    position_frames={}; portfolio_ticks=[]
    for uid in _heartbeat_users(alerts):
        try:
            positions=load_positions(user_id=uid); position_frames[uid]=positions
            if positions is not None and not positions.empty:
                portfolio_ticks.extend(positions['ticker'].dropna().astype(str).str.upper().tolist())
        except Exception as exc:
            log_exception('alert_portfolio_context_error',exc,user_id=uid)
            position_frames[uid]=pd.DataFrame()
    symbols=list(dict.fromkeys(ticks+portfolio_ticks+['SPY']))
    print(f'Storage={storage_mode()} | Downloading {len(symbols)} symbols...')
    price_map=download_prices(symbols,period='2y'); spy=price_map.get('SPY')
    snapshot_rows=_snapshot_lookup(load_latest_snapshot('latest_screener'))
    macro_context=_macro_context(load_json_snapshot('latest_macro'))
    portfolio_cache={}
    attempted=0; delivered_count=0; errors=0; evaluated=0
    now=datetime.now(timezone.utc)
    print('Notification routing=user-scoped webhook (server secret only falls back for DEV/OWNER user)')
    for _,alert in alerts.iterrows():
        aid=int(alert['id']); ticker=str(alert.get('ticker','UNKNOWN'))
        try:
            hit,message,context=evaluate_rule_with_context(alert,price_map,spy); evaluated+=1
            try:
                context.update(_snapshot_context(ticker,snapshot_rows))
                context.update(macro_context)
                portfolio=_portfolio_context(alert.get('user_id'),price_map,portfolio_cache,position_frames)
                context.update(_position_context(ticker,portfolio))
            except Exception as context_exc:
                # Enrichment must never suppress the underlying saved alert.
                log_exception('alert_professional_context_error',context_exc,alert_id=aid,ticker=ticker)
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
                delivered=(send_webhook(message,url=target,
                                        discord_embed=build_discord_rule_alert(alert,message,reason,now,context=context))
                           if target else False)
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
    _record_alert_heartbeats(alerts,'CURRENT' if errors==0 else 'PARTIAL',{
        'enabled_alerts':len(alerts),'evaluated':evaluated,'attempted':attempted,
        'delivered':delivered_count,'errors':errors,
    })
    # A single provider/ticker error should not kill all alerts; systemic failures are visible in logs.
    return 0 if evaluated>0 or errors==0 else 1


if __name__=='__main__':
    raise SystemExit(main())
