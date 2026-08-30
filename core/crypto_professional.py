from __future__ import annotations

"""Asset-specific professional crypto research using zero-cost/public data.

The module intentionally separates Bitcoin, Ethereum, L1/L2, DeFi, stablecoins
and speculative tokens. Missing institutional/on-chain fields stay missing rather
than being inferred from price.
"""

import math
import numpy as np
import pandas as pd
import requests
import streamlit as st

from core.free_market_providers import coingecko_headers, free_crypto_derivatives_snapshot
from core.utils import clamp

CG_IDS = {
    'BTC':'bitcoin','ETH':'ethereum','SOL':'solana','AVAX':'avalanche-2','ADA':'cardano','SUI':'sui',
    'APT':'aptos','NEAR':'near','DOT':'polkadot','ATOM':'cosmos','ARB':'arbitrum','OP':'optimism',
    'LINK':'chainlink','UNI':'uniswap','AAVE':'aave','MKR':'maker','LDO':'lido-dao','CRV':'curve-dao-token',
    'USDT':'tether','USDC':'usd-coin','DAI':'dai','PYUSD':'paypal-usd','DOGE':'dogecoin','SHIB':'shiba-inu',
    'PEPE':'pepe','BONK':'bonk','WIF':'dogwifcoin','XRP':'ripple','BNB':'binancecoin','TRX':'tron',
}
L1_L2 = {'SOL','AVAX','ADA','SUI','APT','NEAR','DOT','ATOM','ARB','OP','BNB','TRX'}
DEFI = {'UNI','AAVE','MKR','LDO','CRV'}
STABLE = {'USDT','USDC','DAI','PYUSD'}
SPECULATIVE = {'DOGE','SHIB','PEPE','BONK','WIF'}


def _coin(ticker: str) -> str:
    return str(ticker).upper().replace('-USD','').replace('USDT','').strip()

def crypto_model_type(ticker: str) -> str:
    c=_coin(ticker)
    if c=='BTC': return 'Bitcoin'
    if c=='ETH': return 'Ethereum'
    if c in STABLE: return 'Stablecoin'
    if c in DEFI: return 'DeFi'
    if c in L1_L2: return 'L1/L2'
    if c in SPECULATIVE: return 'Speculative Token'
    return 'General Token'

def _f(v):
    try:
        x=float(v); return x if math.isfinite(x) else np.nan
    except Exception: return np.nan

def _get(url, params=None, timeout=9):
    r=requests.get(url,params=params,headers=coingecko_headers(),timeout=timeout); r.raise_for_status(); return r.json()

@st.cache_data(ttl=900, show_spinner=False)
def coingecko_coin_snapshot(ticker: str) -> dict:
    c=_coin(ticker); cid=CG_IDS.get(c)
    out={'Coin':c,'CoinGecko_ID':cid,'Status':'Unavailable'}
    if not cid: return out
    try:
        d=_get(f'https://api.coingecko.com/api/v3/coins/{cid}', {'localization':'false','tickers':'false','market_data':'true','community_data':'false','developer_data':'true','sparkline':'false'})
        m=d.get('market_data',{}); dev=d.get('developer_data',{})
        out.update({
            'Market_Cap_$':_f(m.get('market_cap',{}).get('usd')),
            'FDV_$':_f(m.get('fully_diluted_valuation',{}).get('usd')),
            'Circulating_Supply':_f(m.get('circulating_supply')),
            'Total_Supply':_f(m.get('total_supply')),
            'Max_Supply':_f(m.get('max_supply')),
            '24h_Volume_$':_f(m.get('total_volume',{}).get('usd')),
            'ATH_Drawdown_%':_f(m.get('ath_change_percentage',{}).get('usd')),
            'Market_Cap_Rank':_f(d.get('market_cap_rank')),
            'GitHub_Stars':_f(dev.get('stars')),
            'Commits_4w':_f(dev.get('commit_count_4_weeks')),
            'Status':'OK'
        })
        mc,fdv=out['Market_Cap_$'],out['FDV_$']
        out['FDV_to_MCap']=fdv/mc if pd.notna(fdv) and pd.notna(mc) and mc>0 else np.nan
        circ,total=out['Circulating_Supply'],out['Total_Supply']
        out['Circulating_%_of_Total']=100*circ/total if pd.notna(circ) and pd.notna(total) and total>0 else np.nan
    except Exception as exc: out['Reason']=str(exc)[:160]
    return out

