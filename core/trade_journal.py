from pathlib import Path
from datetime import datetime, timezone
import os
import secrets

import duckdb
import numpy as np
import pandas as pd

from core.production_storage import cloud_available, execute_sql, query_sql, ensure_production_schema

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data'/'market_screener.duckdb'

COLUMNS=[
    'user_id','id','opened_at','closed_at','ticker','side','setup','thesis','catalyst',
    'entry','stop','target','exit','quantity','score_at_entry','confidence_at_entry',
    'status','notes','pnl_dollars','pnl_percent'
]


def _default_user_id():
    value=os.getenv('DEV_USER_ID','')
    if not value:
        try:
            import streamlit as st
            value=str(st.secrets.get('DEV_USER_ID',''))
        except Exception:
            pass
    return str(value or 'local-user').strip() or 'local-user'


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _con():
    c=duckdb.connect(str(DB))
    c.execute('''CREATE TABLE IF NOT EXISTS user_trade_journal (
        user_id VARCHAR, id BIGINT, opened_at TIMESTAMP, closed_at TIMESTAMP, ticker VARCHAR,
        side VARCHAR, setup VARCHAR, thesis VARCHAR, catalyst VARCHAR,
        entry DOUBLE, stop DOUBLE, target DOUBLE, exit DOUBLE,
        quantity DOUBLE, score_at_entry DOUBLE, confidence_at_entry DOUBLE,
        status VARCHAR, notes VARCHAR, pnl_dollars DOUBLE, pnl_percent DOUBLE,
        PRIMARY KEY (user_id,id)
    )''')
    # One-time legacy import for the local/default user.
    try:
        exists=c.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name='trade_journal'").fetchone()[0]
        count=c.execute('SELECT COUNT(*) FROM user_trade_journal').fetchone()[0]
        if exists and count==0:
            legacy=c.execute('SELECT * FROM trade_journal').df()
            if not legacy.empty:
                legacy.insert(0,'user_id',_default_user_id())
                for col in COLUMNS:
                    if col not in legacy.columns: legacy[col]=None
                c.register('legacy_trade_journal',legacy[COLUMNS])
                c.execute('INSERT OR IGNORE INTO user_trade_journal SELECT * FROM legacy_trade_journal')
    except Exception:
        pass
    return c


def _new_id():
    return secrets.randbelow(9_000_000_000_000_000_000-1)+1


def _validate_trade(side, entry, stop, target, quantity):
    side=str(side).upper().strip()
    if side not in {'LONG','SHORT'}: raise ValueError('Side debe ser LONG o SHORT')
    entry=float(entry); stop=float(stop); target=float(target); quantity=float(quantity)
    if entry <= 0 or quantity <= 0: raise ValueError('Entry y quantity deben ser > 0')
    if stop < 0 or target < 0: raise ValueError('Stop y target deben ser >= 0')
    if side=='LONG' and stop and stop >= entry: raise ValueError('En LONG el stop debe estar por debajo del entry')
    if side=='SHORT' and stop and stop <= entry: raise ValueError('En SHORT el stop debe estar por encima del entry')
    return side,entry,stop,target,quantity


def add_trade(ticker, side, setup, thesis, catalyst, entry, stop, target, quantity, score, confidence, notes='', user_id=None):
    uid=str(user_id or _default_user_id())
    ticker=str(ticker or '').upper().strip()
    if not ticker: raise ValueError('Ticker vacío')
    side,entry,stop,target,quantity=_validate_trade(side,entry,stop,target,quantity)
    tid=_new_id(); now=_now()
    score=float(score) if score is not None else None
    confidence=float(confidence) if confidence is not None else None
    row=[uid,tid,now,None,ticker,side,str(setup or ''),str(thesis or ''),str(catalyst or ''),entry,stop,target,None,quantity,score,confidence,'OPEN',str(notes or ''),None,None]
    c=_con(); c.execute('INSERT INTO user_trade_journal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',row); c.close()
    if cloud_available():
        ensure_production_schema()
        ok,msg=execute_sql('''INSERT INTO user_trade_journal
            (user_id,id,opened_at,closed_at,ticker,side,setup,thesis,catalyst,entry,stop,target,exit,quantity,score_at_entry,confidence_at_entry,status,notes,pnl_dollars,pnl_percent)
            VALUES (:uid,:id,:opened,NULL,:ticker,:side,:setup,:thesis,:catalyst,:entry,:stop,:target,NULL,:qty,:score,:conf,'OPEN',:notes,NULL,NULL)''',
            {'uid':uid,'id':tid,'opened':now,'ticker':ticker,'side':side,'setup':str(setup or ''),'thesis':str(thesis or ''),'catalyst':str(catalyst or ''),'entry':entry,'stop':stop,'target':target,'qty':quantity,'score':score,'conf':confidence,'notes':str(notes or '')})
        if not ok:
            c=_con(); c.execute('DELETE FROM user_trade_journal WHERE user_id=? AND id=?',[uid,tid]); c.close()
            raise RuntimeError(f'No se pudo guardar el trade en Postgres: {msg}')
    return tid


