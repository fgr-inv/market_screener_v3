import numpy as np
import pandas as pd
from core.model_registry import get_active_model
from core.asset_models import normalize_asset_type
from core.opportunity import asset_opportunity_components


def explain_opportunity(row):
    typ=normalize_asset_type(row.get('Asset_Type','Acción'))
    if typ!='Acción':
        vals,weights=asset_opportunity_components(row)
        labels={'trend':'Trend','entry':'Entry','risk':'Risk quality','context':'Asset/Macro Context','relative_strength':'Relative Strength','cycle':'Weekly Cycle'}
        available=[(labels.get(k,k),float(v),float(weights[k])) for k,v in vals.items() if k in weights and v is not None and not pd.isna(v)]
        denom=sum(w for _,_,w in available) or 1
        parts=[(label,score*w/denom) for label,score,w in available]
    else:
        model=get_active_model(); w=model.get('weights',{})
        defaults={'quality':.18,'trend':.16,'entry':.22,'relative_strength':.12,'sector':.08,'macro':.08,'revisions':.10,'valuation':.06}
        items=[
            ('Quality','quality',row.get('Quality_Score',np.nan)),('Trend','trend',row.get('Trend_Score',np.nan)),
            ('Entry','entry',row.get('Entry_Score',np.nan)),('Relative Strength','relative_strength',row.get('RS_Percentile',np.nan)),
            ('Sector','sector',row.get('Sector_Score',np.nan)),('Macro','macro',row.get('Macro_Fit',np.nan)),
            ('Revisions','revisions',row.get('Revision_Score',np.nan)),('Valuation','valuation',row.get('Valuation_Score',np.nan)),
        ]
        available=[(label,key,float(v),float(w.get(key,defaults[key]))) for label,key,v in items if v is not None and not pd.isna(v)]
        denom=sum(x[3] for x in available) or 1
        parts=[(label,score*weight/denom) for label,key,score,weight in available]
    penalty=0
    rr=row.get('RR',np.nan)
    if pd.notna(rr):
        rr=float(rr); penalty += 4 if rr>=2.5 else -14 if rr<1.25 else -9 if rr<1.5 else -5 if rr<2 else 0
    risk=str(row.get('Event_Risk','')).upper(); penalty += -15 if risk=='HIGH' else -6 if risk=='ELEVATED' else 0
    if bool(row.get('Scan_Extended_Trim',False)): penalty-=10
    if float(row.get('Model_Coverage_%',100) or 0)<60: penalty-=8
    return parts,penalty
