import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from core.cache_policy import OPTIONS_TTL


def _mid(row):
    bid = pd.to_numeric(row.get('bid'), errors='coerce')
    ask = pd.to_numeric(row.get('ask'), errors='coerce')
    last = pd.to_numeric(row.get('lastPrice'), errors='coerce')
    if pd.notna(bid) and pd.notna(ask) and ask >= bid and ask > 0:
        return float((bid + ask) / 2)
    return float(last) if pd.notna(last) else np.nan


@st.cache_data(ttl=OPTIONS_TTL, show_spinner=False)
def get_options_snapshot(ticker):
    out = {
        'available': False,
        'expiration': 'N/D',
        'expected_move_%': np.nan,
        'put_call_volume': np.nan,
        'put_call_oi': np.nan,
        'atm_iv_%': np.nan,
        'iv_skew_put_minus_call_%': np.nan,
        'call_volume': np.nan,
        'put_volume': np.nan,
        'call_oi': np.nan,
        'put_oi': np.nan,
        'detail': pd.DataFrame(),
    }
    try:
        t = yf.Ticker(ticker)
        exps = list(t.options or [])
        if not exps:
            return out
        exp = exps[0]
        chain = t.option_chain(exp)
        calls = chain.calls.copy()
        puts = chain.puts.copy()
        if calls.empty or puts.empty:
            return out

        info = t.fast_info or {}
        spot = info.get('last_price') or info.get('lastPrice') or info.get('previous_close')
        if spot is None:
            try: spot = float(t.history(period='5d')['Close'].dropna().iloc[-1])
            except Exception: spot = np.nan

        call_vol = pd.to_numeric(calls.get('volume'), errors='coerce').fillna(0).sum()
        put_vol = pd.to_numeric(puts.get('volume'), errors='coerce').fillna(0).sum()
        call_oi = pd.to_numeric(calls.get('openInterest'), errors='coerce').fillna(0).sum()
        put_oi = pd.to_numeric(puts.get('openInterest'), errors='coerce').fillna(0).sum()

        call_atm = puts_atm = None
        if pd.notna(spot):
            call_atm = calls.iloc[(calls['strike'] - float(spot)).abs().argsort()[:1]].iloc[0]
            puts_atm = puts.iloc[(puts['strike'] - float(spot)).abs().argsort()[:1]].iloc[0]

        expected_move = np.nan
        atm_iv = np.nan
        skew = np.nan
        if call_atm is not None and puts_atm is not None and float(spot) > 0:
            c_mid = _mid(call_atm)
            p_mid = _mid(puts_atm)
            if pd.notna(c_mid) and pd.notna(p_mid):
                expected_move = (c_mid + p_mid) / float(spot) * 100
            civ = pd.to_numeric(call_atm.get('impliedVolatility'), errors='coerce')
            piv = pd.to_numeric(puts_atm.get('impliedVolatility'), errors='coerce')
            if pd.notna(civ) and pd.notna(piv):
                atm_iv = float((civ + piv) / 2 * 100)
                skew = float((piv - civ) * 100)

        out.update({
            'available': True,
            'expiration': exp,
            'expected_move_%': expected_move,
            'put_call_volume': float(put_vol / call_vol) if call_vol > 0 else np.nan,
            'put_call_oi': float(put_oi / call_oi) if call_oi > 0 else np.nan,
            'atm_iv_%': atm_iv,
            'iv_skew_put_minus_call_%': skew,
            'call_volume': float(call_vol),
            'put_volume': float(put_vol),
            'call_oi': float(call_oi),
            'put_oi': float(put_oi),
        })

        # Compact near-the-money table
        if pd.notna(spot):
            c = calls.assign(Type='Call')
            p = puts.assign(Type='Put')
            detail = pd.concat([c, p], ignore_index=True)
            detail['Distance_%'] = (detail['strike'] / float(spot) - 1) * 100
            detail = detail[detail['Distance_%'].abs() <= 12].copy()
            keep = [x for x in ['Type','strike','lastPrice','bid','ask','volume','openInterest','impliedVolatility','Distance_%'] if x in detail]
            out['detail'] = detail[keep].sort_values(['strike','Type']).head(80)
    except Exception:
        pass
    return out
