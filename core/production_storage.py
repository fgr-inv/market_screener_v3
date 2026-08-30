import os
from contextlib import contextmanager

import pandas as pd


def _database_url():
    value=os.getenv('DATABASE_URL','')
    if value:
        return value
    try:
        import streamlit as st
        return str(st.secrets.get('DATABASE_URL',''))
    except Exception:
        return ''


def cloud_available():
    return bool(_database_url())


def storage_mode():
    return 'POSTGRES' if cloud_available() else 'LOCAL_DUCKDB'


def _engine():
    url=_database_url()
    if not url:
        return None
    from sqlalchemy import create_engine
    return create_engine(url,pool_pre_ping=True,pool_recycle=300,future=True)


@contextmanager
def cloud_connection():
    engine=_engine()
    if engine is None:
        yield None
        return
    with engine.begin() as con:
        yield con


def ensure_production_schema():
    if not cloud_available():
        return False,'DATABASE_URL not configured'
    try:
        from sqlalchemy import text
        statements=[
            '''CREATE TABLE IF NOT EXISTS saved_alerts (
                id BIGINT PRIMARY KEY,
                user_id TEXT DEFAULT 'local-user',
                created_at TIMESTAMP,
                ticker TEXT,
                rule_type TEXT,
                threshold DOUBLE PRECISION,
                enabled BOOLEAN,
                note TEXT,
                cooldown_minutes INTEGER DEFAULT 240,
                repeat_while_true BOOLEAN DEFAULT FALSE
            )''',
            "ALTER TABLE saved_alerts ADD COLUMN IF NOT EXISTS user_id TEXT DEFAULT 'local-user'",
            "UPDATE saved_alerts SET user_id='local-user' WHERE user_id IS NULL OR user_id=''",
            '''CREATE INDEX IF NOT EXISTS idx_saved_alerts_user_enabled
               ON saved_alerts(user_id, enabled)''',
            '''CREATE TABLE IF NOT EXISTS alert_state (
                alert_id BIGINT PRIMARY KEY,
                last_hit BOOLEAN DEFAULT FALSE,
                last_triggered_at TIMESTAMP NULL,
                last_evaluated_at TIMESTAMP NULL,
                last_message TEXT,
                trigger_count BIGINT DEFAULT 0
            )''',
            '''CREATE TABLE IF NOT EXISTS portfolio_positions (
                ticker TEXT PRIMARY KEY,
                quantity DOUBLE PRECISION,
                avg_cost DOUBLE PRECISION,
                sector TEXT,
                note TEXT,
                updated_at TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS investment_theses (
                ticker TEXT PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                thesis TEXT,
                catalysts TEXT,
                invalidation TEXT,
                target TEXT,
                review_date TEXT,
                status TEXT,
                note TEXT
            )''',
            '''CREATE TABLE IF NOT EXISTS app_users (
                user_id TEXT PRIMARY KEY,
                email TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS subscriptions (
                user_id TEXT PRIMARY KEY,
                plan TEXT NOT NULL DEFAULT 'FREE',
                status TEXT NOT NULL DEFAULT 'active',
                billing_cycle TEXT,
                provider_customer_id TEXT,
                provider_subscription_id TEXT,
                current_period_end TIMESTAMP NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS usage_events (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                feature TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                units INTEGER DEFAULT 1,
                cache_hit BOOLEAN DEFAULT FALSE,
                provider_cost DOUBLE PRECISION DEFAULT 0,
                billable BOOLEAN DEFAULT TRUE,
                metadata_json TEXT
            )''',
            '''CREATE INDEX IF NOT EXISTS idx_usage_events_user_feature_time
               ON usage_events(user_id,feature,created_at)''',
        ]
        with cloud_connection() as con:
            for stmt in statements:
                con.execute(text(stmt))
        return True,'OK'
    except Exception as e:
        return False,str(e)[:240]


def execute_sql(sql, params=None):
    if not cloud_available():
        return False,'DATABASE_URL not configured'
    try:
        from sqlalchemy import text
        ensure_production_schema()
        with cloud_connection() as con:
            con.execute(text(sql),params or {})
        return True,'OK'
    except Exception as e:
        return False,str(e)[:240]


def query_sql(sql, params=None):
    if not cloud_available():
        return pd.DataFrame()
    try:
        from sqlalchemy import text
        ensure_production_schema()
        engine=_engine()
        with engine.connect() as con:
            return pd.read_sql(text(sql),con,params=params or {})
    except Exception:
        return pd.DataFrame()


def write_dataframe(df, table, if_exists='append'):
    if not cloud_available():
        return False,'DATABASE_URL not configured'
    try:
        engine=_engine()
        df.to_sql(table,engine,if_exists=if_exists,index=False,method='multi')
        return True,'OK'
    except Exception as e:
        return False,str(e)[:240]


def read_table(table, limit=1000):
    if not str(table).replace('_','').isalnum():
        return pd.DataFrame()
    return query_sql(f'SELECT * FROM {table} LIMIT {int(limit)}')
