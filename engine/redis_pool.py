from __future__ import annotations

import threading

import redis

from app.core.config import get_settings

_lock = threading.Lock()
_pool: redis.ConnectionPool | None = None


def get_redis_pool() -> redis.ConnectionPool:
    """Returns the shared Redis connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                _pool = redis.ConnectionPool.from_url(
                    get_settings().redis_url,
                    decode_responses=True,
                    max_connections=20,
                )
    return _pool


def get_redis() -> redis.Redis:
    """Returns a Redis client using the shared connection pool."""
    return redis.Redis(connection_pool=get_redis_pool())
