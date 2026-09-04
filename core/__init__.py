"""Shared runtime initialization for data-provider clients."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _configure_yfinance_process_cache():
    """Isolate yfinance's SQLite cookie/timezone cache per worker process."""
    try:
        import yfinance as yf
        from yfinance.cache import get_cookie_cache, get_tz_cache
        cache_dir=Path(tempfile.gettempdir())/'market_screener_yfinance'/f'process-{os.getpid()}'
        cache_dir.mkdir(parents=True,exist_ok=True)
        yf.set_tz_cache_location(str(cache_dir))
        # Initialize both SQLite files on the main thread before yf.download
        # creates its internal request threads.
        get_cookie_cache(); get_tz_cache()
    except Exception:
        # Provider functions already expose their own unavailable/partial state.
        pass


_configure_yfinance_process_cache()
