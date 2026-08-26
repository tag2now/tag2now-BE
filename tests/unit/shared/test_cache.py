"""Cache backend behaviour — the dict cache runs whenever Redis is not configured."""

import dataclasses
import time
from datetime import datetime, timezone

import pytest

from shared.cache import CacheBackend, DictCache, RedisCache, _make_cache
from shared.settings import get_settings


@pytest.fixture
def cache():
    return DictCache()


def test_a_stored_value_reads_back(cache):
    cache.set("k", {"a": 1}, 60)
    assert cache.get("k") == {"a": 1}


def test_an_unknown_key_reads_as_a_miss(cache):
    assert cache.get("never-written") is None


def test_a_rewritten_key_keeps_only_the_later_value(cache):
    cache.set("k", "first", 60)
    cache.set("k", "second", 60)
    assert cache.get("k") == "second"


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

def test_an_expired_entry_reads_as_a_miss(cache):
    cache.set("k", "v", 0)
    time.sleep(0.01)
    assert cache.get("k") is None


def test_an_unexpired_entry_survives(cache):
    cache.set("k", "v", 60)
    time.sleep(0.01)
    assert cache.get("k") == "v"


def test_expiry_is_per_entry(cache):
    cache.set("short", "gone", 0)
    cache.set("long", "kept", 60)
    time.sleep(0.01)
    assert cache.get("short") is None
    assert cache.get("long") == "kept"


# ---------------------------------------------------------------------------
# Pattern deletion
# ---------------------------------------------------------------------------

def test_pattern_deletion_removes_every_match(cache):
    cache.set("community:post:1", "a", 60)
    cache.set("community:post:2", "b", 60)
    cache.delete_pattern("community:post:*")
    assert cache.get("community:post:1") is None
    assert cache.get("community:post:2") is None


def test_pattern_deletion_spares_other_namespaces(cache):
    cache.set("community:post:1", "a", 60)
    cache.set("ttt2:rooms_all:X", "b", 60)
    cache.delete_pattern("community:*")
    assert cache.get("ttt2:rooms_all:X") == "b"


def test_pattern_deletion_without_matches_is_harmless(cache):
    cache.set("ttt2:rooms_all:X", "b", 60)
    cache.delete_pattern("community:*")
    assert cache.get("ttt2:rooms_all:X") == "b"


# ---------------------------------------------------------------------------
# Serialisation — the dict cache stores JSON, like Redis does
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _Room:
    name: str
    players: int


def test_a_dataclass_reads_back_as_a_dict(cache):
    cache.set("room", _Room(name="lobby", players=2), 60)
    assert cache.get("room") == {"name": "lobby", "players": 2}


def test_a_datetime_reads_back_as_an_iso_string(cache):
    moment = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    cache.set("when", {"at": moment}, 60)
    assert cache.get("when") == {"at": moment.isoformat()}


def test_a_cached_value_does_not_alias_the_caller_object(cache):
    value = {"players": [1, 2]}
    cache.set("k", value, 60)
    value["players"].append(3)
    assert cache.get("k") == {"players": [1, 2]}


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

@pytest.fixture
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_an_empty_redis_url_selects_the_dict_cache(monkeypatch, clear_settings_cache):
    monkeypatch.setenv("REDIS_URL", "")
    assert isinstance(_make_cache(), DictCache)


def test_a_configured_redis_url_selects_redis(monkeypatch, clear_settings_cache):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    assert isinstance(_make_cache(), RedisCache)


@pytest.mark.parametrize("backend", [DictCache, RedisCache])
def test_every_backend_implements_the_cache_interface(backend):
    assert issubclass(backend, CacheBackend)
