import numpy as np
import pandas as pd
import streamlit as st

from core.market_data import load_universe, download_prices, get_macro_symbols
from core.breadth import composite_breadth
from core.economic_data import institutional_macro_snapshot, get_slow_macro_snapshot
from core.ui import hero, section_note, badge, traffic_tone
from core.macro_calendar import get_us_macro_calendar


def _num(m, key, fallback=None):
    value = m.get(key, np.nan)
    try:
        value = float(value)
        if np.isfinite(value):
            return value
    except Exception:
        pass
    if fallback:
        return _num(m, fallback)
    return np.nan


def _score_text(value):
    return "N/A" if pd.isna(value) else f"{float(value):.0f}/100"


def _state(score, high="Favorable", low="Restrictive"):
    if pd.isna(score):
        return "N/A"
    return high if score >= 60 else low if score <= 40 else "Neutral"


def _trend_word(current, previous, inverse=False):
    if pd.isna(current) or pd.isna(previous):
        return "N/A"
    delta = current - previous
    if abs(delta) < 0.05:
        return "Estable"
    improving = delta < 0 if inverse else delta > 0
    return "Mejorando" if improving else "Empeorando"


def _macro_read(m):
    growth = _num(m, "Slow_Growth", "Growth")
    inflation = _num(m, "Slow_Inflation_Pressure", "Inflation_Pressure")
    policy = _num(m, "Slow_Policy", "Rates")
    credit = _num(m, "Credit")
    liquidity = _num(m, "Liquidity")
    breadth = _num(m, "Breadth")
    risk = _num(m, "Risk_Appetite")

    positives, negatives = [], []
    if pd.notna(growth):
        (positives if growth >= 55 else negatives if growth < 45 else positives).append(
            "crecimiento firme" if growth >= 55 else "crecimiento débil" if growth < 45 else "crecimiento moderado"
        )
    if pd.notna(inflation):
        (negatives if inflation >= 60 else positives if inflation <= 45 else positives).append(
            "inflación presionando" if inflation >= 60 else "desinflación favorable" if inflation <= 45 else "inflación intermedia"
        )
    if pd.notna(policy):
        (positives if policy >= 60 else negatives if policy <= 40 else positives).append(
            "condiciones monetarias favorables" if policy >= 60 else "política restrictiva" if policy <= 40 else "política neutral"
        )
    if pd.notna(credit):
        (positives if credit >= 60 else negatives if credit <= 40 else positives).append(
            "crédito saludable" if credit >= 60 else "crédito deteriorándose" if credit <= 40 else "crédito estable"
        )
    if pd.notna(breadth) and breadth < 45:
        negatives.append("participación de mercado estrecha")
    elif pd.notna(breadth) and breadth >= 60:
        positives.append("breadth amplio")

    headline = m.get("Economic_Regime_Slow")
    if not headline or headline == "N/A":
        headline = m.get("Economic_Regime", "N/A")
    return {
        "growth": growth, "inflation": inflation, "policy": policy, "credit": credit,
        "liquidity": liquidity, "breadth": breadth, "risk": risk,
        "headline": headline, "positives": positives, "negatives": negatives,
    }


def _sector_map(x):
    g, inf, pol, cr, liq = x["growth"], x["inflation"], x["policy"], x["credit"], x["liquidity"]
    def score(weights):
        vals=[]; ws=[]
        for val, w, invert in weights:
            if pd.notna(val):
                vals.append((100-val if invert else val)*w); ws.append(w)
        return np.nan if not ws else round(sum(vals)/sum(ws))
    rows = [
        ("Technology", "XLK", score([(g,.20,False),(pol,.30,False),(liq,.30,False),(cr,.20,False)]), "Growth + tasas + liquidez"),
        ("Communication Services", "XLC", score([(g,.25,False),(pol,.25,False),(liq,.30,False),(cr,.20,False)]), "Growth + liquidez"),
        ("Consumer Discretionary", "XLY", score([(g,.40,False),(pol,.25,False),(cr,.25,False),(inf,.10,True)]), "Consumo + crédito + tasas"),
        ("Industrials", "XLI", score([(g,.50,False),(cr,.25,False),(pol,.15,False),(inf,.10,True)]), "Ciclo económico + crédito"),
        ("Financials", "XLF", score([(g,.35,False),(cr,.40,False),(pol,.15,False),(inf,.10,True)]), "Crédito + crecimiento"),
        ("Real Estate", "XLRE", score([(pol,.40,False),(cr,.25,False),(liq,.25,False),(inf,.10,True)]), "Tasas + financiación"),
        ("Utilities", "XLU", score([(pol,.35,False),(cr,.20,False),(inf,.25,True),(g,.20,True)]), "Tasas + inflación + defensividad"),
        ("Consumer Staples", "XLP", score([(g,.35,True),(inf,.20,True),(pol,.20,False),(cr,.25,False)]), "Defensividad + inflación"),
        ("Health Care", "XLV", score([(g,.30,True),(inf,.15,True),(pol,.20,False),(cr,.20,False),(liq,.15,False)]), "Defensividad + financiación"),
        ("Materials", "XLB", score([(g,.50,False),(inf,.20,False),(cr,.20,False),(pol,.10,False)]), "Ciclo + commodities"),
        ("Energy", "XLE", score([(g,.35,False),(inf,.45,False),(cr,.20,False)]), "Crecimiento + inflación/energía"),
    ]
    df=pd.DataFrame(rows, columns=["Sector","ETF","Macro Fit","Principal driver"])
    df["Lectura"] = df["Macro Fit"].apply(lambda v: "🟢 Favorecido" if pd.notna(v) and v>=60 else "🔴 Desfavorecido" if pd.notna(v) and v<=40 else "🟡 Neutral")
    return df.sort_values("Macro Fit", ascending=False, na_position="last")


