import numpy as np
import pandas as pd


def _max_drawdown(series):
    if series is None or len(series)<2: return np.nan
    wealth=(1+series.fillna(0)).cumprod(); dd=wealth/wealth.cummax()-1
    return float(dd.min()*100)


def portfolio_risk(positions, price_map, benchmark='SPY'):
    if positions is None or positions.empty:
        return {},pd.DataFrame(),pd.DataFrame()
    vals=[]; returns={}
    for _,p in positions.iterrows():
        t=str(p['ticker']).upper(); raw=price_map.get(t)
        if raw is None or raw.empty: continue
        close=raw['Close'].dropna()
        if close.empty: continue
        price=float(close.iloc[-1]); value=float(p['quantity'])*price
        vals.append({'Ticker':t,'Value':value,'Price':price,'Quantity':p['quantity'],'Sector':p.get('sector','Unknown')})
        returns[t]=close.pct_change().dropna()
    detail=pd.DataFrame(vals)
    if detail.empty: return {},detail,pd.DataFrame()
    total=detail['Value'].sum(); detail['Weight %']=detail['Value']/total*100
    ret_df=pd.concat(returns,axis=1).dropna(how='all') if returns else pd.DataFrame()
    corr=ret_df.corr() if not ret_df.empty else pd.DataFrame()
    weights=detail.set_index('Ticker')['Value']/total
    common=[t for t in weights.index if t in ret_df.columns]
    port=pd.Series(dtype=float); rc_pct=pd.Series(dtype=float); standalone_vol=pd.Series(dtype=float)
    if common:
        aligned=ret_df[common].dropna()
        w=weights[common]/weights[common].sum()
        port=aligned.mul(w,axis=1).sum(axis=1)
        if len(aligned)>20:
            cov=aligned.cov()*252
            sigma2=float(w.values @ cov.values @ w.values)
            if sigma2>0:
                marginal=cov.values @ w.values
                component=w.values*marginal
                rc_pct=pd.Series(component/sigma2*100,index=common)
            standalone_vol=aligned.std()*np.sqrt(252)*100
    ann_vol=float(port.std()*np.sqrt(252)*100) if len(port)>10 else np.nan
    var95=float(-np.percentile(port,5)*total) if len(port)>20 else np.nan
    cvar95=np.nan
    if len(port)>20:
        cutoff=np.percentile(port,5); tail=port[port<=cutoff]
        if len(tail): cvar95=float(-tail.mean()*total)
    max_weight=float(detail['Weight %'].max())
    sector_conc=detail.groupby('Sector')['Value'].sum()/total*100
    max_sector=float(sector_conc.max()) if len(sector_conc) else np.nan
    effective_n=float(1/(weights.pow(2).sum())) if len(weights) else np.nan
    beta=np.nan
    braw=price_map.get(benchmark)
    if braw is not None and not braw.empty and len(port)>10:
        b=braw['Close'].pct_change().dropna().rename('b'); x=pd.concat([port.rename('p'),b],axis=1).dropna()
        if len(x)>10 and x['b'].var()>0: beta=float(x.cov().loc['p','b']/x['b'].var())
    detail['Standalone Vol %']=detail['Ticker'].map(standalone_vol).astype(float)
    detail['Risk Contribution %']=detail['Ticker'].map(rc_pct).fillna(0).astype(float)
    detail['Risk / Weight']=np.where(detail['Weight %']>0,detail['Risk Contribution %']/detail['Weight %'],np.nan)
    summary={
        'Market Value':total,'Annualized Vol %':ann_vol,'1d VaR 95 $':var95,'1d CVaR 95 $':cvar95,
        'Historical Max Drawdown %':_max_drawdown(port),'Portfolio Beta':beta,'Largest Position %':max_weight,
        'Largest Sector %':max_sector,'Effective # Positions':effective_n,
    }
    return summary,detail,corr


def high_correlation_pairs(corr, threshold=.80):
    if corr is None or corr.empty: return pd.DataFrame(columns=['Asset A','Asset B','Correlation'])
    rows=[]; cols=list(corr.columns)
    for i in range(len(cols)):
        for j in range(i+1,len(cols)):
            v=corr.iloc[i,j]
            if pd.notna(v) and float(v)>=threshold:
                rows.append({'Asset A':cols[i],'Asset B':cols[j],'Correlation':round(float(v),3)})
    return pd.DataFrame(rows).sort_values('Correlation',ascending=False) if rows else pd.DataFrame(columns=['Asset A','Asset B','Correlation'])
