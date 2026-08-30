
import numpy as np
import pandas as pd
import streamlit as st

from core.market_data import load_universe, download_prices, get_macro_symbols
from core.breadth import composite_breadth
from core.economic_data import institutional_macro_snapshot, get_slow_macro_snapshot
from core.charts import macro_components_chart
from core.ui import hero, section_note, badge, traffic_tone
from core.utils import fmt_num
from core.macro_calendar import get_us_macro_calendar

def score_text(value):
    return "N/A" if value is None or pd.isna(value) else f"{float(value):.0f}/100"

def value_text(value, unit=""):
    if value is None or pd.isna(value):
        return "N/A"
    if unit in {"%", "pp"}:
        return f"{float(value):.2f}"
    if unit == "thousands":
        return f"{float(value):,.0f}"
    return f"{float(value):.3f}"

hero(
    "Macro Dashboard",
    "Combina una capa rápida de mercado con una capa económica lenta para evitar depender de una sola señal.",
    "Institutional Macro Engine",
)

with st.sidebar:
    drill = st.selectbox(
        "Breadth drill-down",
        ["Composite", "S&P 500", "Nasdaq 100", "Fallback líquido"],
        help="El Macro Score usa siempre el Composite. Este selector solo cambia el detalle.",
    )
    refresh = st.button("🔄 Recalcular Macro", type="primary", use_container_width=True)

if st.session_state.macro_snapshot is None or refresh:
    if refresh:
        get_slow_macro_snapshot.clear()

    with st.status("Calculando Institutional Macro Engine...", expanded=True) as status:
        sp = load_universe("S&P 500")
        ndx = load_universe("Nasdaq 100")
        fb = load_universe("Fallback líquido")

        syms = list(dict.fromkeys(
            sp["Ticker"].tolist()
            + ndx["Ticker"].tolist()
            + fb["Ticker"].tolist()
            + list(get_macro_symbols().values())
        ))

        st.write(f"Descargando {len(syms)} símbolos de mercado...")
        pm = download_prices(syms, period="2y")

        st.write("Calculando breadth multi-horizonte...")
        bscore, bdf = composite_breadth(
            {"S&P 500": sp, "Nasdaq 100": ndx, "Fallback líquido": fb},
            pm,
        )

        st.write("Cargando capa económica FRED...")
        macro = institutional_macro_snapshot(
            pm,
            breadth_level=50 if pd.isna(bscore) else bscore,
        )

        st.session_state.macro_snapshot = macro
        st.session_state.macro_breadth_detail = bdf
        status.update(label="Macro actualizado", state="complete", expanded=False)

m = st.session_state.macro_snapshot
bdf = st.session_state.macro_breadth_detail

if m is None:
    st.info("Presioná Recalcular Macro.")
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Institutional Score", score_text(m.get("Macro_Score")))
c2.metric(
    "Fast Market",
    score_text(m.get("Fast_Macro_Score")),
    None if pd.isna(m.get("Macro_Delta_20d", np.nan)) else f'{m["Macro_Delta_20d"]:+.0f} vs 20d',
)
c3.metric("Slow Economy", score_text(m.get("Slow_Macro_Score")))
c4.metric("Risk Regime", m.get("Institutional_Regime", "N/A"))
c5.metric("Economic data coverage", f'{m.get("Data_Quality_%", 0):.0f}%')

st.markdown(
    badge(m.get("Institutional_Regime", "N/A"), traffic_tone(m.get("Macro_Score", 50)))
    + badge(m.get("Economic_Regime_Slow", "N/A"), "warn")
    + badge(
        m.get("Momentum", "N/A"),
        "good" if m.get("Momentum") == "IMPROVING"
        else "bad" if m.get("Momentum") == "DETERIORATING"
        else "neutral",
    ),
    unsafe_allow_html=True,
)

st.subheader("⚡ Fast market layer")
section_note("Breadth, crédito, volatilidad, tasas, dólar y señales de mercado. Reacciona rápido.")
st.plotly_chart(macro_components_chart(m), use_container_width=True)

fast = pd.DataFrame([
    ["Risk Appetite", m.get("Risk_Appetite")],
    ["Credit", m.get("Credit")],
    ["Rates", m.get("Rates")],
    ["Liquidity", m.get("Liquidity")],
    ["Growth market proxy", m.get("Growth")],
    ["Inflation market proxy", m.get("Inflation_Pressure")],
    ["Breadth", m.get("Breadth")],
], columns=["Component", "Score"])
st.dataframe(fast, use_container_width=True, hide_index=True)

