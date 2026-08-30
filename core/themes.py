import pandas as pd

# Multi-theme weights deliberately sum to 1 per explicitly mapped ticker.
THEME_MAP={
    'NVDA':{'AI Compute':0.70,'Data Centers':0.30},
    'AMD':{'AI Compute':0.65,'Data Centers':0.35},
    'MU':{'AI Memory':0.75,'Data Centers':0.25},
    'LITE':{'Optical Networking':0.65,'Data Centers':0.35},
    'IREN':{'Crypto Infrastructure':0.45,'Data Centers':0.55},
    'MSFT':{'Cloud / AI Platforms':0.70,'Enterprise Software':0.30},
    'GOOGL':{'Digital Advertising':0.55,'Cloud / AI Platforms':0.45},
    'META':{'Digital Advertising':0.65,'AI Platforms':0.35},
    'AMZN':{'Consumer / E-commerce':0.50,'Cloud / AI Platforms':0.50},
    'GEV':{'Power / Electrification':0.70,'Grid Infrastructure':0.30},
    'VST':{'Power Generation':0.75,'AI Power Demand':0.25},
    'FCX':{'Copper / Electrification':1.00},
    'MA':{'Payments':1.00},'V':{'Payments':1.00},
    'PGR':{'Insurance':1.00},
    'LLY':{'Healthcare / Pharma':1.00},'ISRG':{'Healthcare / MedTech':1.00},
    'TMUS':{'Telecom':1.00},
    'UBER':{'Mobility / Consumer':1.00},
    'QSR':{'Restaurants / Consumer':1.00},'CAVA':{'Restaurants / Consumer':1.00},
    'PHM':{'Housing':1.00},
    'BTC-USD':{'Crypto':1.00},'ETH-USD':{'Crypto':1.00},
    'WMT':{'Consumer Staples':1.00},'PEP':{'Consumer Staples':1.00},'KO':{'Consumer Staples':1.00},
    'ETN':{'Power / Electrification':0.65,'Industrial Automation':0.35},
}

SECTOR_THEME={
    'Technology':'Technology','Information Technology':'Technology','Industrials':'Industrials',
    'Financials':'Financials','Health Care':'Healthcare','Healthcare':'Healthcare',
    'Consumer Discretionary':'Consumer Discretionary','Consumer Staples':'Consumer Staples',
    'Communication Services':'Communication Services','Utilities':'Utilities','Energy':'Energy',
    'Materials':'Materials','Real Estate':'Real Estate',
}


def ticker_themes(ticker, sector='Unknown'):
    ticker=str(ticker).upper().strip()
    if ticker in THEME_MAP:
        return THEME_MAP[ticker]
    if ticker.endswith('-USD'):
        return {'Crypto':1.0}
    return {SECTOR_THEME.get(str(sector),str(sector) if sector else 'Other'):1.0}


def theme_exposure(detail):
    if detail is None or detail.empty:
        return pd.DataFrame(columns=['Theme','Weight %'])
    rows=[]
    for _,r in detail.iterrows():
        weight=float(r.get('Weight %',0) or 0)
        for theme,share in ticker_themes(r.get('Ticker',''),r.get('Sector','Unknown')).items():
            rows.append({'Theme':theme,'Weight %':weight*float(share),'Ticker':r.get('Ticker')})
    if not rows:
        return pd.DataFrame(columns=['Theme','Weight %'])
    return (pd.DataFrame(rows).groupby('Theme',as_index=False)['Weight %'].sum().sort_values('Weight %',ascending=False))
