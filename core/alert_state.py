from datetime import datetime, timezone
import pandas as pd


def should_notify(hit, state=None, cooldown_minutes=240, repeat_while_true=False, now=None):
    """Pure transition logic used by the hourly alert runner.

    Alerts fire on FALSE->TRUE. When repeat_while_true=True they may repeat only
    after cooldown_minutes. A FALSE evaluation resets the edge state.
    """
    now=pd.Timestamp(now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        now=now.tz_localize('UTC')
    state=state or {}
    raw_previous=state.get('last_hit',False)
    previous=False if pd.isna(raw_previous) else bool(raw_previous)
    if not hit:
        return False,'RESET'
    if not previous:
        return True,'EDGE'
    if not repeat_while_true:
        return False,'ALREADY_ACTIVE'
    last=state.get('last_triggered_at')
    if last is None or pd.isna(last):
        return True,'NO_PREVIOUS_TRIGGER'
    last=pd.Timestamp(last)
    if last.tzinfo is None:
        last=last.tz_localize('UTC')
    elapsed=(now-last).total_seconds()/60
    if elapsed>=max(float(cooldown_minutes or 0),0):
        return True,'COOLDOWN_ELAPSED'
    return False,'COOLDOWN'