def close_trade(trade_id, exit_price, notes='', user_id=None):
    uid=str(user_id or _default_user_id()); tid=int(trade_id); exit_price=float(exit_price)
    if exit_price <= 0: raise ValueError('Exit price debe ser > 0')
    c=_con(); row=c.execute('SELECT entry,quantity,side,status,notes FROM user_trade_journal WHERE user_id=? AND id=?',[uid,tid]).fetchone()
    if not row: c.close(); return False
    entry,qty,side,status,old_notes=row
    if str(status).upper()!='OPEN': c.close(); return False
    mult=1 if str(side).upper()=='LONG' else -1
    pnl=(exit_price-float(entry))*float(qty)*mult
    pct=(exit_price/float(entry)-1)*100*mult if entry else None
    merged_notes=(str(old_notes or '') + (' | '+str(notes) if notes else '')).strip(' |')
    now=_now()
    c.execute('''UPDATE user_trade_journal SET closed_at=?,exit=?,status='CLOSED',notes=?,pnl_dollars=?,pnl_percent=?
                 WHERE user_id=? AND id=?''',[now,exit_price,merged_notes,pnl,pct,uid,tid]); c.close()
    if cloud_available():
        ok,msg=execute_sql('''UPDATE user_trade_journal SET closed_at=:closed,exit=:exit,status='CLOSED',notes=:notes,pnl_dollars=:pnl,pnl_percent=:pct
                              WHERE user_id=:uid AND id=:id AND status='OPEN' ''',
                           {'closed':now,'exit':exit_price,'notes':merged_notes,'pnl':pnl,'pct':pct,'uid':uid,'id':tid})
        if not ok: raise RuntimeError(f'No se pudo cerrar el trade en Postgres: {msg}')
    return True


def list_trades(status=None, user_id=None):
    uid=str(user_id or _default_user_id())
    if cloud_available():
        q='SELECT id,opened_at,closed_at,ticker,side,setup,thesis,catalyst,entry,stop,target,exit,quantity,score_at_entry,confidence_at_entry,status,notes,pnl_dollars,pnl_percent FROM user_trade_journal WHERE user_id=:uid'
        params={'uid':uid}
        if status: q+=' AND status=:status'; params['status']=str(status).upper()
        q+=' ORDER BY opened_at DESC'
        x=query_sql(q,params)
        if not x.empty: return x
    c=_con(); q='SELECT id,opened_at,closed_at,ticker,side,setup,thesis,catalyst,entry,stop,target,exit,quantity,score_at_entry,confidence_at_entry,status,notes,pnl_dollars,pnl_percent FROM user_trade_journal WHERE user_id=?'; params=[uid]
    if status: q+=' AND status=?'; params.append(str(status).upper())
    q+=' ORDER BY opened_at DESC'; df=c.execute(q,params).df(); c.close(); return df


def journal_stats(user_id=None):
    df=list_trades('CLOSED',user_id=user_id)
    if df.empty: return {}
    pnl=pd.to_numeric(df['pnl_dollars'],errors='coerce').dropna(); pct=pd.to_numeric(df['pnl_percent'],errors='coerce').dropna()
    gains=pnl[pnl>0]; losses=pnl[pnl<0]
    gross_profit=float(gains.sum()) if len(gains) else 0.0
    gross_loss=abs(float(losses.sum())) if len(losses) else 0.0
    return {
        'Closed Trades':len(df),
        'Win Rate %':round((pnl>0).mean()*100,1) if len(pnl) else np.nan,
        'Total P&L $':float(pnl.sum()) if len(pnl) else np.nan,
        'Average Trade %':float(pct.mean()) if len(pct) else np.nan,
        'Profit Factor':(gross_profit/gross_loss if gross_loss>0 else np.nan),
    }
