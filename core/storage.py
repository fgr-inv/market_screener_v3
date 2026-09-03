from pathlib import Path
from datetime import datetime, timezone
import json

import pandas as pd
import duckdb

from core.monitoring import log_event
from core.production_storage import cloud_available, ensure_production_schema, execute_sql, query_sql

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
DB_PATH = DATA_DIR / 'market_screener.duckdb'
SNAPSHOT_DIR = DATA_DIR / 'snapshots'
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

ALERT_COLUMNS=['id','user_id','created_at','ticker','rule_type','threshold','enabled','note','cooldown_minutes','repeat_while_true']
ALERT_STATE_COLUMNS=['alert_id','last_hit','last_triggered_at','last_evaluated_at','last_message','trigger_count']
POSITION_COLUMNS=['ticker','quantity','avg_cost','allocation_pct','sector','note','updated_at']
THESIS_COLUMNS=['ticker','created_at','updated_at','thesis','catalysts','invalidation','target','review_date','status','note']


def _conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute('''
        CREATE TABLE IF NOT EXISTS score_history (
            ts TIMESTAMP, ticker VARCHAR, asset_type VARCHAR, sector VARCHAR,
            technical DOUBLE, trend DOUBLE, entry DOUBLE, risk DOUBLE,
            rs_percentile DOUBLE, sector_score DOUBLE, macro_fit DOUBLE, quality DOUBLE,
            preliminary DOUBLE, opportunity DOUBLE, action VARCHAR, rr DOUBLE,
            price DOUBLE, confidence DOUBLE
        )
    ''')
    con.execute('''
        CREATE TABLE IF NOT EXISTS saved_alerts (
            id BIGINT, user_id VARCHAR DEFAULT 'local-user', created_at TIMESTAMP, ticker VARCHAR, rule_type VARCHAR,
            threshold DOUBLE, enabled BOOLEAN, note VARCHAR,
            cooldown_minutes INTEGER DEFAULT 240,
            repeat_while_true BOOLEAN DEFAULT FALSE
        )
    ''')
    # Migrate old DBs safely.
    for stmt in [
        "ALTER TABLE saved_alerts ADD COLUMN IF NOT EXISTS user_id VARCHAR DEFAULT 'local-user'",
        'ALTER TABLE saved_alerts ADD COLUMN IF NOT EXISTS cooldown_minutes INTEGER DEFAULT 240',
        'ALTER TABLE saved_alerts ADD COLUMN IF NOT EXISTS repeat_while_true BOOLEAN DEFAULT FALSE',
    ]:
        try: con.execute(stmt)
        except Exception: pass
    con.execute('''
        CREATE TABLE IF NOT EXISTS alert_state (
            alert_id BIGINT PRIMARY KEY,
            last_hit BOOLEAN DEFAULT FALSE,
            last_triggered_at TIMESTAMP,
            last_evaluated_at TIMESTAMP,
            last_message VARCHAR,
            trigger_count BIGINT DEFAULT 0
        )
    ''')
    con.execute('''
        CREATE TABLE IF NOT EXISTS portfolio_positions (
            ticker VARCHAR PRIMARY KEY, quantity DOUBLE, avg_cost DOUBLE,
            sector VARCHAR, note VARCHAR, updated_at TIMESTAMP
        )
    ''')
    con.execute('''
        CREATE TABLE IF NOT EXISTS investment_theses (
            ticker VARCHAR PRIMARY KEY,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            thesis VARCHAR,
            catalysts VARCHAR,
            invalidation VARCHAR,
            target VARCHAR,
            review_date VARCHAR,
            status VARCHAR,
            note VARCHAR
        )
    ''')
    return con


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _default_alert_user_id():
    import os
    value=os.getenv('DEV_USER_ID','')
    if not value:
        try:
            import streamlit as st
            value=str(st.secrets.get('DEV_USER_ID',''))
        except Exception:
            pass
    return str(value or 'local-user').strip() or 'local-user'


def save_score_snapshot(df: pd.DataFrame, asset_type='Unknown'):
    if df is None or df.empty: return 0
    now=_utcnow_naive(); rows=[]
    for _,r in df.iterrows():
        rows.append({
            'ts':now,'ticker':r.get('Ticker'),'asset_type':r.get('Asset_Type',asset_type),
            'sector':r.get('Sector'),'technical':r.get('Technical_Score'),'trend':r.get('Trend_Score'),
            'entry':r.get('Entry_Score'),'risk':r.get('Risk_Score'),'rs_percentile':r.get('RS_Percentile'),
            'sector_score':r.get('Sector_Score'),'macro_fit':r.get('Macro_Fit'),'quality':r.get('Quality_Score'),
            'preliminary':r.get('Preliminary_Score'),'opportunity':r.get('Opportunity_Score'),'action':r.get('Action'),
            'rr':r.get('RR'),'price':r.get('Price'),'confidence':r.get('Confidence_Score')
        })
    out=pd.DataFrame(rows)
    con=_conn(); con.register('tmp_scores',out); con.execute('INSERT INTO score_history SELECT * FROM tmp_scores'); con.close()
    return len(out)


