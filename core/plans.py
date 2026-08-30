"""Commercial plans and entitlements.

OWNER is intentionally not a paid plan. It bypasses product quotas while still
using shared caches and provider-side safety controls.
"""
from __future__ import annotations

PLANS = {
    'FREE': {
        'technical_screener': True, 'fundamental_screener': False, 'combined_screener': False,
        'asset_technical': True, 'asset_deep': True, 'dcf': False, 'scenarios': False, 'export': False,
        'max_screener_assets': 100, 'max_deep_candidates': 0, 'max_workers': 1,
        'allowed_depths': ('Rápido',), 'max_concurrent_jobs': 1, 'api_units_per_hour': 20, 'max_saved_alerts': 3,
        'quotas': {
            'technical_screener': {'daily': 5, 'monthly': 100},
            'asset_technical': {'daily': 5, 'monthly': 100},
            'asset_deep': {'daily': 1, 'monthly': 10},
        },
    },
    'PRO': {
        'technical_screener': True, 'fundamental_screener': True, 'combined_screener': True,
        'asset_technical': True, 'asset_deep': True, 'dcf': True, 'scenarios': True, 'export': True,
        'max_screener_assets': 300, 'max_deep_candidates': 20, 'max_workers': 4,
        'allowed_depths': ('Rápido','Balanceado','Profundo'), 'max_concurrent_jobs': 2, 'api_units_per_hour': 100, 'max_saved_alerts': 25,
        'quotas': {
            'technical_screener': {'daily': 30, 'monthly': 600},
            'fundamental_screener': {'daily': 3, 'monthly': 30},
            'combined_screener': {'daily': 2, 'monthly': 20},
            'asset_technical': {'daily': 30, 'monthly': 600},
            'asset_deep': {'daily': 10, 'monthly': 150},
        },
    },
    'PREMIUM': {
        'technical_screener': True, 'fundamental_screener': True, 'combined_screener': True,
        'asset_technical': True, 'asset_deep': True, 'dcf': True, 'scenarios': True, 'export': True,
        'max_screener_assets': 500, 'max_deep_candidates': 40, 'max_workers': 6,
        'allowed_depths': ('Rápido','Balanceado','Profundo'), 'max_concurrent_jobs': 3, 'api_units_per_hour': 300, 'max_saved_alerts': 100,
        'quotas': {
            'technical_screener': {'daily': 100, 'monthly': 2000},
            'fundamental_screener': {'daily': 10, 'monthly': 120},
            'combined_screener': {'daily': 8, 'monthly': 80},
            'asset_technical': {'daily': 100, 'monthly': 2000},
            'asset_deep': {'daily': 30, 'monthly': 500},
        },
    },
    'OWNER': {
        'technical_screener': True, 'fundamental_screener': True, 'combined_screener': True,
        'asset_technical': True, 'asset_deep': True, 'dcf': True, 'scenarios': True, 'export': True,
        'max_screener_assets': 500, 'max_deep_candidates': 100, 'max_workers': 8,
        'allowed_depths': ('Rápido','Balanceado','Profundo'), 'max_concurrent_jobs': 8,
        # None means no commercial per-user API budget. Provider safety still applies globally.
        'api_units_per_hour': None, 'max_saved_alerts': None, 'quotas': {}, 'quota_exempt': True,
    },
}

ALIASES = {'ADMIN':'OWNER', 'FOUNDER':'OWNER'}

def normalize_plan(plan: str | None) -> str:
    p=str(plan or 'FREE').strip().upper()
    p=ALIASES.get(p,p)
    return p if p in PLANS else 'FREE'

def plan_config(plan: str | None) -> dict:
    return PLANS[normalize_plan(plan)]

def is_owner(plan: str | None) -> bool:
    return normalize_plan(plan)=='OWNER'

FEATURE_API_UNITS = {
    'technical_screener': 1,
    'fundamental_screener': 10,
    'combined_screener': 15,
    'asset_technical': 1,
    'asset_deep': 3,
}

def api_unit_cost(feature: str) -> int:
    return int(FEATURE_API_UNITS.get(str(feature), 1))