@st.cache_data(ttl=1800, show_spinner=False)
def bitcoin_network_snapshot() -> dict:
    charts={
        'Hash_Rate':'hash-rate','Difficulty':'difficulty','Miner_Revenue_USD':'miners-revenue',
        'Fees_USD':'transaction-fees-usd','Transactions_Per_Day':'n-transactions',
        'Active_Addresses':'n-unique-addresses','Mempool_Size_Bytes':'mempool-size',
        'Estimated_Tx_Volume_USD':'estimated-transaction-volume-usd',
    }
    out={'Status':'Unavailable'}; ok=0
    for k,chart in charts.items():
        try:
            d=requests.get(f'https://api.blockchain.info/charts/{chart}',params={'timespan':'3days','format':'json'},timeout=8).json()
            vals=d.get('values',[])
            if vals: out[k]=_f(vals[-1].get('y')); ok+=1
        except Exception: out[k]=np.nan
    try:
        stats=requests.get('https://api.blockchain.info/stats',timeout=8).json()
        out['BTC_Mined_24h']=_f(stats.get('n_btc_mined'))/1e8 if _f(stats.get('n_btc_mined'))==_f(stats.get('n_btc_mined')) else np.nan
        out['Blocks_Mined_24h']=_f(stats.get('n_blocks_mined'))
        out['Minutes_Between_Blocks']=_f(stats.get('minutes_between_blocks'))
        out['Total_BTC']=_f(stats.get('total_btc'))/1e8 if pd.notna(_f(stats.get('total_btc'))) else np.nan
        ok+=1
    except Exception: pass
    fees,rev=out.get('Fees_USD'),out.get('Miner_Revenue_USD')
    out['Fees_%_Miner_Revenue']=100*fees/rev if pd.notna(fees) and pd.notna(rev) and rev>0 else np.nan
    total=out.get('Total_BTC'); out['Supply_%_of_21M']=100*total/21_000_000 if pd.notna(total) else np.nan
    out['Status']='OK' if ok else 'Unavailable'
    return out

@st.cache_data(ttl=1800, show_spinner=False)
def defillama_chain_snapshot(chain: str) -> dict:
    out={'Chain':chain,'TVL_$':np.nan,'Status':'Unavailable'}
    try:
        rows=requests.get('https://api.llama.fi/v2/chains',timeout=10).json()
        aliases={'ETH':'Ethereum','SOL':'Solana','AVAX':'Avalanche','ARB':'Arbitrum','OP':'Optimism','SUI':'Sui','APT':'Aptos','TRX':'Tron','BNB':'BSC'}
        target=aliases.get(chain,chain)
        x=next((r for r in rows if str(r.get('name','')).lower()==target.lower()),None)
        if x: out.update({'TVL_$':_f(x.get('tvl')),'Chain_Token_Symbol':x.get('tokenSymbol'),'Status':'OK'})
    except Exception as exc: out['Reason']=str(exc)[:160]
    return out

@st.cache_data(ttl=1800, show_spinner=False)
def defillama_protocol_snapshot(ticker: str) -> dict:
    c=_coin(ticker); out={'Status':'Unavailable','Protocol_TVL_$':np.nan}
    slug={'UNI':'uniswap','AAVE':'aave','MKR':'makerdao','LDO':'lido','CRV':'curve'}.get(c)
    if not slug: return out
    try:
        d=requests.get(f'https://api.llama.fi/protocol/{slug}',timeout=10).json()
        out.update({'Protocol':d.get('name',slug),'Protocol_TVL_$':_f(d.get('tvl')),'Category':d.get('category'),'Status':'OK'})
    except Exception as exc: out['Reason']=str(exc)[:160]
    return out

def _score_tokenomics(cg: dict) -> float:
    s=50; ratio=cg.get('FDV_to_MCap'); circ=cg.get('Circulating_%_of_Total'); vol=cg.get('24h_Volume_$'); mc=cg.get('Market_Cap_$')
    if pd.notna(ratio): s += 12 if ratio<=1.15 else 4 if ratio<=1.5 else -10 if ratio>2.5 else -3
    if pd.notna(circ): s += 10 if circ>=85 else 4 if circ>=65 else -10 if circ<35 else 0
    if pd.notna(vol) and pd.notna(mc) and mc>0:
        turn=vol/mc; s += 6 if .02<=turn<=.35 else -5 if turn<.005 else 0
    return float(clamp(s))

