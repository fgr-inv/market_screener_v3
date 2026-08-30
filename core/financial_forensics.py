from __future__ import annotations
import math
import numpy as np
import pandas as pd
from core.utils import clamp

def _n(x):
    try:
        v=float(x); return v if math.isfinite(v) else np.nan
    except Exception:return np.nan

def financial_forensics(f:dict):
    f=f or {}; ni=_n(f.get('Net_Income_SEC')); ocf=_n(f.get('Operating_Cashflow')); fcf=_n(f.get('FCF')); rev=_n(f.get('Revenue')); sbc=_n(f.get('SBC')); invr=_n(f.get('Inventory_to_Revenue'))
    debt=_n(f.get('Total_Debt')); cash=_n(f.get('Total_Cash')); ebitda=_n(f.get('EBITDA')); interest=_n(f.get('Interest_Expense')); cr=_n(f.get('Current_Ratio')); quick=_n(f.get('Quick_Ratio')); roic=_n(f.get('ROIC'))
    quality=50; stress=50; alloc=50; evidence=[]
    if pd.notna(ni) and ni!=0 and pd.notna(ocf):
        conv=ocf/ni; quality += 15 if conv>=1 else 5 if conv>=.8 else -15; evidence.append(f'OCF/net income {conv:.2f}x')
    if pd.notna(rev) and rev and pd.notna(fcf):
        fm=fcf/abs(rev); quality += 12 if fm>=.15 else 6 if fm>=.07 else -8 if fm<0 else 0
    if pd.notna(sbc) and pd.notna(rev) and rev:
        ratio=sbc/abs(rev); quality += 6 if ratio<.03 else -8 if ratio>.10 else 0; evidence.append(f'SBC/revenue {ratio:.1%}')
    if pd.notna(invr): quality += -8 if invr>.35 else 3
    netdebt=(debt if pd.notna(debt) else 0)-(cash if pd.notna(cash) else 0)
    nd_ebitda=netdebt/ebitda if pd.notna(ebitda) and ebitda>0 else np.nan
    if pd.notna(nd_ebitda): stress += -18 if nd_ebitda>4 else -8 if nd_ebitda>2.5 else 12 if nd_ebitda<1 else 3
    if pd.notna(cr): stress += 8 if cr>=1.5 else -10 if cr<1 else 0
    if pd.notna(quick): stress += 5 if quick>=1 else -5 if quick<.7 else 0
    coverage=sum(pd.notna(x) for x in [ni,ocf,fcf,rev,sbc,invr,debt,cash,ebitda,cr,quick])/11*100
    if pd.notna(roic): alloc += 18 if roic>=.15 else 8 if roic>=.08 else -8 if roic<.04 else 0
    if pd.notna(fcf) and fcf>0: alloc += 8
    payout=_n(f.get('Payout_Ratio')); div=_n(f.get('Dividend_Yield'))
    if pd.notna(payout): alloc += 5 if 0<=payout<=.7 else -5 if payout>1 else 0
    return {'Earnings_Quality_Score':int(clamp(quality)),'Financial_Resilience_Score':int(clamp(stress)),'Capital_Allocation_Score':int(clamp(alloc)),
            'Net_Debt_EBITDA':nd_ebitda,'Interest_Coverage':(ebitda/interest if pd.notna(ebitda) and pd.notna(interest) and interest>0 else np.nan),
            'Forensics_Coverage_%':round(coverage),'Evidence':evidence,
            'Note':'Scores use observed accounting/cash-flow fields only. Missing receivables, maturities, covenants or share-count history reduce coverage rather than being imputed.'}
