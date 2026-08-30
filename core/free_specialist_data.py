from __future__ import annotations

"""Free specialist datasets for sector-aware equity research.

Sources are official/public and require no paid subscription:
SEC EDGAR Company Facts, ClinicalTrials.gov v2 and openFDA.
Missing metrics remain missing; the module never fabricates sector KPIs.
"""
import re
from typing import Any
import numpy as np
import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from core.cache_policy import SPECIALIST_TTL

UA = "MarketScreenerPro/8.6 research app contact: local-user"

def _session():
    s=requests.Session(); retry=Retry(total=2,backoff_factor=.5,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(['GET']))
    s.mount('https://',HTTPAdapter(max_retries=retry)); s.headers.update({'User-Agent':UA,'Accept-Encoding':'gzip, deflate'}); return s

def _num(x):
    try: return float(x)
    except Exception: return np.nan

def _latest_fact(facts:dict,tags:list[str]):
    for tag in tags:
        item=facts.get(tag)
        if not item: continue
        units=item.get('units',{})
        candidates=[]
        for _,rows in units.items():
            if isinstance(rows,list): candidates.extend(rows)
        candidates=[r for r in candidates if r.get('val') is not None]
        if candidates:
            candidates.sort(key=lambda r:(str(r.get('end','')),str(r.get('filed',''))))
            return _num(candidates[-1].get('val')),tag
    return np.nan,''

@st.cache_data(ttl=86400,show_spinner=False)
def sec_ticker_map():
    try:
        r=_session().get('https://www.sec.gov/files/company_tickers.json',timeout=15); r.raise_for_status()
        out={}
        for x in r.json().values(): out[str(x.get('ticker','')).upper()]=str(x.get('cik_str','')).zfill(10)
        return out
    except Exception: return {}

@st.cache_data(ttl=SPECIALIST_TTL,show_spinner=False)
def sec_companyfacts(ticker:str):
    cik=sec_ticker_map().get(str(ticker).upper())
    if not cik: return {'available':False,'provider':'SEC EDGAR','reason':'Ticker/CIK not found'}
    try:
        r=_session().get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',timeout=20); r.raise_for_status()
        return {'available':True,'provider':'SEC EDGAR','cik':cik,'data':r.json()}
    except Exception as e: return {'available':False,'provider':'SEC EDGAR','cik':cik,'reason':str(e)[:160]}

# Conservative mappings: only standardized XBRL facts that can be interpreted without prose parsing.
SEC_TAGS={
 'Deposits':['Deposits','DepositsCurrent','InterestBearingDeposits','NoninterestBearingDeposits'],
 'Loans_Net':['FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss','LoansAndLeasesReceivableNetReportedAmount'],
 'Allowance_Credit_Losses':['FinancingReceivableAllowanceForCreditLosses','AllowanceForLoanAndLeaseLosses'],
 'Common_Equity':['StockholdersEquity'],
 'Tangible_Assets':['Assets'],
 'Inventory':['InventoryNet'],
 'Receivables':['AccountsReceivableNetCurrent','AccountsNotesAndLoansReceivableNetCurrent'],
 'Current_Assets':['AssetsCurrent'],
 'Current_Liabilities':['LiabilitiesCurrent'],
 'Shares_Outstanding_SEC':['CommonStocksIncludingAdditionalPaidInCapitalMember','CommonStockSharesOutstanding'],
 'Capex':['PaymentsToAcquirePropertyPlantAndEquipment'],
 'SBC':['ShareBasedCompensation'],
 'Deferred_Revenue':['ContractWithCustomerLiabilityCurrent','DeferredRevenueCurrent'],
 'R_and_D':['ResearchAndDevelopmentExpense'],
 'Operating_Cashflow_SEC':['NetCashProvidedByUsedInOperatingActivities'],
 'Debt_Current':['ShortTermBorrowings','LongTermDebtCurrent'],
 'Debt_LongTerm':['LongTermDebtNoncurrent'],
 'Revenue_SEC':['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues'],
 'Net_Income_SEC':['NetIncomeLoss'],
 'Interest_Expense':['InterestExpenseNonOperating','InterestExpense'],
}

