from __future__ import annotations

"""Free/public market-data providers used by the zero-cost analysis stack.

The module intentionally prefers public exchange/official endpoints and returns
best-effort dictionaries. Missing data stay missing; no neutral values are
fabricated just to fill a score.
"""

import os
from typing import Any

import numpy as np
import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _secret(name: str, default: str = "") -> str:
    try:
        v = st.secrets.get(name, default)
        if v is not None and str(v).strip():
            return str(v).strip()
    except Exception:
        pass
    v = os.getenv(name, default)
    return str(v).strip() if v is not None else default


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": "market-screener/8.5"})
    return s


def _float(v: Any, default=np.nan):
    try:
        if v in (None, ""):
            return default
        return float(v)
    except Exception:
        return default


def _pct_change(cur, prev):
    try:
        cur, prev = float(cur), float(prev)
        if prev == 0:
            return np.nan
        return (cur / prev - 1.0) * 100.0
    except Exception:
        return np.nan


def coingecko_headers() -> dict:
    """Use the free CoinGecko Demo key when configured; public API still works without it."""
    key = _secret("COINGECKO_API_KEY")
    h = {"User-Agent": "market-screener/8.5"}
    if key:
        h["x-cg-demo-api-key"] = key
    return h


@st.cache_data(ttl=300, show_spinner=False)
def binance_derivatives_snapshot(symbol: str = "BTCUSDT") -> dict:
    out = {
        "provider": "Binance public",
        "available": False,
        "Funding_Rate_%": np.nan,
        "Open_Interest_USD": np.nan,
        "Open_Interest_24h_%": np.nan,
        "Perp_Basis_%": np.nan,
        "Long_Short_Ratio": np.nan,
    }
    base = "https://fapi.binance.com"
    s = _session()
    try:
        p = s.get(base + "/fapi/v1/premiumIndex", params={"symbol": symbol}, timeout=8)
        p.raise_for_status()
        pdx = p.json()
        mark = _float(pdx.get("markPrice"))
        index = _float(pdx.get("indexPrice"))
        out["Funding_Rate_%"] = _float(pdx.get("lastFundingRate")) * 100
        if pd.notna(mark) and pd.notna(index) and index:
            out["Perp_Basis_%"] = (mark / index - 1.0) * 100.0

        oi = s.get(base + "/fapi/v1/openInterest", params={"symbol": symbol}, timeout=8)
        oi.raise_for_status()
        oi_units = _float(oi.json().get("openInterest"))
        if pd.notna(oi_units) and pd.notna(mark):
            out["Open_Interest_USD"] = oi_units * mark

        hist = s.get(
            base + "/futures/data/openInterestHist",
            params={"symbol": symbol, "period": "1h", "limit": 25},
            timeout=8,
        )
        if hist.ok:
            arr = hist.json()
            if isinstance(arr, list) and len(arr) >= 2:
                first = _float(arr[0].get("sumOpenInterestValue"))
                last = _float(arr[-1].get("sumOpenInterestValue"))
                out["Open_Interest_24h_%"] = _pct_change(last, first)

        ls = s.get(
            base + "/futures/data/globalLongShortAccountRatio",
            params={"symbol": symbol, "period": "1h", "limit": 1},
            timeout=8,
        )
        if ls.ok:
            arr = ls.json()
            if isinstance(arr, list) and arr:
                out["Long_Short_Ratio"] = _float(arr[-1].get("longShortRatio"))
        out["available"] = True
    except Exception as exc:
        out["reason"] = str(exc)[:160]
    return out


@st.cache_data(ttl=300, show_spinner=False)
def bybit_derivatives_snapshot(symbol: str = "BTCUSDT") -> dict:
    out = {
        "provider": "Bybit public",
        "available": False,
        "Funding_Rate_%": np.nan,
        "Open_Interest_USD": np.nan,
        "Perp_Basis_%": np.nan,
    }
    try:
        r = _session().get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear", "symbol": symbol},
            timeout=8,
        )
        r.raise_for_status()
        rows = r.json().get("result", {}).get("list", [])
        if not rows:
            return out
        x = rows[0]
        out["Funding_Rate_%"] = _float(x.get("fundingRate")) * 100
        out["Open_Interest_USD"] = _float(x.get("openInterestValue"))
        mark, index = _float(x.get("markPrice")), _float(x.get("indexPrice"))
        if pd.notna(mark) and pd.notna(index) and index:
            out["Perp_Basis_%"] = (mark / index - 1.0) * 100.0
        out["available"] = True
    except Exception as exc:
        out["reason"] = str(exc)[:160]
    return out