def load_score_history(ticker=None, days=180):
    frames=[]; con=_conn()
    try:
        q="SELECT * FROM score_history WHERE ts >= current_timestamp - INTERVAL ? DAY"; params=[days]
        if ticker: q+=' AND ticker = ?'; params.append(ticker)
        q+=' ORDER BY ts'; frames.append(con.execute(q,params).df())
    except Exception as e:
        log_event('storage_read_error',table='score_history',error=str(e)[:180])
    con.close()
    cutoff=pd.Timestamp.utcnow().tz_localize(None)-pd.Timedelta(days=days)
    for path in sorted(SNAPSHOT_DIR.glob('history_scores_*.parquet')):
        try:
            ts=pd.Timestamp(path.stem.replace('history_scores_',''))
            if ts<cutoff: continue
            x=pd.read_parquet(path)
            if ticker and 'Ticker' in x.columns: x=x[x['Ticker']==ticker]
            if x.empty: continue
            frames.append(pd.DataFrame({
                'ts':ts,'ticker':x.get('Ticker'),'asset_type':x.get('Asset_Type','Acciones'),'sector':x.get('Sector'),
                'technical':x.get('Technical_Score'),'trend':x.get('Trend_Score'),'entry':x.get('Entry_Score'),
                'risk':x.get('Risk_Score'),'rs_percentile':x.get('RS_Percentile'),'sector_score':x.get('Sector_Score'),
                'macro_fit':x.get('Macro_Fit'),'quality':x.get('Quality_Score'),'preliminary':x.get('Preliminary_Score'),
                'opportunity':x.get('Opportunity_Score'),'action':x.get('Action'),'rr':x.get('RR'),'price':x.get('Price'),
                'confidence':x.get('Confidence_Score'),
            }))
        except Exception as e:
            log_event('snapshot_read_error',file=path.name,error=str(e)[:180])
    if not frames: return pd.DataFrame()
    return pd.concat(frames,ignore_index=True).drop_duplicates(subset=['ts','ticker'],keep='last').sort_values('ts')


def save_latest_snapshot(df: pd.DataFrame, name='latest_screener'):
    if df is None or df.empty: return None
    path=SNAPSHOT_DIR/f'{name}.parquet'; df.to_parquet(path,index=False); return path


def load_latest_snapshot(name='latest_screener'):
    path=SNAPSHOT_DIR/f'{name}.parquet'
    if not path.exists(): return pd.DataFrame()
    try: return pd.read_parquet(path)
    except Exception as e:
        log_event('snapshot_read_error',file=path.name,error=str(e)[:180]); return pd.DataFrame()


def _normalize_alerts(df):
    if df is None or df.empty: return pd.DataFrame(columns=ALERT_COLUMNS)
    x=df.copy()
    defaults={'user_id':_default_alert_user_id(),'cooldown_minutes':240,'repeat_while_true':False,'note':'','enabled':True}
    for c,v in defaults.items():
        if c not in x.columns: x[c]=v
    for c in ALERT_COLUMNS:
        if c not in x.columns: x[c]=None
    return x[ALERT_COLUMNS]


def _mirror_alerts_csv():
    try:
        con=_conn(); df=_normalize_alerts(con.execute('SELECT * FROM saved_alerts ORDER BY id').df()); con.close()
        path=DATA_DIR/'alerts.csv'; df.to_csv(path,index=False); return path
    except Exception as e:
        log_event('alerts_mirror_error',error=str(e)[:180]); return None


def import_alerts_csv_if_needed():
    path=DATA_DIR/'alerts.csv'
    if not path.exists(): return
    con=_conn()
    try:
        count=con.execute('SELECT COUNT(*) FROM saved_alerts').fetchone()[0]
        if count==0:
            df=_normalize_alerts(pd.read_csv(path))
            if not df.empty:
                df['created_at']=pd.to_datetime(df['created_at'],errors='coerce')
                con.register('tmp_alerts',df); con.execute('''INSERT INTO saved_alerts (id,user_id,created_at,ticker,rule_type,threshold,enabled,note,cooldown_minutes,repeat_while_true) SELECT id,user_id,created_at,ticker,rule_type,threshold,enabled,note,cooldown_minutes,repeat_while_true FROM tmp_alerts''')
    except Exception as e:
        log_event('alerts_import_error',error=str(e)[:180])
    con.close()


def _cloud_alerts(enabled_only=False, user_id=None):
    if not cloud_available(): return pd.DataFrame(columns=ALERT_COLUMNS)
    ok,_=ensure_production_schema()
    if not ok: return pd.DataFrame(columns=ALERT_COLUMNS)
    q='SELECT * FROM saved_alerts'; clauses=[]; params={}
    if enabled_only: clauses.append('enabled = TRUE')
    if user_id is not None:
        clauses.append('user_id = :user_id'); params['user_id']=str(user_id)
    if clauses: q+=' WHERE '+' AND '.join(clauses)
    q+=' ORDER BY created_at DESC'
    return _normalize_alerts(query_sql(q,params))


def _new_alert_id():
    import secrets
    return secrets.randbelow(9_000_000_000_000_000_000-1)+1


