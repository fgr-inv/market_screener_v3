import numpy as np
import pandas as pd


def factor_correlation(df, columns=None, min_obs=20):
    if df is None or df.empty:
        return pd.DataFrame()
    columns=columns or [
        'Technical_Score','Trend_Score','Entry_Score','RS_Percentile','Sector_Score',
        'Macro_Fit','Quality_Score','Revision_Score','Valuation_Score','Risk_Score'
    ]
    cols=[c for c in columns if c in df.columns and pd.to_numeric(df[c],errors='coerce').notna().sum()>=min_obs]
    if len(cols)<2:
        return pd.DataFrame()
    return df[cols].apply(pd.to_numeric,errors='coerce').corr()


def redundant_pairs(corr, threshold=.80):
    if corr is None or corr.empty:
        return pd.DataFrame(columns=['Factor A','Factor B','Correlation'])
    rows=[]; cols=list(corr.columns)
    for i in range(len(cols)):
        for j in range(i+1,len(cols)):
            v=corr.iloc[i,j]
            if pd.notna(v) and abs(float(v))>=threshold:
                rows.append({'Factor A':cols[i],'Factor B':cols[j],'Correlation':round(float(v),3)})
    return pd.DataFrame(rows).sort_values('Correlation',key=lambda s:s.abs(),ascending=False) if rows else pd.DataFrame(columns=['Factor A','Factor B','Correlation'])
