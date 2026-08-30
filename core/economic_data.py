
from __future__ import annotations

from io import StringIO
from pathlib import Path
from datetime import datetime, timezone
import os
import numpy as np
import pandas as pd
import requests
import streamlit as st
from core.cache_policy import FRED_TTL
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.macro import calculate_macro_snapshot
from core.utils import clamp

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "cache" / "fred"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FRED_SERIES = {
    "CPI": "CPIAUCSL",
    "Core CPI": "CPILFESL",
    "Headline PCE": "PCEPI",
    "Core PCE": "PCEPILFE",
    "Fed Funds": "FEDFUNDS",
    "Unemployment": "UNRATE",
    "Payrolls": "PAYEMS",
    "Industrial Production": "INDPRO",
    "Manufacturing Production": "IPMAN",
    "Retail Sales": "RSAFS",
    "Housing Starts": "HOUST",
    "10Y-2Y": "T10Y2Y",
    "10Y Breakeven": "T10YIE",
    "Financial Conditions": "NFCI",
    # ISM PMI is not consistently available as a free FRED series.
}

def _secret(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    value = os.getenv(name)
    return str(value) if value else None

def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": "market-screener/8.5"})
    return s

def _normalize_series(df: pd.DataFrame, date_col: str, value_col: str) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)
    d = df[[date_col, value_col]].copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d[value_col] = pd.to_numeric(d[value_col], errors="coerce")
    d = d.dropna().drop_duplicates(date_col).sort_values(date_col)
    if d.empty:
        return pd.Series(dtype=float)
    return d.set_index(date_col)[value_col].astype(float)

def _cache_path(series_id: str) -> Path:
    return CACHE_DIR / f"{series_id}.csv"

def _save_cache(series_id: str, s: pd.Series) -> None:
    if s is None or s.empty:
        return
    out = s.rename("value").to_frame()
    out.index.name = "date"
    out.to_csv(_cache_path(series_id))

def _load_cache(series_id: str) -> pd.Series:
    p = _cache_path(series_id)
    if not p.exists():
        return pd.Series(dtype=float)
    try:
        df = pd.read_csv(p)
        return _normalize_series(df, "date", "value")
    except Exception:
        return pd.Series(dtype=float)

def _fetch_api(series_id: str, api_key: str) -> pd.Series:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
    }
    r = _session().get(
        "https://api.stlouisfed.org/fred/series/observations",
        params=params,
        timeout=25,
    )
    r.raise_for_status()
    obs = r.json().get("observations", [])
    if not obs:
        return pd.Series(dtype=float)
    df = pd.DataFrame(obs)
    return _normalize_series(df, "date", "value")

def _fetch_graph_csv(series_id: str) -> pd.Series:
    r = _session().get(
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        params={"id": series_id},
        timeout=25,
    )
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))
    if df.empty or len(df.columns) < 2:
        return pd.Series(dtype=float)
    return _normalize_series(df, df.columns[0], df.columns[-1])

@st.cache_data(ttl=FRED_TTL, show_spinner=False)
def fred_series_with_meta(series_id: str) -> dict:
    api_key = _secret("FRED_API_KEY")
    errors = []

    if api_key:
        try:
            s = _fetch_api(series_id, api_key)
            if not s.empty:
                _save_cache(series_id, s)
                return {
                    "series": s,
                    "source": "FRED API",
                    "status": "LIVE",
                    "error": None,
                    "latest_date": s.index[-1],
                }
        except Exception as exc:
            errors.append(f"FRED API: {exc}")

    try:
        s = _fetch_graph_csv(series_id)
        if not s.empty:
            _save_cache(series_id, s)
            return {
                "series": s,
                "source": "FRED CSV",
                "status": "LIVE",
                "error": None,
                "latest_date": s.index[-1],
            }
    except Exception as exc:
        errors.append(f"FRED CSV: {exc}")

    cached = _load_cache(series_id)
    if not cached.empty:
        return {
            "series": cached,
            "source": "Local FRED cache",
            "status": "STALE",
            "error": " | ".join(errors) if errors else None,
            "latest_date": cached.index[-1],
        }

    return {
        "series": pd.Series(dtype=float),
        "source": "Unavailable",
        "status": "MISSING",
        "error": " | ".join(errors) if errors else "No data returned",
        "latest_date": None,
    }

def fred_series(series_id: str) -> pd.Series:
    return fred_series_with_meta(series_id)["series"]

def _latest(s):
    s = s.dropna()
    return float(s.iloc[-1]) if len(s) else np.nan

def _previous(s):
    s = s.dropna()
    return float(s.iloc[-2]) if len(s) >= 2 else np.nan

def _yoy(s):
    s = s.dropna()
    if len(s) < 13:
        return np.nan
    return _latest(s.pct_change(12) * 100)

def _yoy_previous(s):
    s = s.dropna()
    yy = s.pct_change(12) * 100
    yy = yy.dropna()
    return float(yy.iloc[-2]) if len(yy) >= 2 else np.nan