def professional_crypto_snapshot(ticker: str) -> dict:
    """Return model-specific crypto fundamentals/context and transparent coverage."""
    c=_coin(ticker); model=crypto_model_type(c); cg=coingecko_coin_snapshot(c)
    deriv=free_crypto_derivatives_snapshot(c) if c not in STABLE else {}
    deep={'Crypto_Model':model, **cg}
    scores={}; missing=[]

    if model=='Bitcoin':
        net=bitcoin_network_snapshot(); deep.update(net)
        # Network health: activity + miner fee/revenue balance + issuance visibility. Hash-rate level itself is not scored without history.
        ns=50
        if pd.notna(net.get('Transactions_Per_Day')): ns+=8
        if pd.notna(net.get('Active_Addresses')): ns+=8
        if pd.notna(net.get('BTC_Mined_24h')): ns+=6
        if pd.notna(net.get('Fees_%_Miner_Revenue')): ns+=6 if 1<=net['Fees_%_Miner_Revenue']<=35 else -3
        scores['Network_Score']=int(clamp(ns))
        scores['Miner_Score']=int(clamp(50 + (8 if pd.notna(net.get('Miner_Revenue_USD')) else 0) + (8 if pd.notna(net.get('Hash_Rate')) else 0) + (8 if pd.notna(net.get('Difficulty')) else 0)))
        # Public free stack does not reliably expose realized-cap cohort metrics.
        missing += ['Realized_Price','MVRV','MVRV_Z_Score','SOPR','NUPL','STH_Cost_Basis','LTH_Cost_Basis','Exchange_Reserves','Miner_Flows','ETF_Flows']
        deep['Framework']='Bitcoin: macro/liquidity + spot/derivatives + network security + miner economics + issuance/supply + holder/on-chain valuation + technical cycle.'
    elif model=='Ethereum':
        chain=defillama_chain_snapshot('ETH'); deep.update(chain)
        scores['Network_Economics_Score']=int(clamp(50 + (12 if pd.notna(chain.get('TVL_$')) else 0)))
        missing += ['Staking_Ratio','Validator_APR','Net_Issuance','ETH_Burn','Blob_Fees','L2_Blob_Activity','ETF_Flows']
        deep['Framework']='Ethereum: macro + derivatives + staking/validator economics + issuance/burn + fees/blobs/L2 activity + TVL/stablecoin usage + ETH/BTC relative strength.'
    elif model=='L1/L2':
        chain=defillama_chain_snapshot(c); deep.update(chain); scores['Tokenomics_Score']=round(_score_tokenomics(cg))
        scores['Network_Activity_Score']=int(clamp(50+(15 if pd.notna(chain.get('TVL_$')) else 0)+(5 if pd.notna(cg.get('Commits_4w')) else 0)))
        missing += ['Active_Users','Network_Fees','Network_Revenue','Stablecoin_Supply','Token_Unlocks','Validator_Concentration']
        deep['Framework']='L1/L2: network growth + users/fees/TVL/stablecoins + tokenomics/unlocks + developer activity + decentralization + derivatives + relative strength vs BTC/ETH.'
    elif model=='DeFi':
        p=defillama_protocol_snapshot(c); deep.update(p); scores['Tokenomics_Score']=round(_score_tokenomics(cg))
        scores['Protocol_Economics_Score']=int(clamp(50+(18 if pd.notna(p.get('Protocol_TVL_$')) else 0)))
        missing += ['Protocol_Fees','Protocol_Revenue','Tokenholder_Revenue','Net_Deposits','Incentives','Bad_Debt','Treasury','Token_Unlocks']
        deep['Framework']='DeFi: TVL + deposits/borrowing + fees/revenue + tokenholder value capture + incentives/dilution + collateral/bad-debt risk + governance + tokenomics.'
    elif model=='Stablecoin':
        scores['Liquidity_Score']=int(clamp(50+(15 if pd.notna(cg.get('Market_Cap_$')) else 0)+(10 if pd.notna(cg.get('24h_Volume_$')) else 0)))
        missing += ['Peg_Deviation_History','Reserve_Composition','Attestation_Freshness','Chain_Distribution','DEX_Liquidity','Issuer_Concentration']
        deep['Framework']='Stablecoin: peg stability + reserve quality/attestations + redemption/liquidity + supply growth + chain/exchange concentration + counterparty/regulatory risk.'
    else:
        scores['Tokenomics_Score']=round(_score_tokenomics(cg))
        missing += ['Holder_Concentration','Token_Unlocks','Exchange_Liquidity_Depth','Active_Users']
        deep['Framework']='Token: liquidity + market structure + tokenomics/FDV/unlocks + holder concentration + network/use-case activity + derivatives where available + BTC-relative strength.'
        if model=='Speculative Token': deep['Framework']='Speculative token: liquidity/market depth + holder concentration + tokenomics + listings + momentum/market structure; fundamental value-capture assumptions receive low weight.'

    if deriv:
        deep.update({
            'Funding_Rate':deriv.get('Funding_Rate_OI_Weighted_%'), 'Open_Interest':deriv.get('Open_Interest_USD'),
            'OI_24h_%':deriv.get('Open_Interest_24h_%'), 'Basis':deriv.get('Perp_Basis_OI_Weighted_%'),
            'Long_Short_Ratio':deriv.get('Long_Short_Ratio'), 'Derivatives_Provider_Count':deriv.get('Provider_Count'),
        })
        ds=50; f=deep.get('Funding_Rate'); oi=deep.get('OI_24h_%')
        if pd.notna(f): ds += 8 if abs(f)<.03 else -8 if abs(f)>.08 else 0
        if pd.notna(oi): ds += 5 if -5<=oi<=10 else -8 if oi>20 else 0
        scores['Derivatives_Score']=int(clamp(ds))
    deep.update(scores)
    deep['Missing_Professional_Data']=missing
    available=sum(1 for v in deep.values() if v is not None and not (isinstance(v,float) and pd.isna(v)))
    deep['Professional_Data_Coverage_%']=int(clamp(100*available/max(available+len(missing),1)))
    return deep


