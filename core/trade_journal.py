from pathlib import Path
from datetime import datetime, timezone
import duckdb
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data'/'market_screener.duckdb'


def _con():
    c=duckdb.connect(str(DB))
    c.execute('''CREATE TABLE IF NOT EXISTS trade_journal (
        id BIGINT, opened_at TIMESTAMP, closed_at TIMESTAMP, ticker VARCHAR,
        side VARCHAR, setup VARCHAR, thesis VARCHAR, catalyst VARCHAR,
        entry DOUBLE, stop DOUBLE, target DOUBLE, exit DOUBLE,
        quantity DOUBLE, score_at_entry DOUBLE, confidence_at_entry DOUBLE,
        status VARCHAR, notes VARCHAR, pnl_dollars DOUBLE, pnl_percent DOUBLE
    )''')
    return c


def add_trade(ticker, side, setup, thesis, catalyst, entry, stop, target, quantity, score, confidence, notes=''):
    c=_con(); nid=c.execute('SELECT COALESCE(MAX(id),0)+1 FROM trade_journal').fetchone()[0]
    c.execute('INSERT INTO trade_journal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',[
        nid,datetime.now(timezone.utc).replace(tzinfo=None),None,ticker.upper(),side,setup,thesis,catalyst,
        float(entry),float(stop),float(target),None,float(quantity),float(score) if score is not None else None,
        float(confidence) if confidence is not None else None,'OPEN',notes,None,None
    ]); c.close(); return nid


def close_trade(trade_id, exit_price, notes=''):
    c=_con(); row=c.execute('SELECT entry, quantity, side FROM trade_journal WHERE id=?',[int(trade_id)]).fetchone()
    if not row: c.close(); return False
    entry,qty,side=row; mult=1 if str(side).upper()=='LONG' else -1
    pnl=(float(exit_price)-float(entry))*float(qty)*mult
    pct=(float(exit_price)/float(entry)-1)*100*mult if entry else None
    c.execute('UPDATE trade_journal SET closed_at=?, exit=?, status=?, notes=COALESCE(notes,\'\') || ?, pnl_dollars=?, pnl_percent=? WHERE id=?',[
        datetime.now(timezone.utc).replace(tzinfo=None),float(exit_price),'CLOSED',(' | '+notes if notes else ''),pnl,pct,int(trade_id)
    ]); c.close(); return True


def list_trades(status=None):
    c=_con(); q='SELECT * FROM trade_journal'; params=[]
    if status:
        q+=' WHERE status=?'; params=[status]
    q+=' ORDER BY opened_at DESC'; df=c.execute(q,params).df(); c.close(); return df


def journal_stats():
    df=list_trades('CLOSED')
    if df.empty: return {}
    pnl=pd.to_numeric(df['pnl_dollars'],errors='coerce').dropna(); pct=pd.to_numeric(df['pnl_percent'],errors='coerce').dropna()
    return {
        'Closed Trades':len(df),
        'Win Rate %':round((pnl>0).mean()*100,1) if len(pnl) else np.nan,
        'Total P&L $':float(pnl.sum()) if len(pnl) else np.nan,
        'Median Trade %':float(pct.median()) if len(pct) else np.nan,
        'Average Trade %':float(pct.mean()) if len(pct) else np.nan,
    }
