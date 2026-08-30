import numpy as np
import pandas as pd

import core.fundamentals as fundamentals


class BrokenYahoo:
    @property
    def info(self):
        raise RuntimeError('quoteSummary throttled')
    @property
    def financials(self):
        return pd.DataFrame()
    @property
    def balance_sheet(self):
        return pd.DataFrame()
    @property
    def cashflow(self):
        return pd.DataFrame()


class StatementYahoo:
    @property
    def info(self):
        raise RuntimeError('info unavailable')
    @property
    def financials(self):
        return pd.DataFrame({
            pd.Timestamp('2025-12-31'):[120.0,24.0,36.0,18.0],
            pd.Timestamp('2024-12-31'):[100.0,20.0,30.0,15.0],
        }, index=['Total Revenue','Net Income','Gross Profit','Operating Income'])
    @property
    def balance_sheet(self):
        return pd.DataFrame({pd.Timestamp('2025-12-31'):[20.0,10.0,80.0,40.0,20.0]},
                            index=['Total Debt','Cash And Cash Equivalents','Stockholders Equity','Current Assets','Current Liabilities'])
    @property
    def cashflow(self):
        return pd.DataFrame({pd.Timestamp('2025-12-31'):[30.0,-8.0]}, index=['Operating Cash Flow','Capital Expenditure'])


def _clear_cache(fn):
    clear=getattr(fn,'clear',None)
    if callable(clear): clear()


def test_fundamentals_survive_yahoo_failure_when_fmp_works(monkeypatch):
    _clear_cache(fundamentals.get_fundamentals)
    monkeypatch.setattr(fundamentals.yf,'Ticker',lambda ticker: BrokenYahoo())
    monkeypatch.setattr(fundamentals,'fmp_equity_snapshot',lambda ticker:{
        'available':True,'Market_Cap':1000.0,'Revenue_Growth':0.15,'Earnings_Growth':0.20,
        'Profit_Margin':0.18,'ROE':0.22,'Debt_Equity':35.0,'Forward_PE':19.0,
        'Price_to_Book':3.0,'EV_EBITDA':12.0,'Industry':'Semiconductors','Sector':'Technology',
        'Observed_Fields':['Market_Cap','Revenue_Growth']
    })
    monkeypatch.setattr(fundamentals,'sec_specialist_snapshot',lambda ticker:{'available':False})
    out=fundamentals.get_fundamentals('TEST')
    assert not out.get('error')
    assert out['Fundamental_Score'] > 50
    assert out['Revenue_Growth'] == 0.15
    assert out['Fundamentals_Provider_Status']['FMP'] == 'OK'


def test_statement_fallback_builds_real_quality_inputs(monkeypatch):
    _clear_cache(fundamentals.get_fundamentals)
    monkeypatch.setattr(fundamentals.yf,'Ticker',lambda ticker: StatementYahoo())
    monkeypatch.setattr(fundamentals,'fmp_equity_snapshot',lambda ticker:{'available':False})
    monkeypatch.setattr(fundamentals,'sec_specialist_snapshot',lambda ticker:{'available':False})
    out=fundamentals.get_fundamentals('TEST2')
    assert not out.get('error')
    assert np.isclose(out['Revenue_Growth'],0.20)
    assert np.isclose(out['Earnings_Growth'],0.20)
    assert np.isclose(out['FCF'],22.0)
    assert np.isclose(out['ROE'],0.30)
    assert out['Fundamentals_Provider_Status']['YahooStatements'] == 'OK'
