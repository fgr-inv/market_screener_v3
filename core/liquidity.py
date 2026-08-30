import numpy as np
import pandas as pd
from core.utils import clamp


def liquidity_score(raw):
    if raw is None or raw.empty:
        return {'Liquidity_Score': 0, 'ADV20_$': np.nan, 'Median_Dollar_Volume20_$': np.nan, 'ATR_%': np.nan, 'Liquidity_Label': 'NO DATA'}
    df = raw.copy().dropna(subset=['Close'])
    dollar = df['Close'] * df.get('Volume', 0)
    adv = dollar.tail(20).mean() if len(dollar) else np.nan
    med = dollar.tail(20).median() if len(dollar) else np.nan
    ret = df['Close'].pct_change().dropna()
    atr_proxy = ret.abs().tail(20).mean() * 100 if len(ret) else np.nan
    score = 30
    if pd.notna(adv):
        score += 55 if adv >= 500_000_000 else 45 if adv >= 100_000_000 else 35 if adv >= 25_000_000 else 20 if adv >= 5_000_000 else 5
    if pd.notna(atr_proxy):
        score += 10 if atr_proxy <= 2 else 5 if atr_proxy <= 4 else -5 if atr_proxy >= 8 else 0
    score = int(clamp(score))
    label = 'EXCELLENT' if score >= 85 else 'GOOD' if score >= 70 else 'FAIR' if score >= 50 else 'POOR'
    return {'Liquidity_Score': score, 'ADV20_$': adv, 'Median_Dollar_Volume20_$': med, 'ATR_%': atr_proxy, 'Liquidity_Label': label}
