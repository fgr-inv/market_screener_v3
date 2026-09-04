
import html
import math

import pandas as pd
import streamlit as st


def safe_error(message, exc=None, event='ui_action_error', **fields):
    """Show a stable user message while keeping technical details in logs.

    Provider, database and parsing exceptions can contain SQL, file paths, URLs or
    stack fragments. Those details are useful for observability but should not be
    rendered as part of the application UI.
    """
    if exc is not None:
        try:
            from core.monitoring import log_exception
            log_exception(event, exc, **fields)
        except Exception:
            pass
    st.error(str(message))


def display_value(value):
    """Return a readable scalar string for mixed-value UI tables.

    Streamlit/PyArrow logs a full conversion traceback when one object column
    mixes numbers, strings and containers. Rendering a stable display string
    avoids that console noise without changing the underlying calculations.
    """
    if value is None:
        return 'N/D'
    if isinstance(value, bool):
        return 'Sí' if value else 'No'
    if isinstance(value, dict):
        return ' · '.join(f'{key}: {display_value(item)}' for key,item in value.items()) or 'N/D'
    if isinstance(value, (list, tuple, set)):
        return ', '.join(display_value(item) for item in value) or 'N/D'
    try:
        if pd.isna(value):
            return 'N/D'
    except Exception:
        pass
    if isinstance(value, float):
        if not math.isfinite(value):
            return 'N/D'
        return f'{value:,.4f}'.rstrip('0').rstrip('.')
    return str(value)


def key_value_frame(items, key_label='Metric', value_label='Value'):
    """Build an Arrow-safe two-column dataframe for UI presentation."""
    pairs=items.items() if isinstance(items,dict) else items
    return pd.DataFrame([
        {key_label:str(key).replace('_',' '),value_label:display_value(value)}
        for key,value in pairs
    ],columns=[key_label,value_label])


def arrow_safe_frame(data):
    """Return a presentation copy that PyArrow can serialize reliably.

    Desk payloads intentionally retain structured evidence (lists and mappings).
    Streamlit tables cannot always serialize those containers when a column also
    contains scalars. Only object/string display columns are normalized here;
    numeric and datetime columns preserve their native types and calculations.
    """
    frame=data.copy() if isinstance(data,pd.DataFrame) else pd.DataFrame(data)
    for column in frame.columns:
        series=frame[column]
        if pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype):
            frame[column]=series.map(display_value)
    return frame

def inject_css():
    st.markdown("""
    <style>
    .block-container{padding-top:1.25rem;padding-bottom:2.5rem;max-width:1600px}
    [data-testid="stSidebar"]{border-right:1px solid rgba(120,120,140,.2)}
    [data-testid="stMetric"]{background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,.018));border:1px solid rgba(120,120,140,.22);padding:14px 16px;border-radius:14px}
    [data-testid="stDataFrame"]{border:1px solid rgba(120,120,140,.18);border-radius:12px;overflow:hidden}
    .hero{padding:18px 22px;border:1px solid rgba(120,120,140,.22);border-radius:18px;background:linear-gradient(135deg,rgba(73,88,255,.12),rgba(0,200,150,.05));margin-bottom:18px}
    .kicker{font-size:.8rem;opacity:.66;letter-spacing:.08em;text-transform:uppercase}
    .title{font-size:2rem;font-weight:760;line-height:1.15;margin-top:5px}
    .subtitle{opacity:.72;margin-top:8px}
    .badge{display:inline-block;padding:3px 9px;border-radius:999px;font-size:.78rem;font-weight:700;border:1px solid rgba(120,120,140,.28);margin-right:6px}
    .good{background:rgba(0,180,120,.12)} .warn{background:rgba(255,180,0,.12)}
    .bad{background:rgba(255,70,70,.12)} .neutral{background:rgba(120,120,140,.12)}
    .note{opacity:.68;font-size:.86rem;margin-top:-5px;margin-bottom:12px}
    </style>
    """, unsafe_allow_html=True)

def hero(title, subtitle, kicker="Market Intelligence"):
    body = (
        '<div class="hero">'
        f'<div class="kicker">{html.escape(kicker)}</div>'
        f'<div class="title">{html.escape(title)}</div>'
        f'<div class="subtitle">{html.escape(subtitle)}</div>'
        '</div>'
    )
    st.markdown(body, unsafe_allow_html=True)

def badge(text, tone="neutral"):
    return f'<span class="badge {tone}">{html.escape(str(text))}</span>'

def section_note(text):
    st.markdown(f'<div class="note">{html.escape(text)}</div>', unsafe_allow_html=True)

def traffic_tone(score):
    try:
        score=float(score)
    except Exception:
        return "neutral"
    return "good" if score>=70 else "bad" if score<=40 else "warn"
