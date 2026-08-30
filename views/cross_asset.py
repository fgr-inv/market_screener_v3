import pandas as pd, streamlit as st
from core.market_data import download_prices,get_cross_asset_symbols,classify_symbol,get_macro_symbols
from core.indicators import enrich_indicators
from core.asset_models import analyze_asset, normalize_asset_type
from core.asset_fundamentals import get_asset_context
from core.economic_data import institutional_macro_snapshot
from core.ui import hero, section_note

hero('Cross Asset','Compara capital rotation sin forzar a equities, crypto, commodities, bonos y FX al mismo modelo.','Capital Rotation')
mapping=get_cross_asset_symbols(); symbols=list(dict.fromkeys(list(mapping.values())+['SPY']+list(get_macro_symbols().values())))
pm=download_prices(symbols,period='5y'); spy=pm.get('SPY'); macro=st.session_state.macro_snapshot or institutional_macro_snapshot(pm,breadth_level=50)
rows=[]
for name,sym in mapping.items():
    try:
        typ=normalize_asset_type(classify_symbol(sym)); h=enrich_indicators(pm[sym]); r=analyze_asset(sym,h,spy,name,typ); ctx=get_asset_context(sym,typ,pm,macro)
        rows.append({'Asset':name,'Symbol':sym,'Type':typ,'Model':r.get('Analysis_Model'),'Trend':r['Trend'],'Technical':r['Technical_Score'],
                     'Entry':r['Entry_Score'],'Risk':r['Risk_Score'],'Context':ctx.get('Asset_Context_Score'),
                     'RS vs SPY 63d %':r['RS_63d_%'],'RSI':r['RSI14'],'Setup':r['Setup']})
    except Exception: pass
df=pd.DataFrame(rows)
if not df.empty: df=df.sort_values(['Technical','Context'],ascending=False,na_position='last')
st.dataframe(df,use_container_width=True,hide_index=True)
section_note('Los scores son comparables en escala 0–100, pero sus drivers cambian por clase de activo. “Trend” en un yield index describe la tasa, no el precio de un bono.')
