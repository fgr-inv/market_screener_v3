import pandas as pd

from core.portfolio_import import normalize_positions_csv
from core.portfolio_positions import apply_live_prices, portfolio_weight_alerts


def _detail():
    return pd.DataFrame([
        {'Ticker':'AAA','Sector':'Technology','Quantity':2.0,'Price':100.0,'Market Value':200.0,
         'Declared Allocation %':None,'Weight %':50.0},
        {'Ticker':'BBB','Sector':'Financials','Quantity':4.0,'Price':50.0,'Market Value':200.0,
         'Declared Allocation %':None,'Weight %':50.0},
    ])


def test_live_quotes_recalculate_quantity_weights():
    out=apply_live_prices(_detail(),{'AAA':150,'BBB':50}).set_index('Ticker')
    assert out.loc['AAA','Market Value']==300
    assert out.loc['BBB','Market Value']==200
    assert round(out.loc['AAA','Weight %'],2)==60.00
    assert round(out.loc['BBB','Weight %'],2)==40.00


def test_declared_percentage_does_not_drift_with_price():
    detail=_detail()
    detail['Declared Allocation %']=[30.0,70.0]
    out=apply_live_prices(detail,{'AAA':1000,'BBB':1})
    assert out['Weight %'].tolist()==[30.0,70.0]


def test_weight_alerts_cover_positions_sectors_and_target_groups():
    alerts=portfolio_weight_alerts(_detail(),position_limit_pct=40,sector_limit_pct=40,
        target_groups=[{'name':'Bitcoin','tickers':['AAA'],'target_pct':45}])
    kinds=[row['kind'] for row in alerts]
    assert kinds.count('POSITION_CONCENTRATION')==2
    assert kinds.count('SECTOR_CONCENTRATION')==2
    target=next(row for row in alerts if row['kind']=='TARGET_GROUP')
    assert target['value_pct']==50 and target['delta_pct']==5


def test_import_combines_duplicate_tickers_with_weighted_cost(tmp_path):
    path=tmp_path/'positions.csv'
    path.write_text('ticker,quantity,avg_cost\nAMD,2,100\nAMD,3,200\nNVDA,1,50\n',encoding='utf-8')
    out=normalize_positions_csv(path).set_index('ticker')
    assert out.loc['AMD','quantity']==5
    assert out.loc['AMD','avg_cost']==160
    assert out.loc['NVDA','quantity']==1
