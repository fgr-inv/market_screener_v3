import numpy as np
import pandas as pd
from core.utils import clamp


def available_weighted_score(values, weights, neutral_if_empty=np.nan):
    """Score only from available factors; missing data is never silently treated as 0/50."""
    used=[]
    for name,w in weights.items():
        v=values.get(name,np.nan)
        if v is None or pd.isna(v):
            continue
        used.append((name,float(v),float(w)))
    total=sum(w for _,_,w in used)
    if not used or total<=0:
        return neutral_if_empty,0.0,[]
    score=sum(v*w for _,v,w in used)/total
    coverage=sum(w for _,_,w in used)/max(sum(float(w) for w in weights.values()),1e-12)*100
    return float(clamp(score)),float(clamp(coverage)),[n for n,_,_ in used]
