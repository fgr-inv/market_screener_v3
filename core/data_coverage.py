"""Data-quality and coverage layer for professional asset analysis.

The goal is not to manufacture precision when specialist data are unavailable.
Instead, each asset/industry declares the metrics a professional analyst would
normally want, what the current app can observe, and which optional provider can
close the gap.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from core.asset_models import normalize_asset_type, effective_asset_type, CREDIT_ETFS, YIELD_INDEXES
from core.utils import clamp
from core.professional_equity_engine import classify_equity_subindustry


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        
        u=value.strip().upper()
        return bool(u) and u not in {'N/A', 'N/D', 'NONE', 'UNAVAILABLE'} and not u.startswith('REQUIRES')
    try:
        return bool(pd.notna(value))
    except Exception:
        return True


def _ratio_present(mapping: dict, keys: list[str]) -> tuple[int, int]:
    return sum(1 for k in keys if _present(mapping.get(k))), len(keys)


def _coverage_label(score: float) -> str:
    if score >= 85:
        return 'HIGH'
    if score >= 70:
        return 'GOOD'
    if score >= 50:
        return 'PARTIAL'
    return 'LOW'


# Metrics in the public yfinance corporate snapshot that are useful across most companies.
EQUITY_CORE = [
    'Market_Cap', 'Revenue_Growth', 'Earnings_Growth', 'Gross_Margin',
    'Operating_Margin', 'ROE', 'FCF', 'Total_Debt', 'Total_Cash',
    'Forward_PE', 'Price_to_Book', 'EV_EBITDA',
]

# Specialist KPI requirements are intentionally explicit. Most are not available from
# the current public company-info endpoint; their absence must reduce coverage.
SPECIALIST = {
    'banks': {
        'critical': ['NIM', 'CET1', 'Deposit_Growth', 'Deposit_Mix', 'NCO_Ratio', 'ROTCE', 'Tangible_Book_Value'],
        'providers': ['SEC EDGAR/XBRL (free)', 'FMP free', 'specialist paid feed only for remaining non-standard KPIs'],
    },
    'insurance': {
        'critical': ['Combined_Ratio', 'Reserve_Adequacy', 'Premium_Growth', 'Investment_Yield', 'Book_Value_Growth'],
        'providers': ['SEC EDGAR/XBRL (free)', 'FMP free', 'specialist paid feed only for remaining non-standard KPIs'],
    },
    'reit': {
        'critical': ['FFO', 'AFFO', 'NAV', 'Occupancy', 'Same_Store_NOI', 'Debt_Maturity_Profile'],
        'providers': ['SEC/10-Q parsing', 'REIT supplemental filings', 'S&P Capital IQ / FactSet / Bloomberg'],
    },
    'semiconductor': {
        'critical': ['Inventory_Days', 'Utilization', 'Capex', 'Product_Mix', 'End_Market_Mix'],
        'providers': ['SEC EDGAR/XBRL (free)', 'FMP free', 'company earnings supplements for non-standard KPIs'],
    },
    'software': {
        'critical': ['ARR', 'RPO', 'NRR', 'Billings_Growth', 'SBC', 'FCF_Margin'],
        'providers': ['SEC filings', 'company earnings supplements', 'FMP/Premium fundamentals'],
    },
    'biotech': {
        'critical': ['Pipeline', 'Trial_Phase', 'Probability_of_Success', 'Cash_Runway', 'Dilution_Risk', 'rNPV'],
        'providers': ['SEC EDGAR/XBRL (free)', 'ClinicalTrials.gov v2 (free)', 'openFDA (free)', 'specialist dataset only for rNPV/probability-of-success'],
    },
    'drug': {
        'critical': ['Pipeline', 'Patent_Cliffs', 'Product_Concentration', 'R_and_D_Productivity'],
        'providers': ['SEC EDGAR/XBRL (free)', 'ClinicalTrials.gov v2 (free)', 'openFDA (free)', 'company filings for patent cliffs'],
    },
    'oil': {
        'critical': ['Production', 'Reserves', 'Realized_Price', 'Lifting_Cost', 'Hedge_Book', 'FCF_Breakeven'],
        'providers': ['SEC EDGAR/XBRL (free)', 'EIA_API_KEY (free macro energy)', 'company operating supplements for reserves/hedges'],
    },
    'utility': {
        'critical': ['Rate_Base_Growth', 'Allowed_ROE', 'Regulatory_Jurisdiction', 'Capex_Funding', 'Dividend_Coverage'],
        'providers': ['SEC/regulatory filings', 'company supplements', 'S&P Capital IQ / FactSet / Bloomberg'],
    },
    'retail': {
        'critical': ['Comparable_Sales', 'Traffic', 'Ticket', 'Inventory_Turns', 'Store_Productivity'],
        'providers': ['company earnings supplements', 'SEC filings', 'premium consumer dataset'],
    },
    'auto': {
        'critical': ['Unit_Volume', 'Pricing_Mix', 'Incentives', 'Inventory', 'EBIT_Margin', 'Captive_Finance_Credit'],
        'providers': ['company deliveries/filings', 'industry registration data', 'premium auto dataset'],
    },
    'homebuilder': {
        'critical': ['Orders', 'Backlog', 'Cancellations', 'Community_Count', 'Land_Position'],
        'providers': ['SEC filings', 'company earnings supplements'],
    },
    'telecom': {
        'critical': ['Subscribers', 'Net_Adds', 'ARPU', 'Churn', 'Capex_Intensity'],
        'providers': ['company earnings supplements', 'SEC filings'],
    },
    'media': {
        'critical': ['Subscribers_or_Users', 'ARPU', 'Engagement', 'Ad_Monetization', 'Content_Spend'],
        'providers': ['company earnings supplements', 'SEC filings'],
    },
    'industrial': {
        'critical': ['Orders', 'Backlog', 'Book_to_Bill', 'Pricing_vs_Inputs', 'FCF_Conversion'],
        'providers': ['company earnings supplements', 'SEC filings'],
    },
    'mining': {
        'critical': ['Production', 'Grade', 'AISC', 'Reserves', 'Capex'],
        'providers': ['company operating reports', 'SEC filings', 'commodity specialist dataset'],
    },
    'airline': {
        'critical': ['RASM', 'CASM', 'Load_Factor', 'Capacity', 'Fuel_Cost'],
        'providers': ['company earnings supplements', 'DOT/industry data'],
    },
}


def industry_lens_key(industry: str = '') -> str:
    text = str(industry or '').lower()
    aliases = [
        ('bank', 'banks'), ('insurance', 'insurance'), ('reit', 'reit'),
        ('semiconductor', 'semiconductor'), ('software', 'software'), ('biotech', 'biotech'),
        ('drug', 'drug'), ('pharma', 'drug'), ('oil', 'oil'), ('exploration', 'oil'),
        ('utility', 'utility'), ('retail', 'retail'), ('auto', 'auto'),
        ('homebuilder', 'homebuilder'), ('telecom', 'telecom'), ('media', 'media'),
        ('industrial', 'industrial'), ('mining', 'mining'), ('airline', 'airline'),
    ]
    for token, key in aliases:
        if token in text:
            return key
    return ''


def equity_data_coverage(fund: dict | None, sector: str, industry: str = '', ticker: str = '') -> dict:
    fund = fund or {}
    if fund.get('error'):
        return {
            'Data_Coverage_Score': 0, 'Data_Coverage_Label': 'LOW',
            'Core_Data_Coverage_%': 0.0, 'Specialist_Data_Coverage_%': 0.0,
            'Available_Data': [], 'Missing_Critical_Data': EQUITY_CORE.copy(),
            'Missing_Useful_Data': [],
            'Recommended_Data_Sources': ['Yahoo Finance/basic fundamentals unavailable in this run'],
            'Coverage_Note': 'Corporate fundamentals could not be retrieved.',
            'Equity_Model': 'Unknown', 'Equity_Model_Key': 'unknown',
        }

    core_have, core_total = _ratio_present(fund, EQUITY_CORE)
    core_cov = 100.0 * core_have / core_total if core_total else 100.0
    profile = classify_equity_subindustry(sector, industry, ticker)
    critical = list(profile.kpis)
    spec_have, spec_total = _ratio_present(fund, critical)
    spec_cov = 100.0 * spec_have / spec_total if spec_total else 100.0

    # Specialist metrics matter more where generic GAAP ratios are structurally weak:
    # banks/REITs/biotech/commodity producers. The score reports data completeness,
    # not model quality, and never imputes unavailable KPIs.
    specialist_heavy = profile.key in {
        'money_center_bank','regional_bank','insurance','consumer_finance',
        'reit_general','data_center_reit','industrial_reit','residential_reit','retail_reit','healthcare_reit','tower_reit',
        'biotech','pharma','ep','integrated_oil','oil_services','midstream','refining','lng',
        'copper_miner','gold_miner','steel','chemicals','materials_general'
    }
    spec_weight = .50 if specialist_heavy else .40 if profile.key != 'generic' else .20
    score = (1-spec_weight)*core_cov + spec_weight*spec_cov

    missing_critical = [k for k in critical if not _present(fund.get(k))]
    missing_core = [k for k in EQUITY_CORE if not _present(fund.get(k))]
    available = [k for k in EQUITY_CORE if _present(fund.get(k))] + [k for k in critical if _present(fund.get(k))]

    providers = ['SEC EDGAR/XBRL (free)', 'Yahoo Finance', 'FMP free if configured']
    if profile.key in {'biotech','pharma'}:
        providers += ['ClinicalTrials.gov v2 (free)', 'openFDA (free)']
    if profile.sector in {'Energy','Materials'}:
        providers += ['EIA/CFTC public data for commodity context', 'company operating supplements for non-standard KPIs']
    elif profile.key.startswith('reit') or 'reit' in profile.key:
        providers += ['company REIT supplemental filings for FFO/AFFO/NAV/NOI']
    else:
        providers += ['company earnings supplements / 10-Q / 10-K for non-standard operating KPIs']

    note=(
        f"{profile.label} model. Specialist KPIs carry {int(spec_weight*100)}% of data coverage. "
        "Missing non-standard KPIs are disclosed and never estimated from unrelated accounting fields."
    )
    return {
        'Data_Coverage_Score': int(clamp(round(score))),
        'Data_Coverage_Label': _coverage_label(score),
        'Core_Data_Coverage_%': round(core_cov, 1),
        'Specialist_Data_Coverage_%': round(spec_cov, 1),
        'Available_Data': list(dict.fromkeys(available)),
        'Missing_Critical_Data': missing_critical,
        'Missing_Useful_Data': missing_core,
        'Recommended_Data_Sources': list(dict.fromkeys(providers)),
        'Coverage_Note': note,
        'Equity_Model': profile.label,
        'Equity_Model_Key': profile.key,
        'Preferred_Valuation_Methods': list(profile.valuation),
        'Key_Catalysts': list(profile.catalysts),
        'Key_Risks': list(profile.risks),
    }


def asset_data_coverage(ticker: str, asset_type: str, context: dict | None = None, macro: dict | None = None) -> dict:
    typ = effective_asset_type(ticker, normalize_asset_type(asset_type))
    context = context or {}
    macro = macro or {}
    t = str(ticker).upper()

    if typ == 'Cripto':
        required = ['20d_Return', '63d_Return', 'BTC_Dominance']
        model = context.get('Crypto_Model', 'General Token')
        specialist_by_model = {
            'Bitcoin': ['Funding_Rate','Open_Interest','Basis','Hash_Rate','Difficulty','Miner_Revenue_USD','BTC_Mined_24h','Realized_Price','MVRV','SOPR','ETF_Flows'],
            'Ethereum': ['Funding_Rate','Open_Interest','Basis','TVL_$','Staking_Ratio','Net_Issuance','ETH_Burn','Blob_Fees','ETF_Flows'],
            'L1/L2': ['Funding_Rate','Open_Interest','TVL_$','FDV_to_MCap','Active_Users','Network_Fees','Token_Unlocks'],
            'DeFi': ['Protocol_TVL_$','FDV_to_MCap','Protocol_Fees','Protocol_Revenue','Tokenholder_Revenue','Bad_Debt','Token_Unlocks'],
            'Stablecoin': ['Market_Cap_$','24h_Volume_$','Peg_Deviation_History','Reserve_Composition','Attestation_Freshness','DEX_Liquidity'],
            'Speculative Token': ['FDV_to_MCap','24h_Volume_$','Holder_Concentration','Exchange_Liquidity_Depth','Token_Unlocks'],
        }
        specialist = specialist_by_model.get(model, ['Funding_Rate','Open_Interest','FDV_to_MCap','Holder_Concentration','Token_Unlocks'])
        providers = ['Binance/Bybit/OKX public APIs', 'CoinGecko Demo/Public', 'Blockchain.com public data (BTC)', 'DefiLlama public data', 'specialist paid/on-chain provider only for fields unavailable reliably for free']
        core_have, core_total = _ratio_present(context, required)
        spec_have, spec_total = _ratio_present(context, specialist)
        core_cov = 100 * core_have / core_total
        spec_cov = 100 * spec_have / spec_total
        score = .45 * core_cov + .55 * spec_cov
        note = f'{model} uses a dedicated crypto coverage template; unavailable on-chain/tokenomics fields reduce confidence and are never inferred from price.'
    elif typ == 'Bono/Tasa':
        required = ['US10Y_20d_bps'] if t not in YIELD_INDEXES else ['Yield_20d_bps']
        specialist = ['Yield_to_Worst', 'Effective_Duration', 'Convexity', 'OAS', 'Spread_Duration', 'Curve_Key_Rates']
        if t not in CREDIT_ETFS:
            specialist = ['Yield_to_Worst', 'Effective_Duration', 'Convexity', 'Curve_Key_Rates', 'Real_Yield']
        providers = ['FRED_API_KEY', 'Treasury/ICE/Bloomberg/FactSet fixed-income feed']
        core_have, core_total = _ratio_present(context, required)
        spec_have, spec_total = _ratio_present(context, specialist)
        core_cov = 100 * core_have / core_total
        spec_cov = 100 * spec_have / spec_total
        score = .45 * core_cov + .55 * spec_cov
        note = 'Fixed income needs duration/curve and, for credit, OAS/default-risk metrics; price-only analysis is incomplete.'
    elif typ == 'Commodity':
        required = ['20d_Return', '63d_Return', 'Dollar_20d']
        specialist = ['Term_Structure', 'Inventory_Signal', 'COT_Signal']
        providers = ['EIA_API_KEY (energy)', 'CFTC public COT', 'NASDAQ_DATA_LINK_API_KEY / futures data provider']
        core_have, core_total = _ratio_present(context, required)
        spec_have, spec_total = _ratio_present(context, specialist)
        core_cov = 100 * core_have / core_total
        spec_cov = 100 * spec_have / spec_total
        score = .55 * core_cov + .45 * spec_cov
        note = 'Commodity analysis should include curve, inventories and positioning; price/macro alone is not enough.'
    elif typ == 'Forex':
        required = ['20d_Return', '63d_Return', 'Dollar_20d']
        specialist = ['Base_Policy_Rate', 'Quote_Policy_Rate', 'Carry_Differential', 'Real_Yield_Differential']
        providers = ['FRED_API_KEY + OECD/global rate series mirrored in FRED', 'official central-bank feeds where available']
        core_have, core_total = _ratio_present(context, required)
        spec_have, spec_total = _ratio_present(context, specialist)
        core_cov = 100 * core_have / core_total
        spec_cov = 100 * spec_have / spec_total
        score = .50 * core_cov + .50 * spec_cov
        note = 'FX requires relative policy/carry and real-yield differentials; USD trend alone cannot replace them.'
    elif typ in {'ETF', 'Índice'}:
        required = ['20d_Return', '63d_Return']
        specialist = ['Breadth', 'Flows', 'Holdings_Concentration', 'Tracking_Error'] if typ == 'ETF' else ['Breadth', 'Advance_Decline', 'New_Highs_Lows']
        providers = ['market breadth feed', 'ETF holdings/flows provider']
        combined = dict(context)
        if _present(macro.get('Breadth')):
            combined['Breadth'] = macro.get('Breadth')
        core_have, core_total = _ratio_present(combined, required)
        spec_have, spec_total = _ratio_present(combined, specialist)
        context = combined
        core_cov = 100 * core_have / core_total
        spec_cov = 100 * spec_have / spec_total
        score = .60 * core_cov + .40 * spec_cov
        note = 'Index/ETF analysis benefits from breadth and flows/concentration; fund-level P/E is not a substitute for underlying composition.'
    else:
        return {
            'Data_Coverage_Score': 50, 'Data_Coverage_Label': 'PARTIAL',
            'Core_Data_Coverage_%': 50.0, 'Specialist_Data_Coverage_%': 0.0,
            'Available_Data': [], 'Missing_Critical_Data': [], 'Missing_Useful_Data': [],
            'Recommended_Data_Sources': [], 'Coverage_Note': 'No dedicated coverage template for this asset type.'
        }

    missing_required = [k for k in required if not _present(context.get(k))]
    missing_specialist = [k for k in specialist if not _present(context.get(k))]
    available = [k for k in required + specialist if _present(context.get(k))]
    return {
        'Data_Coverage_Score': int(clamp(round(score))),
        'Data_Coverage_Label': _coverage_label(score),
        'Core_Data_Coverage_%': round(core_cov, 1),
        'Specialist_Data_Coverage_%': round(spec_cov, 1),
        'Available_Data': available,
        'Missing_Critical_Data': missing_required + missing_specialist,
        'Missing_Useful_Data': [],
        'Recommended_Data_Sources': providers,
        'Coverage_Note': note,
    }


def coverage_rows(cov: dict) -> pd.DataFrame:
    """UI-friendly table without embedding lists in cells as Python reprs."""
    rows = [
        {'Dimension': 'Overall data coverage', 'Value': f"{cov.get('Data_Coverage_Score', 0)}/100 ({cov.get('Data_Coverage_Label', 'N/D')})"},
        {'Dimension': 'Core data coverage', 'Value': f"{cov.get('Core_Data_Coverage_%', 0):.1f}%"},
        {'Dimension': 'Specialist data coverage', 'Value': f"{cov.get('Specialist_Data_Coverage_%', 0):.1f}%"},
    ]
    return pd.DataFrame(rows)
