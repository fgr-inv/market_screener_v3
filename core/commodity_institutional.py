from __future__ import annotations
import numpy as np
import pandas as pd
from core.commodity_data import commodity_deep_context
from core.commodity_curve import curve_metrics
from core.utils import clamp

ROOT_MAP={'CL=F':'CL','BZ=F':'BZ','NG=F':'NG','GC=F':'GC','SI=F':'SI','HG=F':'HG','ZC=F':'ZC','ZW=F':'ZW','ZS=F':'ZS'}

def commodity_institutional_snapshot(ticker,eia_key=''):
    d=commodity_deep_context(ticker,eia_key=eia_key); curve=curve_metrics(ROOT_MAP.get(str(ticker).upper(),str(ticker).upper()))
    score=float(d.get('Deep_Data_Score',50)); structure=curve.get('Term_Structure','N/D'); carry=curve.get('Annualized_Carry_%',np.nan)
    if structure=='BACKWARDATION': score+=8
    elif structure=='CONTANGO': score-=5
    cot=d.get('COT_Signal','N/D')
    return {'Physical_Market_Score':int(clamp(score)),'Inventory_Signal':d.get('Inventory_Signal','N/D'),'COT_Signal':cot,
            'Term_Structure':structure,'Annualized_Carry_%':carry,'Curve_Available':bool(curve.get('available')),'Raw_Context':d,
            'Coverage_Note':'Oil products use EIA inventories when configured; CFTC positioning is public. Metals/agriculture physical inventory/curve depth remains limited when no reliable free feed is available.'}
