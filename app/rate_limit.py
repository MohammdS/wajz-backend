"""Minimal in-memory fixed-window rate limiter.

Suitable for a single-process MVP deployment. Swap for a Redis-backed
implementation when running multiple replicas.
"""

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request, status

from app.config import get_settings

_counters: dict[tuple[str, str], tuple[int, float]] = defaultdict(lambda: (0, 0.0))
_lock = Lock()


def _check(bucket: str, client_id: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    key = (bucket, client_id)
    with _lock:
        count, window_start = _counters[key]
        if now - window_start >= window_seconds:
            count, window_start = 0, now
        count += 1
        _counters[key] = (count, window_start)
    if count > limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Rate limit exceeded. Please slow down.",
        )


def rate_limit(bucket: str, limit_attr: str):
    """Dependency factory: rate_limit("public", "rate_limit_public")."""

    def dependency(request: Request) -> None:
        settings = get_settings()
        client_id = request.client.host if request.client else "unknown"
        _check(bucket, client_id, getattr(settings, limit_attr), settings.rate_limit_window_seconds)

    return dependency


def reset_counters() -> None:
    """For tests."""
    with _lock:
        _counters.clear()