def add_alert(ticker, rule_type, threshold, note='', cooldown_minutes=240, repeat_while_true=False, enabled=True, user_id=None):
    ticker=str(ticker or '').upper().strip()
    if not ticker: raise ValueError('Ticker vacío')
    allowed={'EMA62_DISTANCE','EMA79_DISTANCE','ENTRY_SCORE_ABOVE','PRICE_BELOW','PRICE_ABOVE','RR_ABOVE'}
    if rule_type not in allowed: raise ValueError(f'Regla no soportada: {rule_type}')
    th=float(threshold)
    if th < 0: raise ValueError('Threshold inválido')
    uid=str(user_id or _default_alert_user_id())
    now=_utcnow_naive(); next_id=_new_alert_id()
    vals=[next_id,uid,now,ticker,rule_type,th,bool(enabled),str(note or '')[:240],int(cooldown_minutes),bool(repeat_while_true)]
    con=_conn(); con.execute('''INSERT INTO saved_alerts (id,user_id,created_at,ticker,rule_type,threshold,enabled,note,cooldown_minutes,repeat_while_true) VALUES (?,?,?,?,?,?,?,?,?,?)''',vals); con.close(); _mirror_alerts_csv()
    if cloud_available():
        ok,msg=execute_sql('''INSERT INTO saved_alerts (id,user_id,created_at,ticker,rule_type,threshold,enabled,note,cooldown_minutes,repeat_while_true)
            VALUES (:id,:user_id,:created_at,:ticker,:rule_type,:threshold,:enabled,:note,:cooldown,:repeat)''',
            {'id':next_id,'user_id':uid,'created_at':now,'ticker':ticker,'rule_type':rule_type,'threshold':th,'enabled':bool(enabled),
             'note':str(note or '')[:240],'cooldown':int(cooldown_minutes),'repeat':bool(repeat_while_true)})
        if not ok:
            con=_conn(); con.execute('DELETE FROM saved_alerts WHERE id=?',[next_id]); con.close(); _mirror_alerts_csv()
            raise RuntimeError(f'Postgres no pudo guardar la alerta: {msg}')
    return next_id


def list_alerts(enabled_only=False, user_id=None):
    if cloud_available(): return _cloud_alerts(enabled_only,user_id=user_id)
    import_alerts_csv_if_needed(); con=_conn(); q='SELECT * FROM saved_alerts'; params=[]; clauses=[]
    if enabled_only: clauses.append('enabled = TRUE')
    if user_id is not None: clauses.append('user_id = ?'); params.append(str(user_id))
    if clauses: q+=' WHERE '+' AND '.join(clauses)
    q+=' ORDER BY created_at DESC'; df=_normalize_alerts(con.execute(q,params).df()); con.close(); return df


def delete_alert(alert_id, user_id=None):
    aid=int(alert_id); uid=str(user_id) if user_id is not None else None
    if uid is not None:
        owned = _cloud_alerts(False,user_id=uid) if cloud_available() else list_alerts(False,user_id=uid)
        if owned.empty or aid not in set(pd.to_numeric(owned['id'],errors='coerce').dropna().astype(int)):
            raise PermissionError('La alerta no pertenece al usuario actual.')
    if cloud_available():
        params={'id':aid}; sql='DELETE FROM saved_alerts WHERE id=:id'
        if uid is not None: sql+=' AND user_id=:user_id'; params['user_id']=uid
        ok,msg=execute_sql(sql,params)
        if not ok: raise RuntimeError(msg)
        execute_sql('DELETE FROM alert_state WHERE alert_id=:id',{'id':aid})
    con=_conn()
    if uid is None: con.execute('DELETE FROM saved_alerts WHERE id=?',[aid])
    else: con.execute('DELETE FROM saved_alerts WHERE id=? AND user_id=?',[aid,uid])
    con.execute('DELETE FROM alert_state WHERE alert_id=?',[aid]); con.close(); _mirror_alerts_csv(); _mirror_alert_state_csv()


def set_alert_enabled(alert_id, enabled, user_id=None):
    aid=int(alert_id); uid=str(user_id) if user_id is not None else None
    if cloud_available():
        params={'enabled':bool(enabled),'id':aid}; sql='UPDATE saved_alerts SET enabled=:enabled WHERE id=:id'
        if uid is not None: sql+=' AND user_id=:user_id'; params['user_id']=uid
        ok,msg=execute_sql(sql,params)
        if not ok: raise RuntimeError(msg)
    con=_conn()
    if uid is None: con.execute('UPDATE saved_alerts SET enabled=? WHERE id=?',[bool(enabled),aid])
    else: con.execute('UPDATE saved_alerts SET enabled=? WHERE id=? AND user_id=?',[bool(enabled),aid,uid])
    con.close(); _mirror_alerts_csv()


def alert_storage_health():
    if not cloud_available():
        try:
            con=_conn(); con.execute('SELECT 1 FROM saved_alerts LIMIT 1'); con.close()
            return {'ok':True,'mode':'LOCAL_DUCKDB','message':'OK'}
        except Exception as exc:
            return {'ok':False,'mode':'LOCAL_DUCKDB','message':str(exc)[:180]}
    ok,msg=ensure_production_schema()
    if not ok: return {'ok':False,'mode':'POSTGRES','message':msg}
    try:
        from sqlalchemy import text
        from core.production_storage import cloud_connection
        with cloud_connection() as con:
            con.execute(text('SELECT id FROM saved_alerts LIMIT 1'))
        return {'ok':True,'mode':'POSTGRES','message':'OK'}
    except Exception as exc:
        return {'ok':False,'mode':'POSTGRES','message':str(exc)[:180]}


def _normalize_alert_state(df):
    if df is None or df.empty: return pd.DataFrame(columns=ALERT_STATE_COLUMNS)
    x=df.copy()
    defaults={'last_hit':False,'last_triggered_at':pd.NaT,'last_evaluated_at':pd.NaT,'last_message':'','trigger_count':0}
    for c,v in defaults.items():
        if c not in x.columns: x[c]=v
    return x[ALERT_STATE_COLUMNS]


