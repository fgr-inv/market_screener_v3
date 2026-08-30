import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

from core.utils import clamp
from core.institutional_providers import fmp_equity_snapshot
from core.free_specialist_data import sec_specialist_snapshot, clinicaltrials_company_snapshot, openfda_company_snapshot
from core.cache_policy import FUNDAMENTALS_TTL, VALUATION_TTL


def _safe(d, k):
    try:
        v = d.get(k, np.nan)
    except Exception:
        return np.nan
    return np.nan if v is None else v


def _num(v):
    try:
        x = float(v)
        return x if np.isfinite(x) else np.nan
    except Exception:
        return np.nan


def _blank():
    keys = [
        'Market_Cap','Enterprise_Value','Revenue','EBITDA','Forward_PE','Trailing_PE','EV_EBITDA',
        'Price_to_Book','Revenue_Growth','Earnings_Growth','Profit_Margin','Operating_Margin',
        'Gross_Margin','EBITDA_Margin','ROE','ROA','Debt_Equity','FCF','Operating_Cashflow',
        'Total_Cash','Total_Debt','Current_Ratio','Quick_Ratio','Dividend_Yield','Payout_Ratio',
        'PEG','Price_to_Sales','EV_Revenue','Trailing_EPS','Forward_EPS','52w_High','Beta',
        'Sector','Industry'
    ]
    out = {k: np.nan for k in keys}
    out.update({
        'Yahoo_Info_Available': False,
        'Yahoo_Statements_Available': False,
        'FMP_Available': False,
        'SEC_Data_Available': False,
        'Fundamentals_Source': 'NONE',
        'Provider_Issues': [],
        'Fundamentals_Provider_Status': {
            'YahooInfo': 'NOT_RUN',
            'YahooStatements': 'NOT_RUN',
            'FMP': 'NOT_RUN',
            'SEC': 'NOT_RUN',
        },
    })
    return out


@st.cache_data(ttl=VALUATION_TTL, show_spinner=False)
def get_market_valuation_snapshot(ticker):
    """Daily market-sensitive valuation overlay.

    Accounting fundamentals can safely live for a week, while price-dependent
    multiples should refresh more often.  This small Yahoo-only overlay updates
    those fields without re-running SEC/FMP/company-facts every day.
    """
    ticker = str(ticker).upper().strip()
    out = {}
    try:
        info = yf.Ticker(ticker).info or {}
        mapping = {
            'Market_Cap':'marketCap', 'Enterprise_Value':'enterpriseValue',
            'Forward_PE':'forwardPE', 'Trailing_PE':'trailingPE',
            'EV_EBITDA':'enterpriseToEbitda', 'Price_to_Book':'priceToBook',
            'PEG':'pegRatio', 'Price_to_Sales':'priceToSalesTrailing12Months',
            'EV_Revenue':'enterpriseToRevenue', '52w_High':'fiftyTwoWeekHigh',
            'Beta':'beta', 'Forward_EPS':'forwardEps', 'Trailing_EPS':'trailingEps',
        }
        for dst, src in mapping.items():
            v = _safe(info, src)
            if pd.notna(v):
                out[dst] = v
        out['Valuation_Market_Overlay_Available'] = bool(out)
    except Exception as exc:
        out = {'Valuation_Market_Overlay_Available': False, 'Valuation_Market_Overlay_Error': type(exc).__name__}
    return out


def _statement_value(df, names, col=0):
    if not isinstance(df, pd.DataFrame) or df.empty:
        return np.nan
    idx_map = {str(i).lower().replace(' ', '').replace('_', ''): i for i in df.index}
    for name in names:
        key = str(name).lower().replace(' ', '').replace('_', '')
        if key in idx_map:
            try:
                return _num(df.loc[idx_map[key]].iloc[col])
            except Exception:
                pass
    return np.nan


