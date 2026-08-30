import numpy as np
import pandas as pd
from core.config import SECTOR_ALIASES
from core.utils import clamp
from core.model_registry import get_active_model
from core.quality_weighting import available_weighted_score
from core.asset_models import normalize_asset_type


def normalize_sector(s):
    if s is None or pd.isna(s): return 'Other'
    s=str(s).strip(); return SECTOR_ALIASES.get(s,s)


def add_cross_sectional_metrics(df):
    out=df.copy()
    rs=out['RS_63d_%'].replace([np.inf,-np.inf],np.nan)
    out['RS_Percentile']=(rs.rank(pct=True,method='average')*100).round(0)
    out['Trend_Percentile']=(out['Trend_Score'].rank(pct=True,method='average')*100).round(0)
    return out


def _rr_adjust(rr):
    if pd.isna(rr): return 0
    rr=float(rr)
    return 4 if rr>=2.5 else -14 if rr<1.25 else -9 if rr<1.5 else -5 if rr<2 else 0


def _event_penalty(r):
    risk=str(r.get('Event_Risk','')).upper()
    return -15 if risk=='HIGH' else -6 if risk=='ELEVATED' else 0


def preliminary_score(r):
    values={
        'trend':r.get('Trend_Score',np.nan),'entry':r.get('Entry_Score',np.nan),
        'relative_strength':r.get('RS_Percentile',np.nan),'risk':r.get('Risk_Score',np.nan),
        'sector':r.get('Sector_Score',np.nan),'macro':r.get('Macro_Fit',np.nan),
    }
    weights={'trend':.25,'entry':.30,'relative_strength':.15,'risk':.10,'sector':.10,'macro':.10}
    score,coverage,_=available_weighted_score(values,weights,neutral_if_empty=50)
    score+=_rr_adjust(r.get('RR',np.nan))
    if bool(r.get('Scan_Extended_Trim',False)): score-=8
    return int(clamp(round(score)))


def opportunity_components(r):
    model=get_active_model(); configured=model.get('weights',{})
    defaults={'quality':.18,'trend':.16,'entry':.22,'relative_strength':.12,'sector':.08,'macro':.08,'revisions':.10,'valuation':.06}
    model_key=str(r.get('Equity_Model_Key','generic'))
    # Professional opportunity weights change with the business model. A bank,
    # biotech, SaaS company and copper miner should not have identical factor weights.
    industry_weights={
        'saas':{'quality':.20,'trend':.14,'entry':.18,'relative_strength':.10,'sector':.06,'macro':.06,'revisions':.17,'valuation':.09},
        'cybersecurity':{'quality':.20,'trend':.14,'entry':.18,'relative_strength':.10,'sector':.06,'macro':.06,'revisions':.17,'valuation':.09},
        'ai_accelerators':{'quality':.20,'trend':.15,'entry':.18,'relative_strength':.11,'sector':.07,'macro':.07,'revisions':.15,'valuation':.07},
        'memory':{'quality':.15,'trend':.15,'entry':.17,'relative_strength':.10,'sector':.10,'macro':.12,'revisions':.12,'valuation':.11},
        'money_center_bank':{'quality':.19,'trend':.12,'entry':.17,'relative_strength':.08,'sector':.09,'macro':.13,'revisions':.10,'valuation':.12},
        'regional_bank':{'quality':.20,'trend':.11,'entry':.16,'relative_strength':.07,'sector':.10,'macro':.14,'revisions':.09,'valuation':.13},
        'biotech':{'quality':.17,'trend':.16,'entry':.18,'relative_strength':.11,'sector':.07,'macro':.05,'revisions':.21,'valuation':.05},
        'pharma':{'quality':.21,'trend':.13,'entry':.18,'relative_strength':.08,'sector':.07,'macro':.06,'revisions':.16,'valuation':.11},
        'ep':{'quality':.15,'trend':.14,'entry':.17,'relative_strength':.09,'sector':.10,'macro':.15,'revisions':.08,'valuation':.12},
        'copper_miner':{'quality':.14,'trend':.15,'entry':.17,'relative_strength':.10,'sector':.10,'macro':.17,'revisions':.06,'valuation':.11},
        'gold_miner':{'quality':.14,'trend':.15,'entry':.17,'relative_strength':.10,'sector':.10,'macro':.17,'revisions':.06,'valuation':.11},
        'regulated_utility':{'quality':.20,'trend':.12,'entry':.18,'relative_strength':.07,'sector':.08,'macro':.14,'revisions':.08,'valuation':.13},
        'reit_general':{'quality':.18,'trend':.12,'entry':.18,'relative_strength':.07,'sector':.09,'macro':.14,'revisions':.08,'valuation':.14},
        'data_center_reit':{'quality':.20,'trend':.13,'entry':.17,'relative_strength':.08,'sector':.08,'macro':.12,'revisions':.11,'valuation':.11},
    }
    defaults=industry_weights.get(model_key,defaults)
    weights={k:float(configured.get(k,defaults[k])) for k in defaults}
    # Confidence is deliberately NOT an alpha factor in V8. It controls trust/action gating.
    values={
        'quality':r.get('Quality_Score',np.nan),
        'trend':r.get('Trend_Score',np.nan),
        'entry':r.get('Entry_Score',np.nan),
        'relative_strength':r.get('RS_Percentile',np.nan),
        'sector':r.get('Sector_Score',np.nan),
        'macro':r.get('Macro_Fit',np.nan),
        'revisions':r.get('Revision_Score',np.nan),
        'valuation':r.get('Valuation_Score',np.nan),
    }
    return values,weights


