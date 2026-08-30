import numpy as np
import pandas as pd

from core.asset_fundamentals import equity_context_score
from core.valuation import add_peer_valuation_scores


def test_equity_context_score_is_observed_and_not_nan():
    row=pd.Series({'Sector_Score':70,'Macro_Fit':60,'RS_Percentile':80,'Trend_Score':90})
    out=equity_context_score(row)
    assert out['Asset_Context_Score']==71
    assert 'sector strength' in out['Framework'].lower()


def test_equity_context_score_renormalizes_missing_inputs():
    row=pd.Series({'Sector_Score':80,'Macro_Fit':60,'RS_Percentile':np.nan,'Trend_Score':np.nan})
    out=equity_context_score(row)
    assert out['Asset_Context_Score']==70


def test_pe_sector_percentile_uses_sector_when_peer_sample_exists():
    df=pd.DataFrame({
        'Sector':['Tech','Tech','Tech'],
        'Forward_PE':[10.0,20.0,30.0],
        'Valuation_Score':[np.nan,np.nan,np.nan],
    })
    out=add_peer_valuation_scores(df)
    assert out['PE_Sector_Percentile'].notna().all()
    assert set(out['PE_Percentile_Source'])=={'SECTOR'}
    assert out.loc[0,'PE_Sector_Percentile'] > out.loc[2,'PE_Sector_Percentile']


def test_pe_percentile_falls_back_to_enriched_universe_for_singleton_sector():
    df=pd.DataFrame({
        'Sector':['Tech','Finance','Energy'],
        'Forward_PE':[10.0,20.0,30.0],
        'Valuation_Score':[np.nan,np.nan,np.nan],
    })
    out=add_peer_valuation_scores(df)
    assert out['PE_Sector_Percentile'].notna().all()
    assert set(out['PE_Percentile_Source'])=={'UNIVERSE_FALLBACK'}


def test_separate_screener_pages_exist():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    for name in ['technical_screener.py','fundamental_screener.py','combined_screener.py','screener_shared.py']:
        assert (root/'views'/name).exists()


def test_specialized_screener_persists_mode_specific_results():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    src=(root/'views'/'screener_shared.py').read_text(encoding='utf-8')
    assert "st.session_state[f'scan_results_{_mode_key}']=results.copy()" in src
    assert "_mode_key=str(analysis_mode).lower().replace('é','e')" in src
