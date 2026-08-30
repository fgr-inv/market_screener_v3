"""Central cache TTL policy for multi-user/rate-limit-safe operation.

The policy separates *live quotes* from historical bars.  A live price can be refreshed
frequently without forcing the application to redownload years of OHLCV data, while
slow-moving accounting inputs remain cached for much longer.
"""
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# Market data layers
LIVE_PRICE_TTL = 5 * MINUTE
HISTORICAL_PRICE_TTL = 60 * MINUTE
PRICE_DISK_MAX_AGE_MINUTES = 60
TECHNICAL_TTL = 15 * MINUTE
RS_TTL = 60 * MINUTE
SECTOR_TTL = 60 * MINUTE

# Backwards-compatible alias for modules/tests that still refer to PRICE_TTL.
# It means quote/last-price freshness, not historical OHLCV freshness.
PRICE_TTL = LIVE_PRICE_TTL

NEWS_TTL = 30 * MINUTE
OPTIONS_TTL = 30 * MINUTE
CRYPTO_SPOT_TTL = 5 * MINUTE
CRYPTO_DERIVATIVES_TTL = 15 * MINUTE
MACRO_TTL = 12 * HOUR
FRED_TTL = 12 * HOUR
ANALYST_TTL = 12 * HOUR
EVENT_TTL = 12 * HOUR
VALUATION_TTL = DAY
FUNDAMENTALS_TTL = 7 * DAY
SPECIALIST_TTL = 7 * DAY
COT_TTL = 7 * DAY

CACHE_POLICY = {
    'live_price': LIVE_PRICE_TTL,
    'price': LIVE_PRICE_TTL,
    'historical_price': HISTORICAL_PRICE_TTL,
    'price_disk_max_age_minutes': PRICE_DISK_MAX_AGE_MINUTES,
    'technicals': TECHNICAL_TTL,
    'relative_strength': RS_TTL,
    'sector': SECTOR_TTL,
    'news': NEWS_TTL,
    'options': OPTIONS_TTL,
    'crypto_spot': CRYPTO_SPOT_TTL,
    'crypto_derivatives': CRYPTO_DERIVATIVES_TTL,
    'macro': MACRO_TTL,
    'fred': FRED_TTL,
    'analyst': ANALYST_TTL,
    'earnings_event': EVENT_TTL,
    'valuation': VALUATION_TTL,
    'fundamentals': FUNDAMENTALS_TTL,
    'specialist': SPECIALIST_TTL,
    'cot': COT_TTL,
}