def _mirror_alert_state_csv():
    try:
        con=_conn(); df=_normalize_alert_state(con.execute('SELECT * FROM alert_state ORDER BY alert_id').df()); con.close()
        path=DATA_DIR/'alert_state.csv'; df.to_csv(path,index=False); return path
    except Exception as e:
        log_event('alert_state_mirror_error',error=str(e)[:180]); return None


def import_alert_state_csv_if_needed():
    path=DATA_DIR/'alert_state.csv'
    if not path.exists(): return
    con=_conn()
    try:
        count=con.execute('SELECT COUNT(*) FROM alert_state').fetchone()[0]
        if count==0:
            df=_normalize_alert_state(pd.read_csv(path))
            for c in ['last_triggered_at','last_evaluated_at']: df[c]=pd.to_datetime(df[c],errors='coerce')
            if not df.empty:
                con.register('tmp_state',df); con.execute('INSERT INTO alert_state SELECT * FROM tmp_state')
    except Exception as e:
        log_event('alert_state_import_error',error=str(e)[:180])
    con.close()


def get_alert_state(alert_id):
    aid=int(alert_id)
    if cloud_available():
        x=query_sql('SELECT * FROM alert_state WHERE alert_id=:id',{'id':aid})
        if not x.empty: return x.iloc[0].to_dict()
    import_alert_state_csv_if_needed(); con=_conn(); x=con.execute('SELECT * FROM alert_state WHERE alert_id=?',[aid]).df(); con.close()
    return x.iloc[0].to_dict() if not x.empty else {'alert_id':aid,'last_hit':False,'trigger_count':0}


def set_alert_state(alert_id, hit, message='', triggered=False, evaluated_at=None):
    aid=int(alert_id); now=pd.Timestamp(evaluated_at or _utcnow_naive()).to_pydatetime(); prev=get_alert_state(aid)
    trig_at=now if triggered else prev.get('last_triggered_at')
    raw_count=prev.get('trigger_count',0)
    count=(0 if pd.isna(raw_count) else int(raw_count or 0))+(1 if triggered else 0)
    con=_conn(); con.execute('''INSERT OR REPLACE INTO alert_state VALUES (?,?,?,?,?,?)''',[aid,bool(hit),trig_at,now,message,count]); con.close(); _mirror_alert_state_csv()
    if cloud_available():
        execute_sql('''INSERT INTO alert_state (alert_id,last_hit,last_triggered_at,last_evaluated_at,last_message,trigger_count)
            VALUES (:id,:hit,:trig,:eval,:msg,:count)
            ON CONFLICT (alert_id) DO UPDATE SET last_hit=EXCLUDED.last_hit,last_triggered_at=EXCLUDED.last_triggered_at,
            last_evaluated_at=EXCLUDED.last_evaluated_at,last_message=EXCLUDED.last_message,trigger_count=EXCLUDED.trigger_count''',
            {'id':aid,'hit':bool(hit),'trig':trig_at,'eval':now,'msg':message,'count':count})
    return get_alert_state(aid)


def list_alert_states():
    if cloud_available():
        x=query_sql('SELECT * FROM alert_state ORDER BY alert_id')
        if not x.empty: return _normalize_alert_state(x)
    import_alert_state_csv_if_needed(); con=_conn(); x=_normalize_alert_state(con.execute('SELECT * FROM alert_state ORDER BY alert_id').df()); con.close(); return x


def _ensure_user_portfolio_tables(con):
    # User-scoped tables avoid cross-account portfolio leakage and preserve legacy tables.
    con.execute('''
        CREATE TABLE IF NOT EXISTS user_portfolio_positions (
            user_id VARCHAR, ticker VARCHAR, quantity DOUBLE, avg_cost DOUBLE, allocation_pct DOUBLE,
            sector VARCHAR, note VARCHAR, updated_at TIMESTAMP,
            PRIMARY KEY (user_id, ticker)
        )
    ''')
    try: con.execute('ALTER TABLE user_portfolio_positions ADD COLUMN IF NOT EXISTS allocation_pct DOUBLE')
    except Exception: pass
    con.execute('''
        CREATE TABLE IF NOT EXISTS user_investment_theses (
            user_id VARCHAR, ticker VARCHAR, created_at TIMESTAMP, updated_at TIMESTAMP,
            thesis VARCHAR, catalysts VARCHAR, invalidation VARCHAR, target VARCHAR,
            review_date VARCHAR, status VARCHAR, note VARCHAR,
            PRIMARY KEY (user_id, ticker)
        )
    ''')
    uid=_default_alert_user_id()
    try:
        if con.execute('SELECT COUNT(*) FROM user_portfolio_positions').fetchone()[0]==0:
            legacy=con.execute('SELECT * FROM portfolio_positions').df()
            if not legacy.empty:
                legacy.insert(0,'user_id',uid)
                legacy['allocation_pct']=None
                cols=['user_id','ticker','quantity','avg_cost','allocation_pct','sector','note','updated_at']
                con.register('legacy_positions',legacy[cols])
                con.execute('''INSERT OR IGNORE INTO user_portfolio_positions
                    (user_id,ticker,quantity,avg_cost,allocation_pct,sector,note,updated_at)
                    SELECT user_id,ticker,quantity,avg_cost,allocation_pct,sector,note,updated_at FROM legacy_positions''')
    except Exception as exc:
        log_event('positions_legacy_migration_error',error=str(exc)[:180])
    try:
        if con.execute('SELECT COUNT(*) FROM user_investment_theses').fetchone()[0]==0:
            legacy=con.execute('SELECT * FROM investment_theses').df()
            if not legacy.empty:
                legacy.insert(0,'user_id',uid)
                con.register('legacy_theses',legacy[['user_id']+THESIS_COLUMNS])
                con.execute('INSERT OR IGNORE INTO user_investment_theses SELECT * FROM legacy_theses')
    except Exception as exc:
        log_event('theses_legacy_migration_error',error=str(exc)[:180])