def _delta(s, periods):
    s = s.dropna()
    if len(s) <= periods:
        return np.nan
    return float(s.iloc[-1] - s.iloc[-(periods + 1)])

def _payroll_3m_avg(s):
    s = s.dropna()
    if len(s) < 4:
        return np.nan
    return float(s.diff().tail(3).mean())

def _score_growth(vals: dict) -> float:
    points = []
    for val, pos1, pos2, neg1, neg2 in [
        (vals["Industrial_Production_YoY"], 2, 4, -2, -5),
        (vals["Manufacturing_Production_YoY"], 2, 4, -2, -5),
        (vals["Retail_Sales_YoY"], 2, 5, 0, -3),
        (vals["Housing_Starts_YoY"], 5, 15, -10, -20),
    ]:
        if pd.notna(val):
            points.append(60 if val >= pos2 else 55 if val >= pos1 else 40 if val <= neg1 else 30 if val <= neg2 else 50)
    if pd.notna(vals["Payroll_3m_Avg_Change"]):
        p = vals["Payroll_3m_Avg_Change"]
        points.append(65 if p >= 150 else 58 if p >= 75 else 35 if p < 0 else 48)
    if pd.notna(vals["Unemployment_3m_Change"]):
        u = vals["Unemployment_3m_Change"]
        points.append(60 if u <= 0 else 35 if u >= 0.3 else 43 if u >= 0.15 else 50)
    return float(round(np.mean(points))) if points else np.nan

def _score_inflation(vals: dict, raw: dict) -> float:
    points = []
    for val in [vals["Core_CPI_YoY"], vals["Core_PCE_YoY"]]:
        if pd.notna(val):
            points.append(75 if val >= 3.5 else 65 if val >= 2.8 else 57 if val >= 2.3 else 42 if val <= 2.1 else 50)
    if pd.notna(vals["10Y_Breakeven"]):
        b = vals["10Y_Breakeven"]
        points.append(65 if b >= 2.6 else 42 if b <= 2.1 else 50)
    try:
        yy = raw["Core CPI"].pct_change(12).dropna() * 100
        if len(yy) >= 4:
            trend = float(yy.iloc[-1] - yy.iloc[-4])
            points.append(62 if trend >= 0.25 else 38 if trend <= -0.25 else 50)
    except Exception:
        pass
    return float(round(np.mean(points))) if points else np.nan

def _score_policy(vals: dict) -> float:
    points = []
    if pd.notna(vals["Fed_Funds_6m_Change"]):
        f = vals["Fed_Funds_6m_Change"]
        points.append(65 if f <= -0.50 else 58 if f < 0 else 38 if f >= 0.50 else 50)
    if pd.notna(vals["NFCI"]):
        n = vals["NFCI"]
        points.append(65 if n <= -0.30 else 58 if n < 0 else 35 if n >= 0.25 else 50)
    if pd.notna(vals["10Y_2Y"]):
        c = vals["10Y_2Y"]
        points.append(60 if c >= 0.50 else 40 if c <= -0.50 else 50)
    return float(round(np.mean(points))) if points else np.nan

