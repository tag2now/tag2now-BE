"""Cache helpers — Redis when configured, in-process dict otherwise."""

import dataclasses
import fnmatch
import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from urllib.parse import urlparse

from shared.settings import get_settings

logger = logging.getLogger(__name__)


class _DataclassEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        return super().default(obj)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class CacheBackend(ABC):
    @abstractmethod
    def get(self, key: str):
        """Return the cached value for *key*, or ``None`` if missing/expired."""

    @abstractmethod
    def set(self, key: str, value, ttl: int):
        """Store *value* under *key* with a TTL in seconds."""

    @abstractmethod
    def delete_pattern(self, pattern: str):
        """Delete all keys matching glob-style *pattern*."""


# ---------------------------------------------------------------------------
# Dict (in-process) implementation
# ---------------------------------------------------------------------------

class DictCache(CacheBackend):
    """Thread-safe in-process cache with per-entry TTL."""

    def __init__(self):
        # key -> (json_str, expire_at_monotonic)
        self._store: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            entry = self._store.get(key)
        if entry is None:
            return None
        value_json, expire_at = entry
        if time.monotonic() >= expire_at:
            with self._lock:
                self._store.pop(key, None)
            return None
        return json.loads(value_json)

    def set(self, key: str, value, ttl: int):
        serialised = json.dumps(value, cls=_DataclassEncoder)
        expire_at = time.monotonic() + ttl
        with self._lock:
            self._store[key] = (serialised, expire_at)

    def delete_pattern(self, pattern: str):
        # Match outside the lock: fnmatch over every key dominates the cost, and
        # holding the lock across it stalls readers for as long as it takes.
        with self._lock:
            keys = list(self._store)
        doomed = [key for key in keys if fnmatch.fnmatch(key, pattern)]
        with self._lock:
            for key in doomed:
                self._store.pop(key, None)


# ---------------------------------------------------------------------------
# Redis implementation
# ---------------------------------------------------------------------------

class RedisCache(CacheBackend):
    def __init__(self):
        import redis
        self._client = redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
        )

    def get(self, key: str):
        try:
            raw = self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning("Redis get failed: %s", e)
            return None

    def set(self, key: str, value, ttl: int):
        try:
            self._client.setex(key, ttl, json.dumps(value, cls=_DataclassEncoder))
        except Exception as e:
            logger.warning("Redis set failed: %s", e)

    def delete_pattern(self, pattern: str):
        """Delete all keys matching *pattern* (uses SCAN, safe for production)."""
        try:
            cursor = 0
            while True:
                cursor, keys = self._client.scan(cursor, match=pattern, count=100)
                if keys:
                    self._client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning("Redis delete pattern failed: %s", e)

    def ping(self):
        self._client.ping()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _make_cache() -> CacheBackend:
    if get_settings().redis_url:
        return RedisCache()
    logger.info("redis_url is not set — using in-process dict cache")
    return DictCache()


_cache: CacheBackend = _make_cache()


# ---------------------------------------------------------------------------
# Module-level public API (backwards-compatible shims)
# ---------------------------------------------------------------------------

def cache_get(key: str):
    return _cache.get(key)


def cache_set(key: str, value, ttl: int):
    _cache.set(key, value, ttl)


def cache_delete_pattern(pattern: str):
    _cache.delete_pattern(pattern)


def redis_health_check(timeout: float = 5.0, interval: float = 1.0):
    """Ping Redis repeatedly until success or *timeout* seconds elapse.

    Returns immediately when the dict cache is active (no redis_url).
    """
    if not get_settings().redis_url:
        logger.info("redis_url is not set — skipping Redis health check")
        return

    import redis

    assert isinstance(_cache, RedisCache)
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            _cache.ping()
            parsed = urlparse(get_settings().redis_url)
            logger.info("Redis connection established to %s:%s", parsed.hostname, parsed.port)
            return
        except (redis.ConnectionError, redis.exceptions.TimeoutError, OSError) as e:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error("Redis connection failed after %.1fs (%d attempts): %s", timeout, attempt, e)
                raise
            logger.warning("Redis not ready, retrying in %.1fs (%.1fs remaining): %s", interval, remaining, e)
            time.sleep(min(interval, remaining))
