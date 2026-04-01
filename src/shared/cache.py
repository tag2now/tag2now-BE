"""Redis cache helpers."""

import dataclasses
import json
import logging
import time
from datetime import datetime
from urllib.parse import urlparse

import redis
from shared.settings import get_settings

logger = logging.getLogger(__name__)


class _DataclassEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        return super().default(obj)

_redis_client = redis.from_url(get_settings().redis_url, decode_responses=True, socket_connect_timeout=5)


def cache_get(key: str):
    try:
        raw = _redis_client.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.warning("Redis get failed: %s", e)
        return None


def cache_set(key: str, value, ttl: int):
    try:
        _redis_client.setex(key, ttl, json.dumps(value, cls=_DataclassEncoder))
    except Exception as e:
        logger.warning("Redis set failed: %s", e)


def cache_delete_pattern(pattern: str):
    """Delete all keys matching *pattern* (uses SCAN, safe for production)."""
    try:
        cursor = 0
        while True:
            cursor, keys = _redis_client.scan(cursor, match=pattern, count=100)
            if keys:
                _redis_client.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning("Redis delete pattern failed: %s", e)


def redis_health_check(timeout: float = 5.0, interval: float = 1.0):
    """Ping Redis repeatedly until success or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            _redis_client.ping()
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
