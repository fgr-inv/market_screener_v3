from core.plans import normalize_plan, plan_config, is_owner
from core.provider_rate_limit import DEFAULT_LIMITS


def test_owner_is_quota_exempt_but_has_safety_caps():
    cfg=plan_config('OWNER')
    assert is_owner('OWNER')
    assert cfg['quota_exempt'] is True
    assert cfg['quotas']=={}
    assert cfg['fundamental_screener'] is True
    assert cfg['combined_screener'] is True
    assert cfg['dcf'] is True
    assert cfg['max_screener_assets'] == 500
    assert 'DEEP_BUNDLE' in DEFAULT_LIMITS


def test_admin_alias_maps_to_owner():
    assert normalize_plan('ADMIN')=='OWNER'
    assert normalize_plan('founder')=='OWNER'


def test_paid_and_free_product_limits():
    free=plan_config('FREE'); pro=plan_config('PRO'); prem=plan_config('PREMIUM')
    assert free['fundamental_screener'] is False
    assert free['combined_screener'] is False
    assert free['max_screener_assets']==100
    assert pro['quotas']['fundamental_screener']=={'daily':3,'monthly':30}
    assert prem['quotas']['asset_deep']=={'daily':30,'monthly':500}
    assert pro['max_screener_assets'] < prem['max_screener_assets']