hero(
    "Macro & Rates",
    "Menos indicadores, más decisión: crecimiento, inflación, tasas, crédito y qué implican para el mercado.",
    "Actionable Macro Dashboard",
)

with st.sidebar:
    refresh = st.button("🔄 Actualizar Macro", type="primary", use_container_width=True)

if st.session_state.macro_snapshot is None or refresh:
    if refresh:
        get_slow_macro_snapshot.clear()
    with st.status("Actualizando mercado + FRED...", expanded=True) as status:
        sp = load_universe("S&P 500")
        ndx = load_universe("Nasdaq 100")
        fb = load_universe("Fallback líquido")
        syms = list(dict.fromkeys(sp["Ticker"].tolist()+ndx["Ticker"].tolist()+fb["Ticker"].tolist()+list(get_macro_symbols().values())))
        pm = download_prices(syms, period="2y")
        bscore, bdf = composite_breadth({"S&P 500":sp,"Nasdaq 100":ndx,"Fallback líquido":fb}, pm)
        macro = institutional_macro_snapshot(pm, breadth_level=50 if pd.isna(bscore) else bscore)
        st.session_state.macro_snapshot = macro
        st.session_state.macro_breadth_detail = bdf
        status.update(label="Macro actualizado", state="complete", expanded=False)

m = st.session_state.macro_snapshot
if not m:
    st.info("Presioná Actualizar Macro.")
    st.stop()

x = _macro_read(m)

# 1. Executive decision layer
st.subheader("🎯 Lectura ejecutiva")
c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("Market regime", m.get("Institutional_Regime","N/A"), _score_text(_num(m,"Macro_Score")))
c2.metric("Growth", _state(x["growth"], "Expansivo", "Débil"), _score_text(x["growth"]))
c3.metric("Inflation", _state(100-x["inflation"] if pd.notna(x["inflation"]) else np.nan, "Benigna", "Alta"), _score_text(x["inflation"]))
c4.metric("Rates / Conditions", _state(x["policy"]), _score_text(x["policy"]))
c5.metric("Credit", _state(x["credit"], "Saludable", "Tensionado"), _score_text(x["credit"]))

st.markdown(
    badge(m.get("Institutional_Regime","N/A"), traffic_tone(_num(m,"Macro_Score")))
    + badge(x["headline"], "warn")
    + badge(m.get("Momentum","N/A"), "good" if m.get("Momentum")=="IMPROVING" else "bad" if m.get("Momentum")=="DETERIORATING" else "neutral"),
    unsafe_allow_html=True,
)

pos = ", ".join(x["positives"][:4]) or "sin suficientes señales positivas"
neg = ", ".join(x["negatives"][:4]) or "sin alertas macro dominantes"
st.info(f"**Qué está ayudando:** {pos}.  \n**Qué vigilar:** {neg}.")
st.caption("Market regime mide condiciones de mercado; Economic regime describe crecimiento/inflación. Pueden divergir sin ser contradictorios.")

# 2. Core macro only
st.subheader("🌍 Las 5 variables que importan")
section_note("Los scores son 0–100 y se calculan solo con datos disponibles; N/A nunca se convierte en un 50 artificial.")
core = pd.DataFrame([
    ["Growth", _score_text(x["growth"]), _state(x["growth"],"Expansivo","Débil"), "GDP/actividad, empleo, ventas, producción"],
    ["Inflation pressure", _score_text(x["inflation"]), _state(100-x["inflation"] if pd.notna(x["inflation"]) else np.nan,"Benigna","Alta"), "CPI/PCE + breakevens"],
    ["Rates / financial conditions", _score_text(x["policy"]), _state(x["policy"]), "Fed Funds, curva, NFCI"],
    ["Credit", _score_text(x["credit"]), _state(x["credit"],"Saludable","Tensionado"), "HYG vs Treasuries/IG"],
    ["Liquidity", _score_text(x["liquidity"]), _state(x["liquidity"]), "Dólar + condiciones de mercado"],
], columns=["Factor","Score","Estado","Qué representa"])
st.dataframe(core, use_container_width=True, hide_index=True)

