import os
import hashlib
from contextlib import contextmanager

import pandas as pd


_SCHEMA_READY_FOR=None


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
    global _SCHEMA_READY_FOR
    if not cloud_available():
        return False,'DATABASE_URL not configured'
    schema_key=hashlib.sha256(_database_url().encode('utf-8')).hexdigest()
    if _SCHEMA_READY_FOR==schema_key:
        return True,'OK'
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
            '''CREATE TABLE IF NOT EXISTS user_portfolio_positions (
                user_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                quantity DOUBLE PRECISION,
                avg_cost DOUBLE PRECISION,
                allocation_pct DOUBLE PRECISION,
                sector TEXT,
                note TEXT,
                updated_at TIMESTAMP,
                PRIMARY KEY (user_id, ticker)
            )''',
            "ALTER TABLE user_portfolio_positions ADD COLUMN IF NOT EXISTS allocation_pct DOUBLE PRECISION",
            '''CREATE INDEX IF NOT EXISTS idx_user_portfolio_positions_user
               ON user_portfolio_positions(user_id)''',
            '''CREATE TABLE IF NOT EXISTS user_investment_theses (
                user_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                thesis TEXT,
                catalysts TEXT,
                invalidation TEXT,
                target TEXT,
                review_date TEXT,
                status TEXT,
                note TEXT,
                PRIMARY KEY (user_id, ticker)
            )''',
            '''CREATE INDEX IF NOT EXISTS idx_user_investment_theses_user
               ON user_investment_theses(user_id)''',
            '''CREATE TABLE IF NOT EXISTS user_trade_journal (
                user_id TEXT NOT NULL,
                id BIGINT NOT NULL,
                opened_at TIMESTAMP,
                closed_at TIMESTAMP NULL,
                ticker TEXT,
                side TEXT,
                setup TEXT,
                thesis TEXT,
                catalyst TEXT,
                entry DOUBLE PRECISION,
                stop DOUBLE PRECISION,
                target DOUBLE PRECISION,
                exit DOUBLE PRECISION,
                quantity DOUBLE PRECISION,
                score_at_entry DOUBLE PRECISION,
                confidence_at_entry DOUBLE PRECISION,
                status TEXT,
                notes TEXT,
                pnl_dollars DOUBLE PRECISION,
                pnl_percent DOUBLE PRECISION,
                PRIMARY KEY (user_id, id)
            )''',
            '''CREATE INDEX IF NOT EXISTS idx_user_trade_journal_user_status
               ON user_trade_journal(user_id,status,opened_at)''',
            '''CREATE TABLE IF NOT EXISTS user_notification_settings (
                user_id TEXT PRIMARY KEY,
                webhook_url TEXT,
                enabled BOOLEAN DEFAULT TRUE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            '''CREATE TABLE IF NOT EXISTS user_agent_outputs (
                user_id TEXT NOT NULL,
                output_type TEXT NOT NULL,
                run_key TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (user_id, output_type, run_key)
            )''',
            '''CREATE INDEX IF NOT EXISTS idx_user_agent_outputs_latest
               ON user_agent_outputs(user_id,output_type,created_at DESC)''',
            '''CREATE TABLE IF NOT EXISTS user_agent_audit (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                ts TIMESTAMP NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )''',
            '''CREATE INDEX IF NOT EXISTS idx_user_agent_audit_latest
               ON user_agent_audit(user_id,ts DESC)''',
            '''CREATE TABLE IF NOT EXISTS user_agent_event_state (
                user_id TEXT NOT NULL,
                event_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                last_triggered_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id,event_key)
            )''',
            '''CREATE INDEX IF NOT EXISTS idx_user_agent_event_state_latest
               ON user_agent_event_state(user_id,last_triggered_at DESC)''',
            '''CREATE TABLE IF NOT EXISTS user_shadow_decisions (
                user_id TEXT NOT NULL,
                decision_key TEXT NOT NULL,
                run_key TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                decision_at TIMESTAMP NOT NULL,
                ticker TEXT NOT NULL,
                source_agent TEXT NOT NULL,
                signal_state TEXT NOT NULL,
                expected_direction TEXT NOT NULL,
                confidence DOUBLE PRECISION,
                verification_status TEXT,
                baseline_price DOUBLE PRECISION,
                benchmark_price DOUBLE PRECISION,
                baseline_status TEXT NOT NULL,
                skill_version TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (user_id,decision_key)
            )''',
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS run_key TEXT",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS decision_at TIMESTAMP",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS ticker TEXT",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS source_agent TEXT",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS signal_state TEXT",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS expected_direction TEXT",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS verification_status TEXT",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS baseline_price DOUBLE PRECISION",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS benchmark_price DOUBLE PRECISION",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS baseline_status TEXT",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS skill_version TEXT",
            "ALTER TABLE user_shadow_decisions ADD COLUMN IF NOT EXISTS payload_json TEXT",
            '''CREATE INDEX IF NOT EXISTS idx_user_shadow_decisions_time
               ON user_shadow_decisions(user_id,decision_at DESC)''',
            '''CREATE TABLE IF NOT EXISTS user_shadow_outcomes (
                user_id TEXT NOT NULL,
                decision_key TEXT NOT NULL,
                horizon_days INTEGER NOT NULL,
                evaluated_at TIMESTAMP NOT NULL,
                status TEXT NOT NULL,
                outcome_at TIMESTAMP NULL,
                asset_return_pct DOUBLE PRECISION,
                benchmark_return_pct DOUBLE PRECISION,
                alpha_pct DOUBLE PRECISION,
                signed_return_pct DOUBLE PRECISION,
                signed_alpha_pct DOUBLE PRECISION,
                mfe_pct DOUBLE PRECISION,
                mae_pct DOUBLE PRECISION,
                success BOOLEAN,
                source TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (user_id,decision_key,horizon_days)
            )''',
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS evaluated_at TIMESTAMP",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS status TEXT",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS outcome_at TIMESTAMP NULL",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS asset_return_pct DOUBLE PRECISION",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS benchmark_return_pct DOUBLE PRECISION",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS alpha_pct DOUBLE PRECISION",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS signed_return_pct DOUBLE PRECISION",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS signed_alpha_pct DOUBLE PRECISION",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS mfe_pct DOUBLE PRECISION",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS mae_pct DOUBLE PRECISION",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS success BOOLEAN",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS source TEXT",
            "ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS payload_json TEXT",
            '''CREATE INDEX IF NOT EXISTS idx_user_shadow_outcomes_status
               ON user_shadow_outcomes(user_id,status,horizon_days)''',
            '''CREATE TABLE IF NOT EXISTS user_skill_calibration_reviews (
                user_id TEXT NOT NULL,
                review_key TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                status TEXT NOT NULL,
                manual_review_required BOOLEAN DEFAULT FALSE,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (user_id,review_key)
            )''',
            '''CREATE INDEX IF NOT EXISTS idx_user_skill_calibration_latest
               ON user_skill_calibration_reviews(user_id,created_at DESC)''',
            '''CREATE TABLE IF NOT EXISTS user_skill_governance (
                user_id TEXT NOT NULL,
                proposal_key TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                agent TEXT NOT NULL,
                signal_state TEXT NOT NULL,
                skill_version TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                resolution TEXT NOT NULL,
                note TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (user_id,proposal_key)
            )''',
            '''CREATE INDEX IF NOT EXISTS idx_user_skill_governance_latest
               ON user_skill_governance(user_id,updated_at DESC)''',
        ]
        with cloud_connection() as con:
            for stmt in statements:
                con.execute(text(stmt))
        _SCHEMA_READY_FOR=schema_key
        return True,'OK'
    except Exception as e:
        return False,str(e)[:240]


def execute_sql(sql, params=None):
    if not cloud_available():
        return False,'DATABASE_URL not configured'
    try:
        from sqlalchemy import text
        schema_ok,schema_message=ensure_production_schema()
        if not schema_ok:
            return False,f'schema migration failed: {schema_message}'[:240]
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