def _yahoo_statement_fallback(t, f):
    """Fill fundamentals from Yahoo statements when .info is unavailable/rate-limited."""
    try:
        inc = t.financials
    except Exception:
        inc = pd.DataFrame()
    try:
        cf = t.cashflow
    except Exception:
        cf = pd.DataFrame()
    try:
        bs = t.balance_sheet
    except Exception:
        bs = pd.DataFrame()

    if all(x.empty for x in (inc, cf, bs) if isinstance(x, pd.DataFrame)):
        return False

    rev0 = _statement_value(inc, ['Total Revenue', 'Operating Revenue'], 0)
    rev1 = _statement_value(inc, ['Total Revenue', 'Operating Revenue'], 1) if getattr(inc, 'shape', (0,0))[1] > 1 else np.nan
    ni0 = _statement_value(inc, ['Net Income', 'Net Income Common Stockholders'], 0)
    ni1 = _statement_value(inc, ['Net Income', 'Net Income Common Stockholders'], 1) if getattr(inc, 'shape', (0,0))[1] > 1 else np.nan
    gp0 = _statement_value(inc, ['Gross Profit'], 0)
    op0 = _statement_value(inc, ['Operating Income'], 0)
    ebitda0 = _statement_value(inc, ['EBITDA', 'Normalized EBITDA'], 0)
    cfo0 = _statement_value(cf, ['Operating Cash Flow', 'Total Cash From Operating Activities'], 0)
    capex0 = _statement_value(cf, ['Capital Expenditure', 'Capital Expenditures'], 0)
    fcf0 = _statement_value(cf, ['Free Cash Flow'], 0)
    cash0 = _statement_value(bs, ['Cash Cash Equivalents And Short Term Investments', 'Cash And Cash Equivalents'], 0)
    debt0 = _statement_value(bs, ['Total Debt'], 0)
    assets0 = _statement_value(bs, ['Current Assets'], 0)
    liab0 = _statement_value(bs, ['Current Liabilities'], 0)
    equity0 = _statement_value(bs, ['Stockholders Equity', 'Total Equity Gross Minority Interest'], 0)

    vals = {
        'Revenue': rev0,
        'EBITDA': ebitda0,
        'Operating_Cashflow': cfo0,
        'Total_Cash': cash0,
        'Total_Debt': debt0,
    }
    if pd.isna(fcf0) and pd.notna(cfo0) and pd.notna(capex0):
        # Yahoo capex is commonly negative; adding it to CFO yields FCF.
        fcf0 = cfo0 + capex0 if capex0 < 0 else cfo0 - capex0
    vals['FCF'] = fcf0
    if pd.notna(rev0) and rev0:
        vals['Gross_Margin'] = gp0 / abs(rev0) if pd.notna(gp0) else np.nan
        vals['Operating_Margin'] = op0 / abs(rev0) if pd.notna(op0) else np.nan
        vals['Profit_Margin'] = ni0 / abs(rev0) if pd.notna(ni0) else np.nan
    if pd.notna(rev0) and pd.notna(rev1) and rev1:
        vals['Revenue_Growth'] = rev0 / abs(rev1) - 1
    if pd.notna(ni0) and pd.notna(ni1) and ni1:
        vals['Earnings_Growth'] = ni0 / abs(ni1) - 1
    if pd.notna(ni0) and pd.notna(equity0) and equity0:
        vals['ROE'] = ni0 / abs(equity0)
    if pd.notna(assets0) and pd.notna(liab0) and liab0:
        vals['Current_Ratio'] = assets0 / abs(liab0)

    for k, v in vals.items():
        if pd.notna(v) and (k not in f or pd.isna(f.get(k))):
            f[k] = v
    return any(pd.notna(v) for v in vals.values())


def _score(f):
    s = 50
    rg, eg = _num(f.get('Revenue_Growth')), _num(f.get('Earnings_Growth'))
    pm, roe = _num(f.get('Profit_Margin')), _num(f.get('ROE'))
    de, pe, fcf = _num(f.get('Debt_Equity')), _num(f.get('Forward_PE')), _num(f.get('FCF'))
    if pd.notna(rg): s += 14 if rg >= .20 else 9 if rg >= .10 else 3 if rg > 0 else -8
    if pd.notna(eg): s += 16 if eg >= .25 else 11 if eg >= .12 else 4 if eg > 0 else -10
    if pd.notna(pm): s += 10 if pm >= .20 else 6 if pm >= .10 else 2 if pm > 0 else -8
    if pd.notna(roe): s += 10 if roe >= .25 else 6 if roe >= .15 else 2 if roe > 0 else -6
    if pd.notna(de): s += 5 if de < 50 else 2 if de < 100 else -5 if de > 200 else 0
    if pd.notna(pe): s += 7 if 0 < pe <= 20 else 4 if pe <= 30 else 0 if pe <= 45 else -5
    if pd.notna(fcf): s += 6 if fcf > 0 else -6
    return int(clamp(s))