# 3. Rates panel
st.subheader("🏦 Tasas, inflación y empleo")
r1,r2,r3,r4,r5 = st.columns(5)
r1.metric("Fed Funds", "N/A" if pd.isna(_num(m,"Fed_Funds")) else f'{_num(m,"Fed_Funds"):.2f}%')
r2.metric("10Y-2Y", "N/A" if pd.isna(_num(m,"10Y_2Y")) else f'{_num(m,"10Y_2Y"):+.2f} pp')
r3.metric("Core CPI YoY", "N/A" if pd.isna(_num(m,"Core_CPI_YoY")) else f'{_num(m,"Core_CPI_YoY"):.2f}%')
r4.metric("Core PCE YoY", "N/A" if pd.isna(_num(m,"Core_PCE_YoY")) else f'{_num(m,"Core_PCE_YoY"):.2f}%')
r5.metric("Unemployment", "N/A" if pd.isna(_num(m,"Unemployment")) else f'{_num(m,"Unemployment"):.2f}%')

r6,r7,r8,r9 = st.columns(4)
r6.metric("Fed Funds Δ6m", "N/A" if pd.isna(_num(m,"Fed_Funds_6m_Change")) else f'{_num(m,"Fed_Funds_6m_Change"):+.2f} pp')
r7.metric("10Y Breakeven", "N/A" if pd.isna(_num(m,"10Y_Breakeven")) else f'{_num(m,"10Y_Breakeven"):.2f}%')
r8.metric("NFCI", "N/A" if pd.isna(_num(m,"NFCI")) else f'{_num(m,"NFCI"):.2f}')
r9.metric("Payroll 3m avg", "N/A" if pd.isna(_num(m,"Payroll_3m_Avg_Change")) else f'{_num(m,"Payroll_3m_Avg_Change"):,.0f}k')

# 4. Translation into sectors
st.subheader("🧭 ¿Qué implica para los sectores?")
section_note("Macro Fit no es una señal de compra. Traduce el entorno macro actual a sensibilidad sectorial; Sector Rotation debe confirmar precio, momentum y relative strength.")
sector_df = _sector_map(x)
st.dataframe(sector_df[["Sector","ETF","Macro Fit","Lectura","Principal driver"]], use_container_width=True, hide_index=True)

fav = sector_df.dropna(subset=["Macro Fit"]).head(3)
weak = sector_df.dropna(subset=["Macro Fit"]).tail(3).sort_values("Macro Fit")
if not fav.empty:
    st.success("**Mejor encaje macro:** " + " · ".join(f'{r.ETF} {int(r["Macro Fit"])}' for _,r in fav.iterrows()))
if not weak.empty:
    st.warning("**Mayor viento en contra macro:** " + " · ".join(f'{r.ETF} {int(r["Macro Fit"])}' for _,r in weak.iterrows()))

# 5. Market confirmation
st.subheader("📈 Confirmación del mercado")
mc1,mc2,mc3,mc4 = st.columns(4)
mc1.metric("Breadth", _score_text(x["breadth"]))
mc2.metric("Risk appetite", _score_text(x["risk"]))
mc3.metric("VIX", "N/A" if pd.isna(_num(m,"VIX")) else f'{_num(m,"VIX"):.2f}')
mc4.metric("HYG/IEF Δ20d", "N/A" if pd.isna(_num(m,"HYG_IEF_20d")) else f'{_num(m,"HYG_IEF_20d"):+.2%}')

with st.expander("Ver breadth por universo"):
    bdf = st.session_state.get("macro_breadth_detail")
    if isinstance(bdf, pd.DataFrame) and not bdf.empty:
        st.dataframe(bdf, use_container_width=True, hide_index=True)

# 6. Raw FRED only when needed
with st.expander("Ver detalle económico / calidad de datos"):
    coverage=float(m.get("Data_Quality_%",0) or 0)
    st.metric("FRED coverage", f"{coverage:.0f}%")
    slow=m.get("Slow_Table")
    if isinstance(slow,pd.DataFrame) and not slow.empty:
        st.dataframe(slow, use_container_width=True, hide_index=True)
    missing=m.get("Missing") or []
    if missing:
        st.warning("Series no disponibles: " + ", ".join(missing))
    if not m.get("FRED_Key_Configured"):
        st.caption("FRED_API_KEY no configurada. La app intenta FRED CSV y cache local como fallback.")

st.subheader("📅 Próximos eventos macro")
cal=get_us_macro_calendar(14)
if cal.empty:
    st.caption("No se recibieron próximas fechas oficiales desde FRED.")
else:
    st.dataframe(cal, use_container_width=True, hide_index=True)

st.caption("Datos económicos: FRED. Las clasificaciones y Macro Fit son modelos internos probabilísticos, no pronósticos ni recomendaciones financieras.")