@st.cache_data(ttl=300, show_spinner=False)
def okx_derivatives_snapshot(coin: str = "BTC") -> dict:
    c = str(coin).upper().replace("-USD", "").replace("USDT", "")
    inst = f"{c}-USDT-SWAP"
    out = {
        "provider": "OKX public",
        "available": False,
        "Funding_Rate_%": np.nan,
        "Open_Interest_USD": np.nan,
        "Perp_Basis_%": np.nan,
    }
    s = _session()
    try:
        fr = s.get("https://www.okx.com/api/v5/public/funding-rate", params={"instId": inst}, timeout=8)
        if fr.ok:
            arr = fr.json().get("data", [])
            if arr:
                out["Funding_Rate_%"] = _float(arr[0].get("fundingRate")) * 100

        oi = s.get("https://www.okx.com/api/v5/public/open-interest", params={"instType": "SWAP", "instId": inst}, timeout=8)
        if oi.ok:
            arr = oi.json().get("data", [])
            if arr:
                out["Open_Interest_USD"] = _float(arr[0].get("oiUsd"))

        mark_r = s.get("https://www.okx.com/api/v5/public/mark-price", params={"instType": "SWAP", "instId": inst}, timeout=8)
        idx_r = s.get("https://www.okx.com/api/v5/market/index-tickers", params={"instId": f"{c}-USDT"}, timeout=8)
        if mark_r.ok and idx_r.ok:
            ma = mark_r.json().get("data", [])
            ia = idx_r.json().get("data", [])
            if ma and ia:
                mark, index = _float(ma[0].get("markPx")), _float(ia[0].get("idxPx"))
                if pd.notna(mark) and pd.notna(index) and index:
                    out["Perp_Basis_%"] = (mark / index - 1.0) * 100.0
        out["available"] = any(pd.notna(out[k]) for k in ("Funding_Rate_%", "Open_Interest_USD", "Perp_Basis_%"))
    except Exception as exc:
        out["reason"] = str(exc)[:160]
    return out


@st.cache_data(ttl=300, show_spinner=False)
def free_crypto_derivatives_snapshot(coin: str = "BTC") -> dict:
    """Aggregate free public derivatives data from Binance, Bybit and OKX.

    Funding and basis are OI-weighted where notional OI is available. Binance
    supplies a public 24h OI history proxy. Historical aggregate liquidations and
    spot-ETF flows are intentionally left missing because a reliable zero-cost
    multi-venue REST feed is not available in this stack.
    """
    c = str(coin).upper().replace("-USD", "").replace("USDT", "")
    sym = c + "USDT"
    providers = [binance_derivatives_snapshot(sym), bybit_derivatives_snapshot(sym), okx_derivatives_snapshot(c)]
    good = [p for p in providers if p.get("available")]

    def weighted(field: str):
        vals = []
        for p in good:
            v, w = p.get(field), p.get("Open_Interest_USD")
            if pd.notna(v):
                vals.append((float(v), float(w) if pd.notna(w) and float(w) > 0 else 1.0))
        if not vals:
            return np.nan
        den = sum(w for _, w in vals)
        return sum(v * w for v, w in vals) / den if den else np.nan

    oi_vals = [float(p["Open_Interest_USD"]) for p in good if pd.notna(p.get("Open_Interest_USD"))]
    b = providers[0]
    return {
        "available": bool(good),
        "provider": "Free multi-exchange (Binance + Bybit + OKX)",
        "symbol": c,
        "Provider_Count": len(good),
        "Funding_Rate_OI_Weighted_%": weighted("Funding_Rate_%"),
        "Open_Interest_USD": sum(oi_vals) if oi_vals else np.nan,
        "Open_Interest_24h_%": b.get("Open_Interest_24h_%", np.nan),
        "Perp_Basis_OI_Weighted_%": weighted("Perp_Basis_%"),
        "Long_Short_Ratio": b.get("Long_Short_Ratio", np.nan),
        "Liquidations_24h_$": np.nan,
        "ETF_Flow_5d_$": np.nan,
        "Components": {p.get("provider", "unknown"): p for p in providers},
        "Coverage_Note": "Free REST aggregation covers funding/OI/basis; reliable aggregate liquidations and ETF flows remain unavailable without a specialist feed.",
    }