def opportunity_score(r):
    # A stock opportunity model requires a company-quality observation. Other asset classes
    # use their own context scores rather than pretending missing fundamentals are neutral.
    if pd.isna(r.get('Quality_Score',np.nan)):
        return np.nan
    values,weights=opportunity_components(r)
    score,coverage,used=available_weighted_score(values,weights)
    if pd.isna(score): return np.nan
    score+=_rr_adjust(r.get('RR',np.nan))+_event_penalty(r)
    if bool(r.get('Scan_Extended_Trim',False)): score-=10
    # Very sparse factor coverage is explicitly penalized rather than filled with neutral 50s.
    if coverage<60: score-=8
    return int(clamp(round(score)))


def model_coverage(r):
    values,weights=opportunity_components(r)
    _,coverage,used=available_weighted_score(values,weights)
    return round(coverage,1),', '.join(used)


def best_stock_score(r):
    if pd.isna(r.get('Quality_Score',np.nan)): return np.nan
    values={
        'quality':r.get('Quality_Score',np.nan),'trend':r.get('Trend_Score',np.nan),
        'rs':r.get('RS_Percentile',np.nan),'revisions':r.get('Revision_Score',np.nan),
        'valuation':r.get('Valuation_Score',np.nan),'sector':r.get('Sector_Score',np.nan),'macro':r.get('Macro_Fit',np.nan),
    }
    weights={'quality':.28,'trend':.22,'rs':.18,'revisions':.10,'valuation':.08,'sector':.07,'macro':.07}
    s,coverage,_=available_weighted_score(values,weights)
    if pd.isna(s): return np.nan
    if coverage<60: s-=6
    return int(clamp(round(s)))



