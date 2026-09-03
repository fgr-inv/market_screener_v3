
import pandas as pd, streamlit as st
from core.market_data import download_prices,get_sector_etfs,get_macro_symbols
from core.indicators import enrich_indicators
from core.scoring import analyze_symbol,sector_strength_entry
from core.macro import sector_macro_score
from core.economic_data import institutional_macro_snapshot
from core.ui import hero,section_note

hero("Sector Rotation","Separa liderazgo, calidad de entrada y entorno macro.","Sector Allocation Lens")
syms=list(dict.fromkeys(["SPY"]+list(get_sector_etfs().values())+list(get_macro_symbols().values())))
pm=download_prices(syms,period="2y"); spy=pm.get("SPY")
macro=st.session_state.macro_snapshot or institutional_macro_snapshot(pm,breadth_level=50)
rows=[]
for sector,etf in get_sector_etfs().items():
    try:
        raw=pm.get(etf)
        if raw is None or raw.empty: continue
        h=enrich_indicators(raw); r=analyze_symbol(etf,h,spy,sector)
        strength,entry,status=sector_strength_entry(r); mf=sector_macro_score(sector,macro)
        overall=round(.45*strength+.25*entry+.30*mf)
        rows.append({"Sector":sector,"ETF":etf,"Overall":overall,"Strength":strength,"Entry":entry,"Macro":mf,"Status":status,"Trend":r["Trend"],"RS vs SPY 63d %":r["RS_63d_%"],"RSI":r["RSI14"],"Dist EMA62 %":r["Dist_EMA62_%"]})
    except Exception as e:
        st.warning(f"{sector}: {e}")
df=pd.DataFrame(rows).sort_values(["Overall","Strength"],ascending=False)
st.subheader("Ranking"); section_note("Overall = 45% sector strength + 25% entry quality + 30% macro fit.")
st.dataframe(df,width='stretch',hide_index=True)
st.markdown("- **Strength alto + Entry bajo** → líder, pero extendido.\n- **Strength alto + Entry alto** → sector fuerte y comprable.\n- **Overall** prioriza análisis; no es señal automática.")
