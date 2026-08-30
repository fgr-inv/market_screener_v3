"""Process-global provider safety limiter.

This is a last line of defence, independent of commercial plan quotas. OWNER is
not exempt. It intentionally uses conservative defaults suitable for public/free
sources. Multi-instance deployments should move this state to Redis/Upstash.
"""
from __future__ import annotations
import threading, time
from collections import defaultdict, deque

# Requests per rolling window. These are app-side safety ceilings, not provider guarantees.
DEFAULT_LIMITS={
    'SEC': (4,1.0),
    'YAHOO': (2,1.0),
    'FMP': (1,1.0),
    'FRED': (2,1.0),
    'EIA': (2,1.0),
    'COINGECKO': (2,1.0),
    'DEEP_BUNDLE': (4,1.0),
}
_LOCK=threading.Lock(); _HITS=defaultdict(deque)

def acquire(provider: str, timeout=15.0):
    provider=str(provider or 'DEEP_BUNDLE').upper(); limit,window=DEFAULT_LIMITS.get(provider,(4,1.0))
    deadline=time.monotonic()+max(0,float(timeout))
    while True:
        now=time.monotonic()
        with _LOCK:
            q=_HITS[provider]
            while q and now-q[0]>=window: q.popleft()
            if len(q)<limit:
                q.append(now); return True
            wait=max(0.01,window-(now-q[0])+0.005)
        if now+wait>deadline: return False
        time.sleep(min(wait,0.25))