@st.cache_data(ttl=FRED_TTL, show_spinner=False)
def get_slow_macro_snapshot() -> dict:
    raw, meta, missing = {}, {}, []

    for label, sid in FRED_SERIES.items():
        item = fred_series_with_meta(sid)
        raw[label] = item["series"]
        meta[label] = {
            "series_id": sid,
            "source": item["source"],
            "status": item["status"],
            "latest_date": item["latest_date"],
            "error": item["error"],
        }
        if item["series"].empty:
            missing.append(label)

    vals = {
        "Core_CPI_YoY": _yoy(raw["Core CPI"]),
        "Core_PCE_YoY": _yoy(raw["Core PCE"]),
        "CPI_YoY": _yoy(raw["CPI"]),
        "PCE_YoY": _yoy(raw["Headline PCE"]),
        "Industrial_Production_YoY": _yoy(raw["Industrial Production"]),
        "Manufacturing_Production_YoY": _yoy(raw["Manufacturing Production"]),
        "Retail_Sales_YoY": _yoy(raw["Retail Sales"]),
        "Housing_Starts_YoY": _yoy(raw["Housing Starts"]),
        "Unemployment": _latest(raw["Unemployment"]),
        "Unemployment_3m_Change": _delta(raw["Unemployment"], 3),
        "Payroll_3m_Avg_Change": _payroll_3m_avg(raw["Payrolls"]),
        "Fed_Funds": _latest(raw["Fed Funds"]),
        "Fed_Funds_6m_Change": _delta(raw["Fed Funds"], 6),
        "10Y_2Y": _latest(raw["10Y-2Y"]),
        "10Y_Breakeven": _latest(raw["10Y Breakeven"]),
        "NFCI": _latest(raw["Financial Conditions"]),
        "ISM_PMI": np.nan,
    }

    growth = _score_growth(vals)
    inflation = _score_inflation(vals, raw)
    policy = _score_policy(vals)

    available_scores = [x for x in [growth, policy, (100 - inflation if pd.notna(inflation) else np.nan)] if pd.notna(x)]
    slow_score = float(round(np.mean(available_scores))) if available_scores else np.nan

    if pd.notna(growth) and pd.notna(inflation):
        if growth >= 55 and inflation < 55:
            regime = "GOLDILOCKS"
        elif growth >= 55 and inflation >= 55:
            regime = "REFLATION"
        elif growth < 55 and inflation >= 55:
            regime = "STAGFLATION RISK"
        else:
            regime = "SLOWDOWN / DISINFLATION"
    else:
        regime = "N/A"

    available = sum(1 for s in raw.values() if not s.empty)
    quality = round(available / len(raw) * 100)

    rows = []
    mapping = [
        ("Core CPI YoY", "Core CPI", vals["Core_CPI_YoY"], _yoy_previous(raw["Core CPI"]), "%"),
        ("Core PCE YoY", "Core PCE", vals["Core_PCE_YoY"], _yoy_previous(raw["Core PCE"]), "%"),
        ("Headline CPI YoY", "CPI", vals["CPI_YoY"], _yoy_previous(raw["CPI"]), "%"),
        ("Headline PCE YoY", "Headline PCE", vals["PCE_YoY"], _yoy_previous(raw["Headline PCE"]), "%"),
        ("Industrial Production YoY", "Industrial Production", vals["Industrial_Production_YoY"], _yoy_previous(raw["Industrial Production"]), "%"),
        ("Manufacturing Production YoY", "Manufacturing Production", vals["Manufacturing_Production_YoY"], _yoy_previous(raw["Manufacturing Production"]), "%"),
        ("Retail Sales YoY", "Retail Sales", vals["Retail_Sales_YoY"], _yoy_previous(raw["Retail Sales"]), "%"),
        ("Housing Starts YoY", "Housing Starts", vals["Housing_Starts_YoY"], _yoy_previous(raw["Housing Starts"]), "%"),
        ("Unemployment", "Unemployment", vals["Unemployment"], _previous(raw["Unemployment"]), "%"),
        ("Unemployment 3m change", "Unemployment", vals["Unemployment_3m_Change"], np.nan, "pp"),
        ("Payroll 3m avg change", "Payrolls", vals["Payroll_3m_Avg_Change"], np.nan, "thousands"),
        ("Fed Funds", "Fed Funds", vals["Fed_Funds"], _previous(raw["Fed Funds"]), "%"),
        ("Fed Funds 6m change", "Fed Funds", vals["Fed_Funds_6m_Change"], np.nan, "pp"),
        ("10Y-2Y", "10Y-2Y", vals["10Y_2Y"], _previous(raw["10Y-2Y"]), "pp"),
        ("10Y Breakeven", "10Y Breakeven", vals["10Y_Breakeven"], _previous(raw["10Y Breakeven"]), "%"),
        ("NFCI", "Financial Conditions", vals["NFCI"], _previous(raw["Financial Conditions"]), "index"),
    ]
    for indicator, key, value, previous, unit in mapping:
        m = meta[key]
        trend = ""
        if pd.notna(value) and pd.notna(previous):
            trend = "↑" if value > previous else "↓" if value < previous else "→"
        rows.append({
            "Indicator": indicator,
            "Value": value,
            "Previous": previous,
            "Trend": trend,
            "Unit": unit,
            "Source": m["source"],
            "Status": m["status"],
            "Updated": m["latest_date"],
        })

    return {
        "Slow_Macro_Score": slow_score,
        "Slow_Growth": growth,
        "Slow_Inflation_Pressure": inflation,
        "Slow_Policy": policy,
        "Economic_Regime_Slow": regime,
        "Data_Quality_%": quality,
        **vals,
        "Missing": missing,
        "Series_Meta": meta,
        "Slow_Table": pd.DataFrame(rows),
        "FRED_Key_Configured": bool(_secret("FRED_API_KEY")),
    }

def institutional_macro_snapshot(price_map, breadth_level=50):
    fast = calculate_macro_snapshot(price_map, breadth_level)
    slow = get_slow_macro_snapshot()

    if pd.notna(slow["Slow_Macro_Score"]):
        overall = int(clamp(round(0.70 * fast["Macro_Score"] + 0.30 * slow["Slow_Macro_Score"])))
        slow_used = True
    else:
        overall = int(fast["Macro_Score"])
        slow_used = False

    out = dict(fast)
    out.update(slow)
    out["Fast_Macro_Score"] = fast["Macro_Score"]
    out["Macro_Score"] = overall
    out["Slow_Layer_Used"] = slow_used
    out["Institutional_Regime"] = "RISK-ON" if overall >= 70 else "RISK-OFF" if overall <= 40 else "NEUTRAL"
    return out