def _migrate_cloud_legacy_portfolio_if_needed(user_id):
    # Preserve pre-V11.23 single-user cloud data by assigning it to the configured user once.
    if not cloud_available(): return
    uid=str(user_id or _default_alert_user_id())
    try:
        counts=query_sql('SELECT (SELECT COUNT(*) FROM user_portfolio_positions) AS p, (SELECT COUNT(*) FROM user_investment_theses) AS t')
        if counts.empty: return
        if int(counts.iloc[0].get('p',0) or 0)==0:
            old=query_sql('SELECT ticker,quantity,avg_cost,sector,note,updated_at FROM portfolio_positions')
            for _,r in old.iterrows():
                execute_sql('''INSERT INTO user_portfolio_positions (user_id,ticker,quantity,avg_cost,allocation_pct,sector,note,updated_at)
                    VALUES (:uid,:ticker,:q,:cost,NULL,:sector,:note,:updated) ON CONFLICT (user_id,ticker) DO NOTHING''',
                    {'uid':uid,'ticker':r['ticker'],'q':float(r['quantity']),'cost':float(r['avg_cost']),
                     'sector':str(r.get('sector','Unknown')),'note':str(r.get('note','') or ''),'updated':r.get('updated_at')})
        if int(counts.iloc[0].get('t',0) or 0)==0:
            old=query_sql('SELECT ticker,created_at,updated_at,thesis,catalysts,invalidation,target,review_date,status,note FROM investment_theses')
            for _,r in old.iterrows():
                execute_sql('''INSERT INTO user_investment_theses (user_id,ticker,created_at,updated_at,thesis,catalysts,invalidation,target,review_date,status,note)
                    VALUES (:uid,:ticker,:created,:updated,:thesis,:catalysts,:invalidation,:target,:review,:status,:note)
                    ON CONFLICT (user_id,ticker) DO NOTHING''',
                    {'uid':uid,'ticker':r['ticker'],'created':r.get('created_at'),'updated':r.get('updated_at'),
                     'thesis':str(r.get('thesis','') or ''),'catalysts':str(r.get('catalysts','') or ''),'invalidation':str(r.get('invalidation','') or ''),
                     'target':str(r.get('target','') or ''),'review':str(r.get('review_date','') or ''),'status':str(r.get('status','ACTIVE') or 'ACTIVE'),'note':str(r.get('note','') or '')})
    except Exception as exc:
        log_event('cloud_portfolio_legacy_migration_error',error=str(exc)[:180])


def _mirror_positions_csv():
    try:
        con=_conn(); _ensure_user_portfolio_tables(con)
        df=con.execute('SELECT * FROM user_portfolio_positions ORDER BY user_id,ticker').df(); con.close()
        path=DATA_DIR/'portfolio_positions.csv'; df.to_csv(path,index=False); return path
    except Exception as e:
        log_event('positions_mirror_error',error=str(e)[:180]); return None


def import_positions_csv_if_needed():
    path=DATA_DIR/'portfolio_positions.csv'
    if not path.exists(): return
    con=_conn(); _ensure_user_portfolio_tables(con)
    try:
        if con.execute('SELECT COUNT(*) FROM user_portfolio_positions').fetchone()[0]==0:
            df=pd.read_csv(path)
            if not df.empty:
                if 'user_id' not in df.columns: df.insert(0,'user_id',_default_alert_user_id())
                for c,v in {'sector':'Unknown','note':'','updated_at':_utcnow_naive()}.items():
                    if c not in df.columns: df[c]=v
                if 'allocation_pct' not in df.columns: df['allocation_pct']=None
                df['updated_at']=pd.to_datetime(df['updated_at'],errors='coerce')
                cols=['user_id','ticker','quantity','avg_cost','allocation_pct','sector','note','updated_at']
                con.register('tmp_positions',df[cols]); con.execute('''INSERT OR IGNORE INTO user_portfolio_positions
                    (user_id,ticker,quantity,avg_cost,allocation_pct,sector,note,updated_at)
                    SELECT user_id,ticker,quantity,avg_cost,allocation_pct,sector,note,updated_at FROM tmp_positions''')
    except Exception as e: log_event('positions_import_error',error=str(e)[:180])
    con.close()


