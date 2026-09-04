from pathlib import Path

import numpy as np
import pandas as pd

import core.production_storage as storage
import core.shadow_validation as shadow


def test_shadow_outcome_schema_has_incremental_migrations():
    source=(Path(__file__).resolve().parents[1]/'core'/'production_storage.py').read_text(encoding='utf-8')
    for column in ('evaluated_at','status','outcome_at','asset_return_pct','benchmark_return_pct',
                   'alpha_pct','signed_return_pct','signed_alpha_pct','mfe_pct','mae_pct',
                   'success','source','payload_json'):
        assert f'ALTER TABLE user_shadow_outcomes ADD COLUMN IF NOT EXISTS {column} ' in source


def test_database_value_normalizes_numpy_and_missing_values():
    assert shadow._db_value(np.float64(1.25)) == 1.25
    assert type(shadow._db_value(np.float64(1.25))) is float
    assert shadow._db_value(np.int64(5)) == 5
    assert type(shadow._db_value(np.int64(5))) is int
    assert shadow._db_value(np.bool_(True)) is True
    assert shadow._db_value(np.nan) is None
    assert shadow._db_value(pd.NA) is None


def test_cloud_outcome_upsert_uses_native_database_parameters(tmp_path,monkeypatch):
    captured={}
    monkeypatch.setattr(shadow,'DATA_DIR',tmp_path)
    monkeypatch.setattr(shadow,'cloud_available',lambda:True)
    monkeypatch.setattr(shadow,'ensure_production_schema',lambda:(True,'OK'))
    monkeypatch.setattr(shadow,'query_sql',lambda *args,**kwargs:pd.DataFrame())

    def execute(sql,param_rows=None):
        captured.update((param_rows or [])[0])
        return True,'OK'

    monkeypatch.setattr(shadow,'execute_many_sql',execute)
    result=shadow.persist_shadow_outcomes('u',[{
        'decision_key':'d','horizon_days':np.int64(5),'evaluated_at':'2026-09-04T12:00:00Z',
        'status':'MATURED','asset_return_pct':np.float64(2.5),'benchmark_return_pct':np.nan,
        'success':np.bool_(True),'source':'daily bars',
    }])
    assert result['status']=='CURRENT'
    assert type(captured['horizon_days']) is int
    assert type(captured['asset_return_pct']) is float
    assert captured['benchmark_return_pct'] is None
    assert captured['success'] is True


def test_many_shadow_outcomes_use_one_bounded_batch(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(shadow,'DATA_DIR',tmp_path)
    monkeypatch.setattr(shadow,'cloud_available',lambda:True)
    monkeypatch.setattr(shadow,'query_sql',lambda *args,**kwargs:pd.DataFrame())
    monkeypatch.setattr(shadow,'execute_many_sql',lambda sql,rows:(calls.append(list(rows)) or (True,'OK')))
    outcomes=[{'decision_key':f'd-{i}','horizon_days':1,'evaluated_at':'2026-09-04T12:00:00Z',
               'status':'PENDING'} for i in range(220)]
    result=shadow.persist_shadow_outcomes('u',outcomes)
    assert result['status']=='CURRENT'
    assert len(calls)==1 and len(calls[0])==220


def test_engine_is_reused_with_one_connection_pool(monkeypatch):
    created=[]

    class Engine:
        def dispose(self): pass

    def create_engine(url,**kwargs):
        created.append((url,kwargs))
        return Engine()

    import sqlalchemy
    monkeypatch.setattr(sqlalchemy,'create_engine',create_engine)
    monkeypatch.setattr(storage,'_database_url',lambda:'postgresql://redacted')
    monkeypatch.setattr(storage,'_ENGINE',None)
    monkeypatch.setattr(storage,'_ENGINE_KEY',None)
    first=storage._engine(); second=storage._engine()
    assert first is second and len(created)==1
    assert created[0][1]['pool_size']==1
    assert created[0][1]['max_overflow']==0


def test_execute_sql_stops_when_schema_migration_fails(monkeypatch):
    monkeypatch.setattr(storage,'cloud_available',lambda:True)
    monkeypatch.setattr(storage,'ensure_production_schema',lambda:(False,'missing column'))
    ok,message=storage.execute_sql('SELECT 1')
    assert not ok
    assert message=='schema migration failed: missing column'
