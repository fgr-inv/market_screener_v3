import pandas as pd
from core.utils import clamp


def confidence_score(row, fundamentals=None, macro=None):
    score=100
    reasons=[]
    required=['Price','Trend_Score','Entry_Score','Risk_Score','RR']
    missing=sum(1 for k in required if pd.isna(row.get(k)))
    score-=missing*10
    if pd.isna(row.get('RS_63d_%')):
        score-=8; reasons.append('RS incompleto')
    if pd.isna(row.get('Rel_Volume')):
        score-=5; reasons.append('volumen relativo incompleto')
    if fundamentals is not None:
        keys=['Revenue_Growth','Earnings_Growth','Profit_Margin','ROE','Forward_PE','FCF']
        miss=sum(1 for k in keys if pd.isna(fundamentals.get(k)))
        score-=min(25, miss*4)
        if miss: reasons.append(f'{miss} fundamentales faltantes')
    if macro is not None:
        q=macro.get('Data_Quality_%',100)
        if pd.notna(q): score-=max(0,(100-float(q))*.15)
    return int(clamp(round(score))), reasons
