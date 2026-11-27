"""Small in-process sliding-window rate limiter (OWASP ASVS V2.2 / V11.1).

Enough for a single-process academic deployment; counters reset on restart and are not
shared between processes (documented limitation). Keys are hashed so e-mail addresses are not
held in memory in clear text.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import Lock

from flask import current_app, request

_windows: dict[tuple, deque] = defaultdict(deque)
_lock = Lock()

# bucket: (max events, window)
LIMITS = {
    'register_ip': (30, timedelta(minutes=10)),  # a classroom shares one IP
    'forgot_ip': (5, timedelta(minutes=15)),
    'forgot_email': (3, timedelta(hours=1)),
    'reset_ip': (10, timedelta(minutes=15)),
    'verify_ip': (20, timedelta(minutes=15)),
    'login_fail_ip': (50, timedelta(minutes=15)),
    'login_fail_email': (5, timedelta(minutes=15)),
}


def _key(bucket: str, value: str) -> tuple:
    return bucket, hashlib.sha256(str(value).lower().encode()).hexdigest()


def client_ip() -> str:
    return request.remote_addr or 'unknown'


def enabled() -> bool:
    return current_app.config.get('RATE_LIMIT_ENABLED', True)


def hit(bucket: str, value: str) -> bool:
    """Record one event; True when the bucket is now over its limit (the caller answers 429)."""
    if not enabled():
        return False
    limit, window = LIMITS[bucket]
    now = datetime.utcnow()
    with _lock:
        events = _windows[_key(bucket, value)]
        while events and now - events[0] > window:
            events.popleft()
        events.append(now)
        return len(events) > limit


def exceeded(bucket: str, value: str) -> bool:
    """True when the bucket is already at its limit, without recording an event."""
    if not enabled():
        return False
    limit, window = LIMITS[bucket]
    now = datetime.utcnow()
    with _lock:
        events = _windows[_key(bucket, value)]
        while events and now - events[0] > window:
            events.popleft()
        return len(events) >= limit


def reset_all():
    """Test helper."""
    with _lock:
        _windows.clear()