def professional_crypto_cycle(ticker: str, df: pd.DataFrame, snapshot: dict | None = None) -> dict:
    """Regime-aware crypto decision layer.

    Separates structural/cycle opportunity from execution timing. It never assumes a
    new ATH is guaranteed and does not treat high RSI/price above an EMA as bearish
    by itself during a confirmed bull expansion.
    """
    c=_coin(ticker); model=crypto_model_type(c); snap=snapshot or {}
    if df is None or df.empty or 'Close' not in df:
        return {'Crypto_Regime':'UNKNOWN','Cycle_Score':50,'Structural_Trend_Score':50,
                'Entry_Timing_Score':50,'Long_Term_Opportunity_Score':50,'Overextension_Risk':'UNKNOWN',
                'Leverage_Risk':'UNKNOWN','Cycle_Risk':'UNKNOWN','Entry_Type':'WATCH','Crypto_Verdict':'Insufficient price history.'}
    close=df['Close'].dropna(); p=float(close.iloc[-1])
    ema21=close.ewm(span=21,adjust=False).mean(); ema50=close.ewm(span=50,adjust=False).mean(); sma200=close.rolling(200).mean()
    w=close.resample('W').last().dropna() if isinstance(close.index,pd.DatetimeIndex) else pd.Series(dtype=float)
    w21=w.ewm(span=21,adjust=False).mean() if len(w) else w; w40=w.rolling(40).mean() if len(w) else w; w200=w.rolling(200).mean() if len(w) else w
    def last(s): return float(s.iloc[-1]) if len(s) and pd.notna(s.iloc[-1]) else np.nan
    e21,e50,s200,we21,ws40,ws200=map(last,[ema21,ema50,sma200,w21,w40,w200])
    rsi=np.nan
    if len(close)>=15:
        d=close.diff(); up=d.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean(); rs=up/dn.replace(0,np.nan); rsi=last(100-(100/(1+rs)))
    ret=close.pct_change(); rv=float(ret.tail(30).std()*np.sqrt(365)*100) if len(ret.dropna())>=20 else np.nan
    ath=float(close.cummax().iloc[-1]); dd=100*(p/ath-1) if ath else np.nan
    # structural score: daily + weekly trend and slope; no short-term oscillator penalty.
    structural=50
    for cond,pts in [(p>e21,8),(e21>e50,10),(p>s200,12),(we21==we21 and p>we21,10),(ws40==ws40 and p>ws40,10),(ws200==ws200 and p>ws200,10)]:
        structural += pts if cond else -pts
    if len(ema50)>20 and pd.notna(ema50.iloc[-20]): structural += 8 if e50>float(ema50.iloc[-20]) else -8
    structural=float(clamp(structural))
    # regime is based on structure and drawdown, not a promise about future ATH.
    if structural<35 and pd.notna(dd) and dd<-35: regime='BEAR MARKET'
    elif structural>=55 and pd.notna(dd) and dd<-20: regime='BULL CONFIRMATION / RECOVERY'
    elif structural>=72 and (pd.isna(dd) or dd>-20): regime='BULL EXPANSION'
    elif structural>=60: regime='EARLY / DEVELOPING BULL'
    elif structural<48: regime='BOTTOMING / TRANSITION'
    else: regime='NEUTRAL / TRANSITION'
    cycle=structural
    if regime=='BULL CONFIRMATION / RECOVERY': cycle+=8
    if regime=='BULL EXPANSION': cycle+=6
    cycle=float(clamp(cycle))
    # Regime-aware execution. Momentum is tolerated in bull expansion; extremes are still flagged.
    dist21=100*(p/e21-1) if e21 else np.nan
    vol_unit=dist21/max(rv/np.sqrt(365)*100,0.5) if pd.notna(rv) and pd.notna(dist21) else np.nan
    entry=58 if regime in {'BULL EXPANSION','BULL CONFIRMATION / RECOVERY','EARLY / DEVELOPING BULL'} else 50
    if pd.notna(rsi):
        if regime in {'BULL EXPANSION','BULL CONFIRMATION / RECOVERY','EARLY / DEVELOPING BULL'}:
            entry += 10 if 50<=rsi<=72 else 3 if 72<rsi<=80 else -10 if rsi>85 else -5 if rsi<38 else 0
        else:
            entry += 10 if 42<=rsi<=62 else -12 if rsi>=75 else -7 if rsi<30 else 0
    if pd.notna(vol_unit): entry += 8 if -1<=vol_unit<=2.0 else -7 if vol_unit>4 else -3 if vol_unit<-2 else 0
    # Breakout/price discovery is a valid entry archetype, not automatically extension.
    high63=float(close.tail(63).max()) if len(close)>=20 else ath
    near_breakout=p>=high63*.985
    breakout=near_breakout and structural>=70 and (pd.isna(rsi) or rsi<86)
    pullback=structural>=65 and pd.notna(dist21) and -4<=dist21<=6
    if breakout: entry+=7; entry_type='BREAKOUT / PRICE DISCOVERY'
    elif pullback: entry+=10; entry_type='TREND PULLBACK / ACCUMULATION'
    elif structural>=70: entry_type='TREND CONTINUATION'
    else: entry_type='WATCH / TRANSITION'
    entry=float(clamp(entry))
    over='LOW'
    if (pd.notna(rsi) and rsi>85) or (pd.notna(vol_unit) and vol_unit>5): over='HIGH'
    elif (pd.notna(rsi) and rsi>78) or (pd.notna(vol_unit) and vol_unit>3): over='MODERATE'
    f=snap.get('Funding_Rate'); oi=snap.get('OI_24h_%'); leverage='LOW'
    if pd.notna(_f(f)) and abs(_f(f))>.08 or pd.notna(_f(oi)) and _f(oi)>20: leverage='HIGH'
    elif pd.notna(_f(f)) and abs(_f(f))>.04 or pd.notna(_f(oi)) and _f(oi)>10: leverage='MODERATE'
    cycle_risk='LOW' if regime in {'BULL CONFIRMATION / RECOVERY','EARLY / DEVELOPING BULL'} else 'MODERATE' if regime=='BULL EXPANSION' else 'HIGH' if regime=='BEAR MARKET' else 'MODERATE'
    # Long-term opportunity emphasizes regime/structure; execution is intentionally a smaller input.
    longterm=.48*cycle+.27*structural+.15*entry+.10*(70 if leverage=='LOW' else 50 if leverage=='MODERATE' else 25)
    if over=='HIGH': longterm-=5
    longterm=float(clamp(longterm))
    if longterm>=78 and entry>=62: verdict='BULLISH — ACCUMULATE / BUY IN TRANCHES'
    elif longterm>=75: verdict='BULLISH STRUCTURE — WAIT FOR BETTER EXECUTION OR SCALE IN'
    elif structural>=65: verdict='CONSTRUCTIVE — HOLD / SELECTIVE ACCUMULATION'
    elif regime=='BEAR MARKET': verdict='DEFENSIVE — CAPITAL PRESERVATION / WAIT FOR CONFIRMATION'
    else: verdict='NEUTRAL — WAIT FOR STRUCTURAL CONFIRMATION'
    return {
        'Crypto_Regime':regime,'Cycle_Score':int(round(cycle)),'Structural_Trend_Score':int(round(structural)),
        'Entry_Timing_Score':int(round(entry)),'Long_Term_Opportunity_Score':int(round(longterm)),
        'Overextension_Risk':over,'Leverage_Risk':leverage,'Cycle_Risk':cycle_risk,'Entry_Type':entry_type,
        'RSI_Regime_Aware':round(rsi,1) if pd.notna(rsi) else np.nan,'Dist_EMA21_%':round(dist21,2) if pd.notna(dist21) else np.nan,
        'Realized_Vol_30d_Ann_%':round(rv,1) if pd.notna(rv) else np.nan,'Drawdown_From_ATH_%':round(dd,1) if pd.notna(dd) else np.nan,
        'Crypto_Verdict':verdict,
        'Scenario_Note':'Regime classification is probabilistic. A new ATH is never assumed or guaranteed; invalidation comes from loss of structural trend and worsening leverage/cycle conditions.'
    }
