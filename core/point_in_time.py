from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
PIT_DIR=ROOT/'data'/'premium'/'point_in_time'
PIT_DIR.mkdir(parents=True,exist_ok=True)


def load_constituent_history(index_name='SP500'):
    path=PIT_DIR/f'{index_name}_constituents.csv'
    if not path.exists(): return pd.DataFrame()
    df=pd.read_csv(path)
    for c in ['start_date','end_date']:
        if c in df.columns: df[c]=pd.to_datetime(df[c],errors='coerce')
    return df


def constituents_on(date,index_name='SP500'):
    df=load_constituent_history(index_name)
    if df.empty: return []
    d=pd.Timestamp(date)
    mask=(df['start_date']<=d) & (df['end_date'].isna() | (df['end_date']>=d))
    return df.loc[mask,'ticker'].astype(str).str.upper().tolist()


def point_in_time_status(index_name='SP500'):
    df=load_constituent_history(index_name)
    return {
        'available':not df.empty,
        'rows':len(df),
        'note':'Point-in-time constituent history loaded.' if not df.empty else 'No historical constituent file. Backtests may have survivorship bias.'
    }


def premium_data_contracts():
    return {
        'SP500_constituents.csv':['ticker','start_date','end_date'],
        'historical_revisions.csv':['ticker','asof_date','fiscal_period','eps_estimate','revenue_estimate'],
        'historical_short_interest.csv':['ticker','asof_date','short_interest','days_to_cover','borrow_cost'],
        'historical_options.csv':['ticker','asof_date','expiration','strike','type','iv','oi','volume','delta','gamma'],
        'commodity_curve.csv':['root','asof_date','contract','expiry','price','open_interest'],
    }

# V10 zero-cost point-in-time contracts. These files can be built prospectively
# from free/public providers; unavailable history must remain missing.
def zero_cost_point_in_time_contracts():
    return {
        'daily_research_snapshots.jsonl':['asset','asof','payload','sources'],
        'historical_fundamentals.csv':['ticker','asof_date','fiscal_period','metric','value','source'],
        'historical_estimates.csv':['ticker','asof_date','fiscal_period','metric','value','source'],
        'macro_vintages.csv':['series_id','asof_date','observation_date','value','source'],
        'event_history.csv':['asset','event_date','event_type','actual','consensus','surprise','source'],
        'etf_holdings_history.csv':['ticker','asof_date','holding','weight','source'],
        'futures_curve_history.csv':['root','asof_date','contract','expiry','price','open_interest','source'],
        'positioning_history.csv':['asset','asof_date','category','net','open_interest','source'],
        'institutional_holdings_13f.csv':['manager','ticker','asof_date','shares','value','source'],
        'insider_transactions_form4.csv':['ticker','insider','role','transaction_date','code','shares','price','source'],
        'fund_holdings_nport.csv':['fund','ticker','asof_date','holding','weight','source'],
        'short_market_history.csv':['ticker','asof_date','short_sale_volume','short_interest','days_to_cover','source'],
        'crypto_network_history.csv':['asset','asof_date','metric','value','source'],
        'stablecoin_liquidity_history.csv':['asset','asof_date','market_cap','chain','source'],
        'tokenomics_history.csv':['asset','asof_date','circulating_supply','total_supply','fdv','market_cap','source'],
        'commodity_physical_history.csv':['root','asof_date','metric','value','source'],
        'agriculture_history.csv':['commodity','asof_date','metric','value','source'],
        'weather_history.csv':['region','asof_date','metric','value','source'],
        'fixed_income_history.csv':['instrument','asof_date','yield','spread','duration','source'],
        'fx_macro_history.csv':['pair','asof_date','metric','value','source'],
        'news_event_history.csv':['asset','event_date','event_type','attention','source'],
        'model_validation_history.csv':['asset','asof_date','score_name','score','horizon','forward_return','regime'],
        'decision_attribution_history.csv':['asset','asof_date','component','score','realized_return','contribution_proxy'],
    }