def upsert_position(ticker, quantity=0, avg_cost=0, sector='Unknown', note='', user_id=None, allocation_pct=None):
    ticker=str(ticker or '').upper().strip()
    if not ticker: raise ValueError('Ticker vacío')
    q=float(quantity); cost=float(avg_cost)
    allocation=None if allocation_pct is None else float(allocation_pct)
    if q < 0 or cost < 0: raise ValueError('Cantidad y costo deben ser >= 0')
    if allocation is not None and not 0 < allocation <= 100: raise ValueError('El porcentaje debe ser mayor a 0 y menor o igual a 100')
    if allocation is None and q <= 0: raise ValueError('La cantidad debe ser mayor a 0 cuando no se carga por porcentaje')
    uid=str(user_id or _default_alert_user_id()); now=_utcnow_naive()
    con=_conn(); _ensure_user_portfolio_tables(con)
    con.execute('''INSERT INTO user_portfolio_positions (user_id,ticker,quantity,avg_cost,allocation_pct,sector,note,updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT (user_id,ticker) DO UPDATE SET quantity=EXCLUDED.quantity,avg_cost=EXCLUDED.avg_cost,
        allocation_pct=EXCLUDED.allocation_pct,sector=EXCLUDED.sector,note=EXCLUDED.note,updated_at=EXCLUDED.updated_at''',
        [uid,ticker,q,cost,allocation,str(sector or 'Unknown'),str(note or '')[:500],now])
    con.close(); _mirror_positions_csv()
    if cloud_available():
        ensure_production_schema()
        ok,msg=execute_sql('''INSERT INTO user_portfolio_positions (user_id,ticker,quantity,avg_cost,allocation_pct,sector,note,updated_at)
            VALUES (:uid,:ticker,:q,:cost,:allocation,:sector,:note,:updated)
            ON CONFLICT (user_id,ticker) DO UPDATE SET quantity=EXCLUDED.quantity,avg_cost=EXCLUDED.avg_cost,
            allocation_pct=EXCLUDED.allocation_pct,sector=EXCLUDED.sector,note=EXCLUDED.note,updated_at=EXCLUDED.updated_at''',
            {'uid':uid,'ticker':ticker,'q':q,'cost':cost,'allocation':allocation,'sector':str(sector or 'Unknown'),'note':str(note or '')[:500],'updated':now})
        if not ok: raise RuntimeError(f'No se pudo guardar la posición en Postgres: {msg}')
    return True


def load_positions(user_id=None):
    uid=str(user_id or _default_alert_user_id())
    if cloud_available():
        ensure_production_schema()
        _migrate_cloud_legacy_portfolio_if_needed(uid)
        x=query_sql('SELECT ticker,quantity,avg_cost,allocation_pct,sector,note,updated_at FROM user_portfolio_positions WHERE user_id=:uid ORDER BY ticker',{'uid':uid})
        if not x.empty: return x
    import_positions_csv_if_needed(); con=_conn(); _ensure_user_portfolio_tables(con)
    df=con.execute('SELECT ticker,quantity,avg_cost,allocation_pct,sector,note,updated_at FROM user_portfolio_positions WHERE user_id=? ORDER BY ticker',[uid]).df(); con.close(); return df


def delete_position(ticker, user_id=None):
    ticker=str(ticker or '').upper().strip(); uid=str(user_id or _default_alert_user_id())
    if cloud_available():
        ok,msg=execute_sql('DELETE FROM user_portfolio_positions WHERE user_id=:uid AND ticker=:ticker',{'uid':uid,'ticker':ticker})
        if not ok: raise RuntimeError(msg)
    con=_conn(); _ensure_user_portfolio_tables(con)
    con.execute('DELETE FROM user_portfolio_positions WHERE user_id=? AND ticker=?',[uid,ticker]); con.close(); _mirror_positions_csv()


def _mirror_theses_csv():
    try:
        con=_conn(); _ensure_user_portfolio_tables(con)
        df=con.execute('SELECT * FROM user_investment_theses ORDER BY user_id,ticker').df(); con.close()
        path=DATA_DIR/'investment_theses.csv'; df.to_csv(path,index=False); return path
    except Exception as e: log_event('theses_mirror_error',error=str(e)[:180]); return None


def import_theses_csv_if_needed():
    path=DATA_DIR/'investment_theses.csv'
    if not path.exists(): return
    con=_conn(); _ensure_user_portfolio_tables(con)
    try:
        if con.execute('SELECT COUNT(*) FROM user_investment_theses').fetchone()[0]==0:
            df=pd.read_csv(path)
            if not df.empty:
                if 'user_id' not in df.columns: df.insert(0,'user_id',_default_alert_user_id())
                for c in THESIS_COLUMNS:
                    if c not in df.columns: df[c]=''
                for c in ['created_at','updated_at']: df[c]=pd.to_datetime(df[c],errors='coerce')
                con.register('tmp_theses',df[['user_id']+THESIS_COLUMNS]); con.execute('INSERT OR IGNORE INTO user_investment_theses SELECT * FROM tmp_theses')
    except Exception as e: log_event('theses_import_error',error=str(e)[:180])
    con.close()