st.subheader("🏛️ Slow economic layer")
section_note(
    "CPI/PCE, empleo, producción, ventas, vivienda, Fed Funds, curva y condiciones financieras. "
    "N/A significa dato no disponible; nunca se reemplaza por 50/100."
)

a, b, c, d = st.columns(4)
a.metric("Slow Growth", score_text(m.get("Slow_Growth")))
b.metric("Inflation Pressure", score_text(m.get("Slow_Inflation_Pressure")))
c.metric("Policy / Conditions", score_text(m.get("Slow_Policy")))
d.metric("Coverage", f'{m.get("Data_Quality_%", 0):.0f}%')

slow = m.get("Slow_Table")
if isinstance(slow, pd.DataFrame) and not slow.empty:
    display = slow.copy()
    display["Value"] = [
        value_text(v, u) for v, u in zip(display["Value"], display["Unit"])
    ]
    display["Previous"] = [
        value_text(v, u) for v, u in zip(display["Previous"], display["Unit"])
    ]
    display["Updated"] = display["Updated"].apply(
        lambda x: "N/A" if x is None or pd.isna(x) else pd.Timestamp(x).strftime("%Y-%m-%d")
    )
    st.dataframe(
        display[["Indicator", "Value", "Previous", "Trend", "Unit", "Status", "Updated", "Source"]],
        use_container_width=True,
        hide_index=True,
    )

coverage = float(m.get("Data_Quality_%", 0) or 0)
missing = m.get("Missing") or []

if coverage == 0:
    st.error(
        "No se pudo cargar la capa económica. El Institutional Score está usando solamente la capa rápida de mercado; "
        "no se está interpretando 50/100 como un dato neutral."
    )
    if not m.get("FRED_Key_Configured"):
        st.info(
            "Recomendado: configurá una FRED_API_KEY gratuita en Streamlit Secrets. "
            "La app también intenta FRED CSV sin key y usa el último cache válido si existe."
        )
        st.code('FRED_API_KEY = "tu_api_key"', language="toml")
elif missing:
    st.warning(
        f"Cobertura económica {coverage:.0f}%. Series no disponibles: "
        + ", ".join(missing)
        + ". Los scores se recalculan solo con los factores disponibles."
    )
else:
    st.success("Capa económica cargada correctamente desde FRED.")
st.caption('This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.')

st.subheader("Breadth")
section_note("Composite fijo para el Macro Score; el selector lateral solo sirve para drill-down.")
st.dataframe(
    bdf if drill == "Composite" else bdf[bdf["Universe"] == drill],
    use_container_width=True,
    hide_index=True,
)

st.subheader("Key market signals")

def _fmt_level(value):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.2f}"


def _fmt_pct_change(value):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):+.2%}"

def _fmt_bps(value):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):+.0f} bps"


signals = pd.DataFrame([
    ["VIX", _fmt_level(m.get("VIX")), "level"],
    ["Copper / Gold Δ20d", _fmt_pct_change(m.get("Copper_Gold_20d")), "%"],
    ["Oil Δ20d", _fmt_pct_change(m.get("Oil_20d")), "%"],
    ["US10Y Δ20d", _fmt_bps(m.get("US10Y_20d_bps")), "bps"],
    ["Dollar Δ20d", _fmt_pct_change(m.get("Dollar_20d")), "%"],
    ["HYG / IEF Δ20d", _fmt_pct_change(m.get("HYG_IEF_20d")), "%"],
], columns=["Indicator", "Value", "Unit"])
st.dataframe(signals, use_container_width=True, hide_index=True)

st.subheader("📅 Upcoming Macro Events")
cal = get_us_macro_calendar(14)
if cal.empty:
    st.caption(
        "No upcoming FRED release dates were returned. Ensure FRED_API_KEY is configured; "
        "this free calendar shows official release dates, not paid consensus forecasts."
    )
else:
    st.dataframe(cal, use_container_width=True, hide_index=True)

st.caption(
    "Institutional Score = 70% market layer + 30% slow economy when the slow layer is available. "
    "If economic data is unavailable, the system falls back to the market layer and marks coverage accordingly."
)