@st.cache_data(ttl=FUNDAMENTALS_TTL, show_spinner=False)
def get_fundamentals(ticker):
    """Resilient free-data fundamentals.

    Providers fail independently. A failure in Yahoo, FMP, SEC, ClinicalTrials or
    openFDA never discards observations already obtained from another provider.
    """
    ticker = str(ticker).upper().strip()
    f = _blank()
    info = {}
    try:
        t = yf.Ticker(ticker)
    except Exception as exc:
        f['Provider_Issues'].append(f'Yahoo ticker: {type(exc).__name__}')
        t = None

    # Yahoo info (best convenient source, but often rate-limited).
    if t is not None:
        try:
            info = t.info or {}
            if info:
                f['Yahoo_Info_Available'] = True
                f['Fundamentals_Provider_Status']['YahooInfo'] = 'OK'
                mapping = {
                    'Market_Cap':'marketCap','Enterprise_Value':'enterpriseValue','Revenue':'totalRevenue','EBITDA':'ebitda',
                    'Forward_PE':'forwardPE','Trailing_PE':'trailingPE','EV_EBITDA':'enterpriseToEbitda','Price_to_Book':'priceToBook',
                    'Revenue_Growth':'revenueGrowth','Earnings_Growth':'earningsGrowth','Profit_Margin':'profitMargins',
                    'Operating_Margin':'operatingMargins','Gross_Margin':'grossMargins','EBITDA_Margin':'ebitdaMargins',
                    'ROE':'returnOnEquity','ROA':'returnOnAssets','Debt_Equity':'debtToEquity','FCF':'freeCashflow',
                    'Operating_Cashflow':'operatingCashflow','Total_Cash':'totalCash','Total_Debt':'totalDebt',
                    'Current_Ratio':'currentRatio','Quick_Ratio':'quickRatio','Dividend_Yield':'dividendYield','Payout_Ratio':'payoutRatio',
                    'PEG':'pegRatio','Price_to_Sales':'priceToSalesTrailing12Months','EV_Revenue':'enterpriseToRevenue',
                    'Trailing_EPS':'trailingEps','Forward_EPS':'forwardEps','52w_High':'fiftyTwoWeekHigh','Beta':'beta',
                    'Sector':'sector','Industry':'industry'
                }
                for dst, src in mapping.items():
                    v = _safe(info, src)
                    if pd.notna(v):
                        f[dst] = v
        except Exception as exc:
            f['Fundamentals_Provider_Status']['YahooInfo'] = f'ERROR:{type(exc).__name__}'
            f['Provider_Issues'].append(f'Yahoo info: {type(exc).__name__}')

        try:
            f['Yahoo_Statements_Available'] = bool(_yahoo_statement_fallback(t, f))
            f['Fundamentals_Provider_Status']['YahooStatements'] = 'OK' if f['Yahoo_Statements_Available'] else 'NO_DATA'
        except Exception as exc:
            f['Fundamentals_Provider_Status']['YahooStatements'] = f'ERROR:{type(exc).__name__}'
            f['Provider_Issues'].append(f'Yahoo statements: {type(exc).__name__}')

    # FMP must never be a single point of failure.
    try:
        fmp = fmp_equity_snapshot(ticker) or {}
        f['FMP_Available'] = bool(fmp.get('available'))
        f['Fundamentals_Provider_Status']['FMP'] = 'OK' if f['FMP_Available'] else 'NO_DATA'
        if f['FMP_Available']:
            for k, v in fmp.items():
                if k in {'available','provider','reason','error'}:
                    continue
                if k in f and pd.notna(v) and (pd.isna(f.get(k)) or f.get(k) in (None, '')):
                    f[k] = v
                elif k in ['ROIC','FCF_Yield','Piotroski_Score','Altman_Z_Score','FMP_Estimates_Available'] and pd.notna(v):
                    f[k] = v
            f['FMP_Observed_Fields'] = fmp.get('Observed_Fields', [])
        else:
            f['FMP_Observed_Fields'] = []
    except Exception as exc:
        f['FMP_Available'] = False
        f['Fundamentals_Provider_Status']['FMP'] = f'ERROR:{type(exc).__name__}'
        f['FMP_Observed_Fields'] = []
        f['Provider_Issues'].append(f'FMP: {type(exc).__name__}')

    # SEC XBRL official layer, independent from Yahoo/FMP.
    try:
        sec = sec_specialist_snapshot(ticker) or {}
        f['SEC_Data_Available'] = bool(sec.get('available'))
        f['Fundamentals_Provider_Status']['SEC'] = 'OK' if f['SEC_Data_Available'] else 'NO_DATA'
        if f['SEC_Data_Available']:
            for k, v in sec.items():
                if k in {'available','provider','reason','error'}:
                    continue
                if isinstance(v, (list, dict)) or pd.notna(v):
                    # SEC specialist fields are authoritative where mapped.
                    f[k] = v
    except Exception as exc:
        f['SEC_Data_Available'] = False
        f['Fundamentals_Provider_Status']['SEC'] = f'ERROR:{type(exc).__name__}'
        f['Provider_Issues'].append(f'SEC: {type(exc).__name__}')

    # Biopharma specialist context must not break base fundamentals.
    ind = str(f.get('Industry', '')).lower()
    if any(x in ind for x in ('biotech','drug','pharma')):
        company = str(info.get('shortName') or info.get('longName') or ticker)
        try:
            ct = clinicaltrials_company_snapshot(company) or {}
            for k, v in ct.items():
                if k not in {'available','provider','reason','error'}:
                    f[k] = v
            f['ClinicalTrials_Available'] = bool(ct.get('available'))
            if ct.get('available'):
                f['Trial_Phase'] = ct.get('Trial_Phases', {})
                f['Pipeline'] = {'active_trials':ct.get('Active_Trials',0),'total_trials':ct.get('Trial_Count',0)}
        except Exception as exc:
            f['ClinicalTrials_Available'] = False
            f['Provider_Issues'].append(f'ClinicalTrials: {type(exc).__name__}')
        try:
            fd = openfda_company_snapshot(company) or {}
            for k, v in fd.items():
                if k not in {'available','provider','reason','error'}:
                    f[k] = v
            f['openFDA_Available'] = bool(fd.get('available'))
        except Exception as exc:
            f['openFDA_Available'] = False
            f['Provider_Issues'].append(f'openFDA: {type(exc).__name__}')

    rev = _num(f.get('Revenue'))
    fcf = _num(f.get('FCF'))
    ocf = _num(f.get('Operating_Cashflow'))
    debt = _num(f.get('Total_Debt'))
    cash = _num(f.get('Total_Cash'))
    mc = _num(f.get('Market_Cap'))
    if pd.notna(rev) and rev:
        if pd.notna(fcf): f['FCF_Margin'] = fcf / abs(rev)
        if pd.notna(ocf): f['OCF_Margin'] = ocf / abs(rev)
    if pd.notna(debt) and pd.notna(cash): f['Net_Debt'] = debt - cash
    if pd.notna(fcf) and pd.notna(mc) and mc: f['FCF_Yield'] = fcf / mc

    sources = []
    if f.get('Yahoo_Info_Available') or f.get('Yahoo_Statements_Available'): sources.append('Yahoo Finance')
    if f.get('FMP_Available'): sources.append('FMP')
    if f.get('SEC_Data_Available'): sources.append('SEC EDGAR')
    f['Fundamentals_Source'] = ' + '.join(sources) if sources else 'NONE'
    f['Premium_Fundamentals_Source'] = f['Fundamentals_Source']
    f['Fundamental_Score'] = _score(f)

    observed_core = sum(pd.notna(f.get(k)) for k in ['Revenue','Revenue_Growth','Earnings_Growth','Profit_Margin','ROE','FCF'])
    f['Fundamentals_Available'] = observed_core >= 1
    if not f['Fundamentals_Available']:
        f['error'] = 'No core fundamental observations returned by free providers'
    notes = []
    if pd.notna(_num(f.get('Revenue_Growth'))) and _num(f.get('Revenue_Growth')) >= .10: notes.append('Ingresos creciendo a doble dígito.')
    if pd.notna(_num(f.get('Earnings_Growth'))) and _num(f.get('Earnings_Growth')) >= .12: notes.append('Beneficios creciendo con fuerza.')
    if pd.notna(_num(f.get('Profit_Margin'))) and _num(f.get('Profit_Margin')) >= .15: notes.append('Márgenes atractivos.')
    if pd.notna(_num(f.get('Forward_PE'))) and _num(f.get('Forward_PE')) > 40: notes.append('Valoración exigente.')
    f['Comment'] = ' '.join(notes) or 'Fundamentales mixtos o incompletos.'
    return f