def upsert_thesis(ticker, thesis='', catalysts='', invalidation='', target='', review_date='', status='ACTIVE', note='', user_id=None):
    ticker=str(ticker or '').upper().strip(); uid=str(user_id or _default_alert_user_id()); now=_utcnow_naive()
    if not ticker: raise ValueError('Ticker vacío')
    existing=load_theses(ticker,user_id=uid); created=existing.iloc[0]['created_at'] if not existing.empty else now
    vals=[uid,ticker,created,now,str(thesis or ''),str(catalysts or ''),str(invalidation or ''),str(target or ''),str(review_date),str(status or 'ACTIVE'),str(note or '')]
    con=_conn(); _ensure_user_portfolio_tables(con)
    con.execute('''INSERT INTO user_investment_theses VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (user_id,ticker) DO UPDATE SET updated_at=EXCLUDED.updated_at,thesis=EXCLUDED.thesis,
        catalysts=EXCLUDED.catalysts,invalidation=EXCLUDED.invalidation,target=EXCLUDED.target,
        review_date=EXCLUDED.review_date,status=EXCLUDED.status,note=EXCLUDED.note''',vals)
    con.close(); _mirror_theses_csv()
    if cloud_available():
        ok,msg=execute_sql('''INSERT INTO user_investment_theses (user_id,ticker,created_at,updated_at,thesis,catalysts,invalidation,target,review_date,status,note)
            VALUES (:uid,:ticker,:created,:updated,:thesis,:catalysts,:invalidation,:target,:review,:status,:note)
            ON CONFLICT (user_id,ticker) DO UPDATE SET updated_at=EXCLUDED.updated_at,thesis=EXCLUDED.thesis,catalysts=EXCLUDED.catalysts,
            invalidation=EXCLUDED.invalidation,target=EXCLUDED.target,review_date=EXCLUDED.review_date,status=EXCLUDED.status,note=EXCLUDED.note''',
            {'uid':uid,'ticker':ticker,'created':created,'updated':now,'thesis':str(thesis or ''),'catalysts':str(catalysts or ''),'invalidation':str(invalidation or ''),'target':str(target or ''),'review':str(review_date),'status':str(status or 'ACTIVE'),'note':str(note or '')})
        if not ok: raise RuntimeError(f'No se pudo guardar la tesis en Postgres: {msg}')
    return True


def load_theses(ticker=None, user_id=None):
    uid=str(user_id or _default_alert_user_id())
    if cloud_available():
        _migrate_cloud_legacy_portfolio_if_needed(uid)
        q='SELECT ticker,created_at,updated_at,thesis,catalysts,invalidation,target,review_date,status,note FROM user_investment_theses WHERE user_id=:uid'; params={'uid':uid}
        if ticker: q+=' AND ticker=:ticker'; params['ticker']=str(ticker).upper().strip()
        q+=' ORDER BY updated_at DESC'; x=query_sql(q,params)
        if not x.empty: return x
    import_theses_csv_if_needed(); con=_conn(); _ensure_user_portfolio_tables(con)
    q='SELECT ticker,created_at,updated_at,thesis,catalysts,invalidation,target,review_date,status,note FROM user_investment_theses WHERE user_id=?'; params=[uid]
    if ticker: q+=' AND ticker=?'; params.append(str(ticker).upper().strip())
    q+=' ORDER BY updated_at DESC'; x=con.execute(q,params).df(); con.close(); return x


def delete_thesis(ticker, user_id=None):
    ticker=str(ticker or '').upper().strip(); uid=str(user_id or _default_alert_user_id())
    if cloud_available():
        ok,msg=execute_sql('DELETE FROM user_investment_theses WHERE user_id=:uid AND ticker=:ticker',{'uid':uid,'ticker':ticker})
        if not ok: raise RuntimeError(msg)
    con=_conn(); _ensure_user_portfolio_tables(con)
    con.execute('DELETE FROM user_investment_theses WHERE user_id=? AND ticker=?',[uid,ticker]); con.close(); _mirror_theses_csv()

def save_json_snapshot(data, name):
    path=SNAPSHOT_DIR/f'{name}.json'
    def clean(v):
        # Pandas containers need an explicit conversion before json.dumps().
        # `institutional_macro_snapshot()` includes Slow_Table as a DataFrame,
        # which is what caused the GitHub Actions daily refresh to fail.
        if isinstance(v, pd.DataFrame):
            return [clean(row) for row in v.to_dict(orient='records')]
        if isinstance(v, pd.Series):
            return {str(k): clean(x) for k, x in v.to_dict().items()}
        if isinstance(v, pd.Index):
            return [clean(x) for x in v.tolist()]
        if isinstance(v,(pd.Timestamp,datetime)): return str(v)
        try:
            if pd.isna(v): return None
        except (TypeError, ValueError):
            # Array-like objects do not have a single truth value.
            pass
        if hasattr(v,'item'):
            try: return clean(v.item())
            except Exception: pass
        if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
        if isinstance(v,(list,tuple,set)): return [clean(x) for x in v]
        if hasattr(v, 'tolist'):
            try: return clean(v.tolist())
            except Exception: pass
        return v
    path.write_text(json.dumps(clean(data),ensure_ascii=False,indent=2),encoding='utf-8'); return path


def load_json_snapshot(name):
    path=SNAPSHOT_DIR/f'{name}.json'
    if not path.exists(): return None
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception as e: log_event('json_snapshot_read_error',file=path.name,error=str(e)[:180]); return None


