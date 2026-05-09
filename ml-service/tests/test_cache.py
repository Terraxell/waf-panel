"""ScoreCache fail-open semantics — Redis errors must never raise."""

from __future__ import annotations


def test_cache_get_returns_none_when_no_client():
    from waf_ml_service.cache import ScoreCache

    c = ScoreCache(client=None, ttl_sec=30)
    assert c.get("anything") is None
    c.set("anything", {"prob": 0.1})  # must not raise


def test_cache_swallows_get_errors():
    """A flaky redis client whose .get raises must be treated as a miss."""
    from waf_ml_service.cache import ScoreCache

    class Flaky:
        def get(self, _k):
            raise RuntimeError("redis is having a moment")

        def setex(self, *_a):
            raise RuntimeError("still flaky")

        def ping(self):
            raise RuntimeError("ping fails too")

    c = ScoreCache(client=Flaky(), ttl_sec=30)
    assert c.get("k") is None  # error → None, not raised
    c.set("k", {"prob": 0.5})  # error swallowed
    assert c.healthy is False


def test_cache_key_is_method_path_query_dependent():
    from waf_ml_service.cache import cache_key

    a = cache_key("GET", "/x", "id=1")
    b = cache_key("POST", "/x", "id=1")
    c = cache_key("GET", "/y", "id=1")
    d = cache_key("GET", "/x", "id=2")
    e = cache_key("get", "/x", "id=1")  # method should be normalised
    assert len({a, b, c, d}) == 4
    assert a == e


def test_cache_round_trip_with_dict_backed_client():
    """A minimal dict-backed redis stub round-trips a payload."""
    from waf_ml_service.cache import ScoreCache

    class DictRedis:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}

        def get(self, k):
            return self.store.get(k)

        def setex(self, k, _ttl, v):
            self.store[k] = v

        def ping(self):
            return True

    c = ScoreCache(client=DictRedis(), ttl_sec=30)
    c.set("k", {"prob": 0.42, "model": "stub"})
    assert c.get("k") == {"prob": 0.42, "model": "stub"}
    assert c.healthy is True