def asset_opportunity_components(r):
    typ=normalize_asset_type(r.get('Asset_Type','Acción'))
    context=r.get('Asset_Context_Score',r.get('Macro_Fit',np.nan))
    rs=r.get('RS_Percentile',np.nan)
    common={
        'trend':r.get('Trend_Score',np.nan),'entry':r.get('Entry_Score',np.nan),
        'risk':r.get('Risk_Score',np.nan),'context':context,'relative_strength':rs,
        'cycle':r.get('Cycle_Score',r.get('Weekly_Cycle_Score',np.nan)),
        'long_term':r.get('Long_Term_Opportunity_Score',np.nan),
    }
    weights={
        'Cripto':{'long_term':.28,'trend':.16,'entry':.12,'risk':.10,'context':.18,'relative_strength':.06,'cycle':.10},
        'Commodity':{'trend':.24,'entry':.18,'risk':.15,'context':.33,'relative_strength':.10},
        'Bono/Tasa':{'trend':.22,'entry':.16,'risk':.17,'context':.35,'relative_strength':.10},
        'Forex':{'trend':.26,'entry':.20,'risk':.18,'context':.26,'relative_strength':.10},
        'Índice':{'trend':.30,'entry':.20,'risk':.15,'context':.20,'relative_strength':.15},
        'ETF':{'trend':.28,'entry':.20,'risk':.15,'context':.22,'relative_strength':.15},
        'Otro':{'trend':.30,'entry':.25,'risk':.20,'context':.15,'relative_strength':.10},
    }.get(typ,{'trend':.30,'entry':.25,'risk':.20,'context':.15,'relative_strength':.10})
    return common,weights


def asset_opportunity_score(r):
    typ=normalize_asset_type(r.get('Asset_Type','Acción'))
    if typ=='Acción': return opportunity_score(r)
    values,weights=asset_opportunity_components(r)
    score,coverage,_=available_weighted_score(values,weights,neutral_if_empty=50)
    score+=_rr_adjust(r.get('RR',np.nan))
    if bool(r.get('Scan_Extended_Trim',False)): score-=10
    if coverage<55: score-=6
    return int(clamp(round(score)))



def fundamental_opportunity_score(r):
    """Fundamental opportunity: quality + valuation + revisions + resilience.

    This intentionally excludes technical timing. Missing optional inputs are
    reweighted instead of imputed; quality is required to avoid false precision.
    """
    if pd.isna(r.get('Quality_Score',np.nan)):
        return np.nan
    values={
        'quality':r.get('Quality_Score',np.nan),
        'valuation':r.get('Valuation_Score',np.nan),
        'revisions':r.get('Revision_Score',np.nan),
        'resilience':r.get('Financial_Resilience_Score',np.nan),
    }
    weights={'quality':.40,'valuation':.35,'revisions':.20,'resilience':.05}
    s,coverage,_=available_weighted_score(values,weights)
    if pd.isna(s): return np.nan
    if coverage<60: s-=4
    return int(clamp(round(s)))


def fundamental_leader_score(r):
    """Business-quality leadership score, deliberately independent of technical timing.

    A leader can be expensive today. The score emphasizes durable company quality,
    balance-sheet resilience, earnings quality and capital allocation.
    """
    if pd.isna(r.get('Quality_Score',np.nan)):
        return np.nan
    values={
        'quality':r.get('Quality_Score',np.nan),
        'resilience':r.get('Financial_Resilience_Score',np.nan),
        'earnings_quality':r.get('Earnings_Quality_Score',np.nan),
        'capital_allocation':r.get('Capital_Allocation_Score',np.nan),
        'management':r.get('Management_Execution_Score',np.nan),
    }
    weights={'quality':.55,'resilience':.20,'earnings_quality':.10,'capital_allocation':.10,'management':.05}
    s,coverage,_=available_weighted_score(values,weights)
    if pd.isna(s): return np.nan
    if coverage<55: s-=4
    return int(clamp(round(s)))

def asset_model_coverage(r):
    typ=normalize_asset_type(r.get('Asset_Type','Acción'))
    if typ=='Acción': return model_coverage(r)
    values,weights=asset_opportunity_components(r)
    _,coverage,used=available_weighted_score(values,weights,neutral_if_empty=50)
    return round(coverage,1),', '.join(used)