def sync_local_state_to_cloud():
    # One-way bootstrap for Postgres. User IDs are preserved for all scoped data.
    report=[]
    if not cloud_available():
        return pd.DataFrame([{'Table':'all','Rows':0,'Status':'DATABASE_URL not configured'}])
    ensure_production_schema()
    import_alerts_csv_if_needed(); import_positions_csv_if_needed(); import_theses_csv_if_needed()
    con=_conn(); _ensure_user_portfolio_tables(con)
    alerts=_normalize_alerts(con.execute('SELECT * FROM saved_alerts').df())
    states=_normalize_alert_state(con.execute('SELECT * FROM alert_state').df())
    positions=con.execute('SELECT * FROM user_portfolio_positions').df()
    theses=con.execute('SELECT * FROM user_investment_theses').df(); con.close()

    ok_count=0
    for _,r in alerts.iterrows():
        ok,_=execute_sql('''INSERT INTO saved_alerts (id,user_id,created_at,ticker,rule_type,threshold,enabled,note,cooldown_minutes,repeat_while_true)
            VALUES (:id,:uid,:created_at,:ticker,:rule_type,:threshold,:enabled,:note,:cooldown,:repeat)
            ON CONFLICT (id) DO UPDATE SET user_id=EXCLUDED.user_id,ticker=EXCLUDED.ticker,rule_type=EXCLUDED.rule_type,
            threshold=EXCLUDED.threshold,enabled=EXCLUDED.enabled,note=EXCLUDED.note,cooldown_minutes=EXCLUDED.cooldown_minutes,
            repeat_while_true=EXCLUDED.repeat_while_true''',
            {'id':int(r['id']),'uid':str(r.get('user_id') or 'local-user'),'created_at':r['created_at'],'ticker':r['ticker'],
             'rule_type':r['rule_type'],'threshold':float(r['threshold']),'enabled':bool(r['enabled']),'note':str(r.get('note','') or ''),
             'cooldown':int(r.get('cooldown_minutes',240) or 240),'repeat':bool(r.get('repeat_while_true',False))})
        ok_count+=int(ok)
    report.append({'Table':'saved_alerts','Rows':len(alerts),'Status':f'{ok_count}/{len(alerts)} synced'})

    ok_count=0
    for _,r in states.iterrows():
        ok,_=execute_sql('''INSERT INTO alert_state (alert_id,last_hit,last_triggered_at,last_evaluated_at,last_message,trigger_count)
            VALUES (:id,:hit,:trig,:eval,:msg,:count)
            ON CONFLICT (alert_id) DO UPDATE SET last_hit=EXCLUDED.last_hit,last_triggered_at=EXCLUDED.last_triggered_at,
            last_evaluated_at=EXCLUDED.last_evaluated_at,last_message=EXCLUDED.last_message,trigger_count=EXCLUDED.trigger_count''',
            {'id':int(r['alert_id']),'hit':bool(r['last_hit']),'trig':r['last_triggered_at'],'eval':r['last_evaluated_at'],
             'msg':str(r.get('last_message','') or ''),'count':int(r.get('trigger_count',0) or 0)})
        ok_count+=int(ok)
    report.append({'Table':'alert_state','Rows':len(states),'Status':f'{ok_count}/{len(states)} synced'})

    ok_count=0
    for _,r in positions.iterrows():
        allocation=None if pd.isna(r.get('allocation_pct')) else float(r.get('allocation_pct'))
        ok,_=execute_sql('''INSERT INTO user_portfolio_positions (user_id,ticker,quantity,avg_cost,allocation_pct,sector,note,updated_at)
            VALUES (:uid,:ticker,:q,:cost,:allocation,:sector,:note,:updated)
            ON CONFLICT (user_id,ticker) DO UPDATE SET quantity=EXCLUDED.quantity,avg_cost=EXCLUDED.avg_cost,
            allocation_pct=EXCLUDED.allocation_pct,sector=EXCLUDED.sector,note=EXCLUDED.note,updated_at=EXCLUDED.updated_at''',
            {'uid':str(r['user_id']),'ticker':r['ticker'],'q':float(r['quantity']),'cost':float(r['avg_cost']),
             'allocation':allocation,'sector':str(r.get('sector','Unknown')),'note':str(r.get('note','') or ''),'updated':r['updated_at']})
        ok_count+=int(ok)
    report.append({'Table':'user_portfolio_positions','Rows':len(positions),'Status':f'{ok_count}/{len(positions)} synced'})

    ok_count=0
    for _,r in theses.iterrows():
        ok,_=execute_sql('''INSERT INTO user_investment_theses (user_id,ticker,created_at,updated_at,thesis,catalysts,invalidation,target,review_date,status,note)
            VALUES (:uid,:ticker,:created,:updated,:thesis,:catalysts,:invalidation,:target,:review,:status,:note)
            ON CONFLICT (user_id,ticker) DO UPDATE SET updated_at=EXCLUDED.updated_at,thesis=EXCLUDED.thesis,
            catalysts=EXCLUDED.catalysts,invalidation=EXCLUDED.invalidation,target=EXCLUDED.target,
            review_date=EXCLUDED.review_date,status=EXCLUDED.status,note=EXCLUDED.note''',
            {'uid':str(r['user_id']),'ticker':r['ticker'],'created':r['created_at'],'updated':r['updated_at'],
             'thesis':str(r.get('thesis','') or ''),'catalysts':str(r.get('catalysts','') or ''),'invalidation':str(r.get('invalidation','') or ''),
             'target':str(r.get('target','') or ''),'review':str(r.get('review_date','') or ''),'status':str(r.get('status','ACTIVE') or 'ACTIVE'),
             'note':str(r.get('note','') or '')})
        ok_count+=int(ok)
    report.append({'Table':'user_investment_theses','Rows':len(theses),'Status':f'{ok_count}/{len(theses)} synced'})
    return pd.DataFrame(report)
