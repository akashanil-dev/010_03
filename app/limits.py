"""Request rate limits per IP or email, and the day the daily quota counts against.

The limiter is in memory: run the web app as a single process (it is I/O bound; the worker does the heavy
work). Sliding windows: at most `count` requests per `window` seconds per key.
"""

import threading
import time
from collections import deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from . import config

RULES = {
    "signup": (5, 3600),        # per IP
    "login": (20, 600),         # per IP
    "login_email": (10, 600),   # per email, so one account cannot be guessed at from many IPs
    "email": (5, 3600),         # verification / reset / invite emails per IP or account
    "upload": (30, 3600),       # upload requests per IP (the daily quota is the real limit)
    "push": (20, 3600),
}

_hits: dict[tuple[str, str], deque] = {}
_lock = threading.Lock()


def hit(rule: str, key: str | None) -> None:
    """Count one request, or raise 429 if the window is full."""
    count, window = RULES[rule]
    now = time.monotonic()
    with _lock:
        q = _hits.setdefault((rule, key or "?"), deque())
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= count:
            wait = int(q[0] + window - now) + 1
            raise HTTPException(429, f"Too many attempts. Try again in {_minutes(wait)}.",
                                headers={"Retry-After": str(wait)})
        q.append(now)
        if len(_hits) > 50_000:   # drop idle keys now and then
            for k in [k for k, v in _hits.items() if not v or v[-1] <= now - 3600]:
                del _hits[k]


def reset() -> None:
    with _lock:
        _hits.clear()


def _minutes(seconds: int) -> str:
    return f"{seconds} seconds" if seconds < 90 else f"{round(seconds / 60)} minutes"


def today(now: float | None = None) -> str:
    """The quota day (YYYY-MM-DD) in the configured time zone."""
    return datetime.fromtimestamp(now or time.time(), ZoneInfo(config.TIMEZONE)).date().isoformat()


def next_reset(now: float | None = None) -> float:
    tz = ZoneInfo(config.TIMEZONE)
    d = datetime.fromtimestamp(now or time.time(), tz).date() + timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=tz).timestamp()
