from __future__ import annotations
import math
import numpy as np
import pandas as pd


def _n(x):
    try:
        v=float(x); return v if math.isfinite(v) else np.nan
    except Exception: return np.nan


def _pv_fcf(fcf0,g,wacc,tg,years=5):
    if fcf0<=0 or wacc<=tg: return np.nan
    pv=0.0; f=fcf0
    for y in range(1,years+1):
        f*=1+g; pv += f/((1+wacc)**y)
    tv=f*(1+tg)/(wacc-tg)
    return pv + tv/((1+wacc)**years)


def reverse_dcf_growth(fund:dict, wacc=.10, terminal_growth=.025):
    fcf=_n(fund.get('FCF')); ev=_n(fund.get('Enterprise_Value'))
    if pd.isna(fcf) or pd.isna(ev) or fcf<=0 or ev<=0 or wacc<=terminal_growth:
        return {'available':False,'Implied_FCF_Growth_%':np.nan,'WACC_%':wacc*100,'Terminal_Growth_%':terminal_growth*100}
    lo,hi=-.30,.80
    flo=_pv_fcf(fcf,lo,wacc,terminal_growth)-ev; fhi=_pv_fcf(fcf,hi,wacc,terminal_growth)-ev
    if np.sign(flo)==np.sign(fhi):
        return {'available':False,'Implied_FCF_Growth_%':np.nan,'WACC_%':wacc*100,'Terminal_Growth_%':terminal_growth*100}
    for _ in range(70):
        mid=(lo+hi)/2; fm=_pv_fcf(fcf,mid,wacc,terminal_growth)-ev
        if np.sign(fm)==np.sign(flo): lo=mid; flo=fm
        else: hi=mid
    g=(lo+hi)/2
    return {'available':True,'Implied_FCF_Growth_%':round(g*100,1),'WACC_%':wacc*100,'Terminal_Growth_%':terminal_growth*100,
            'Interpretation':'Growth the current enterprise value roughly requires under the stated FCF/WACC assumptions.'}


def dcf_scenarios(fund:dict, model_key='generic'):
    fcf=_n(fund.get('FCF')); debt=_n(fund.get('Total_Debt')); cash=_n(fund.get('Total_Cash')); mc=_n(fund.get('Market_Cap'))
    if pd.isna(fcf) or fcf<=0 or pd.isna(mc) or mc<=0:
        return {'available':False,'Coverage_%':0,'Scenarios':pd.DataFrame(),'Fair_Value_Mid':np.nan}
    rg=_n(fund.get('Revenue_Growth')); eg=_n(fund.get('Earnings_Growth'))
    growth_candidates=[x for x in [rg,eg] if pd.notna(x)]
    base_g=float(np.clip(np.nanmean(growth_candidates) if growth_candidates else .08,-.05,.30))
    cyclical={'memory','ep','copper_miner','gold_miner','steel','refining'}
    wacc=.11 if model_key in cyclical else .105 if model_key in {'saas','cybersecurity','ai_accelerators','biotech'} else .09
    tg=.025
    net_debt=(debt if pd.notna(debt) else 0)-(cash if pd.notna(cash) else 0)
    rows=[]
    for name,g_delta,w_delta,p in [('Bear',-.08,.02,.25),('Base',0,0,.50),('Bull',.07,-.01,.25)]:
        g=float(np.clip(base_g+g_delta,-.15,.40)); ww=max(tg+.02,wacc+w_delta); ev=_pv_fcf(fcf,g,ww,tg)
        eq=max(0,ev-net_debt) if pd.notna(ev) else np.nan
        rows.append({'Scenario':name,'FCF_Growth_%':round(g*100,1),'WACC_%':round(ww*100,1),'Equity_Value':eq,'Vs_Market_Cap_%':round((eq/mc-1)*100,1) if pd.notna(eq) else np.nan,'Probability_%':p*100})
    df=pd.DataFrame(rows); fair=float((df['Equity_Value']*df['Probability_%']/100).sum())
    return {'available':True,'Coverage_%':round(100*sum(pd.notna(x) for x in [fcf,mc,debt,cash,rg,eg])/6),
            'Scenarios':df,'Fair_Value_Mid':fair,'Fair_Value_Upside_%':round((fair/mc-1)*100,1),'Method':'5-year FCF DCF with explicit scenario assumptions; enterprise-to-equity bridge uses observed net debt.'}


def valuation_workstation(fund:dict, model_key='generic', peer_rank=np.nan):
    fund=fund or {}
    rev=reverse_dcf_growth(fund)
    dcf=dcf_scenarios(fund,model_key)
    pe=_n(fund.get('Forward_PE')); eve=_n(fund.get('EV_EBITDA')); fcfy=_n(fund.get('FCF_Yield')); ps=_n(fund.get('Price_to_Sales')); pb=_n(fund.get('Price_to_Book'))
    observed=sum(pd.notna(x) for x in [pe,eve,fcfy,ps,pb])
    return {'Current_Multiples':{'Forward_PE':pe,'EV_EBITDA':eve,'FCF_Yield_%':fcfy*100 if pd.notna(fcfy) and abs(fcfy)<1 else fcfy,'Price_to_Sales':ps,'Price_to_Book':pb},
            'Reverse_DCF':rev,'DCF':dcf,'Peer_Rank_Score':peer_rank,'Historical_Valuation_Coverage_%':0,
            'Historical_Valuation_Note':'True historical multiple percentiles require point-in-time historical fundamentals. V9.0 does not backfill them from current EPS/FCF because that would create look-ahead bias.',
            'Valuation_Evidence_Coverage_%':round(observed/5*100)}