@st.cache_data(ttl=SPECIALIST_TTL,show_spinner=False)
def sec_specialist_snapshot(ticker:str):
    cf=sec_companyfacts(ticker)
    out={'available':False,'provider':'SEC EDGAR','SEC_Observed_Fields':[]}
    if not cf.get('available'): out['reason']=cf.get('reason','unavailable'); return out
    facts=cf['data'].get('facts',{}).get('us-gaap',{})
    for name,tags in SEC_TAGS.items():
        val,tag=_latest_fact(facts,tags)
        if pd.notna(val): out[name]=val; out['SEC_Observed_Fields'].append(name)
    # Derived accounting KPIs useful across specialist lenses.
    if pd.notna(out.get('Inventory')) and pd.notna(out.get('Revenue_SEC')) and out.get('Revenue_SEC'):
        out['Inventory_to_Revenue']=out['Inventory']/abs(out['Revenue_SEC'])
    if pd.notna(out.get('SBC')) and pd.notna(out.get('Revenue_SEC')) and out.get('Revenue_SEC'):
        out['SBC_to_Revenue']=out['SBC']/abs(out['Revenue_SEC'])
    if pd.notna(out.get('Capex')) and pd.notna(out.get('Revenue_SEC')) and out.get('Revenue_SEC'):
        out['Capex_to_Revenue']=out['Capex']/abs(out['Revenue_SEC'])
    if pd.notna(out.get('Allowance_Credit_Losses')) and pd.notna(out.get('Loans_Net')) and out.get('Loans_Net'):
        out['Credit_Loss_Allowance_to_Loans']=out['Allowance_Credit_Losses']/abs(out['Loans_Net'])
    out['available']=bool(out['SEC_Observed_Fields'])
    return out

@st.cache_data(ttl=SPECIALIST_TTL,show_spinner=False)
def clinicaltrials_company_snapshot(company:str):
    q=str(company or '').strip()
    if not q: return {'available':False,'provider':'ClinicalTrials.gov'}
    try:
        r=_session().get('https://clinicaltrials.gov/api/v2/studies',params={'query.spons':q,'pageSize':100,'format':'json'},timeout=20); r.raise_for_status()
        studies=r.json().get('studies',[]); phases={}; statuses={}; active=0
        for s in studies:
            p=s.get('protocolSection',{}); design=p.get('designModule',{}); status=p.get('statusModule',{}).get('overallStatus','UNKNOWN')
            for ph in design.get('phases',[]) or ['N/A']: phases[ph]=phases.get(ph,0)+1
            statuses[status]=statuses.get(status,0)+1
            if status in {'RECRUITING','ACTIVE_NOT_RECRUITING','ENROLLING_BY_INVITATION','NOT_YET_RECRUITING'}: active+=1
        return {'available':bool(studies),'provider':'ClinicalTrials.gov','Trial_Count':len(studies),'Active_Trials':active,'Trial_Phases':phases,'Trial_Statuses':statuses}
    except Exception as e: return {'available':False,'provider':'ClinicalTrials.gov','reason':str(e)[:160]}

@st.cache_data(ttl=SPECIALIST_TTL,show_spinner=False)
def openfda_company_snapshot(company:str):
    q=re.sub(r'[^A-Za-z0-9 .&-]','',str(company or '')).strip()
    if not q: return {'available':False,'provider':'openFDA'}
    try:
        r=_session().get('https://api.fda.gov/drug/label.json',params={'search':f'openfda.manufacturer_name:"{q}"','limit':1},timeout=15)
        if r.status_code==404: return {'available':False,'provider':'openFDA','reason':'No matching drug labels'}
        r.raise_for_status(); meta=r.json().get('meta',{}).get('results',{})
        return {'available':True,'provider':'openFDA','FDA_Drug_Label_Count':meta.get('total',np.nan)}
    except Exception as e: return {'available':False,'provider':'openFDA','reason':str(e)[:160]}