def action_label(r):
    trend=float(r.get('Trend_Score',0) or 0); entry=float(r.get('Entry_Score',0) or 0)
    q=r.get('Quality_Score',np.nan); opp=r.get('Opportunity_Score',np.nan); rr=r.get('RR',np.nan)
    event=str(r.get('Event_Risk','')).upper(); conf=r.get('Confidence_Score',np.nan); coverage=float(r.get('Model_Coverage_%',100) or 0)
    if event=='HIGH': return 'EVENT RISK — WAIT'
    if pd.notna(conf) and float(conf)<55: return 'LOW CONFIDENCE — WAIT'
    if coverage<55 and pd.notna(opp): return 'INCOMPLETE DATA — WAIT'
    typ=normalize_asset_type(r.get('Asset_Type','Acción'))
    if typ=='Cripto':
        lt=float(r.get('Long_Term_Opportunity_Score',0) or 0); regime=str(r.get('Crypto_Regime','')); lev=str(r.get('Leverage_Risk',''))
        if lt>=78 and entry>=62 and trend>=65: return 'ACCUMULATE / BUY IN TRANCHES'
        if lt>=75 and trend>=65: return 'BULLISH — WAIT / SCALE IN'
        if r.get('Entry_Type','').startswith('BREAKOUT') and entry>=60: return 'BREAKOUT / PRICE DISCOVERY'
        if lev=='HIGH' and str(r.get('Overextension_Risk',''))=='HIGH': return 'LEVERAGE RISK — WAIT'
    if bool(r.get('Scan_Extended_Trim',False)): return 'EXTENDED / TRIM'
    if bool(r.get('Scan_Breakout_Base',False)) and entry>=60 and pd.notna(rr) and float(rr)>=1.5: return 'BREAKOUT'
    if pd.notna(opp):
        typ=normalize_asset_type(r.get('Asset_Type','Acción'))
        if float(opp)>=80 and trend>=70 and entry>=68 and (pd.isna(rr) or float(rr)>=1.5) and coverage>=65: return 'BUY ZONE'
        if typ=='Acción' and pd.notna(q) and float(q)>=75 and trend>=75 and (entry<60 or (pd.notna(rr) and float(rr)<1.5)): return 'GREAT STOCK — WAIT'
        if float(opp)>=70 and trend>=60: return 'WATCH'
    if float(r.get('Preliminary_Score',0) or 0)>=75 and entry>=65: return 'WATCH'
    return 'AVOID' if trend<45 else 'WAIT'


def attach_scores(df):
    out=df.copy()
    for col in ['Quality_Score','Revision_Score','Valuation_Score','Confidence_Score']:
        if col not in out.columns: out[col]=np.nan
    if 'Event_Risk' not in out.columns: out['Event_Risk']='N/D'
    out['Preliminary_Score']=out.apply(preliminary_score,axis=1)
    coverage=out.apply(lambda r:asset_model_coverage(r),axis=1)
    out['Model_Coverage_%']=[x[0] for x in coverage]
    out['Available_Factors']=[x[1] for x in coverage]
    out['Data_Confidence_Score']=out['Confidence_Score']
    blended=[]
    for _,r in out.iterrows():
        raw=r.get('Data_Confidence_Score',np.nan); cov=float(r.get('Model_Coverage_%',0) or 0)
        blended.append(round(.65*float(raw)+.35*cov) if pd.notna(raw) else round(cov))
    out['Confidence_Score']=[int(clamp(x)) for x in blended]
    out['Opportunity_Score']=out.apply(asset_opportunity_score,axis=1)
    out['Best_Stock_Score']=out.apply(best_stock_score,axis=1)
    out['Fundamental_Opportunity_Score']=out.apply(fundamental_opportunity_score,axis=1)
    out['Fundamental_Leader_Score']=out.apply(fundamental_leader_score,axis=1)
    out['Action']=out.apply(action_label,axis=1)
    return out
