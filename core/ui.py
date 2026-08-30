
import html
import streamlit as st

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
