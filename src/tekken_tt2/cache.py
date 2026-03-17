"""Redis cache helpers."""

import json
import logging

import redis
from env import get_settings

_redis_client = redis.from_url(get_settings().redis_url, decode_responses=True)


def cache_get(key: str):
    try:
        raw = _redis_client.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:
        logging.warning("Redis get failed: %s", e)
        return None


def cache_set(key: str, value, ttl: int):
    try:
        _redis_client.setex(key, ttl, json.dumps(value))
    except Exception as e:
        logging.warning("Redis set failed: %s", e)
