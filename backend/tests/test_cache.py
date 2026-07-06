import time

from app.cache import Cache, make_signature


def make_cache(tmp_path, **kwargs) -> Cache:
    return Cache(str(tmp_path / "cache.sqlite3"), **kwargs)


def test_miss_then_hit(tmp_path):
    cache = make_cache(tmp_path)
    params = {"q": "DEL to CDG", "adults": 2}
    assert cache.get("flights", params) is None
    cache.set("flights", params, {"price": 45000})
    assert cache.get("flights", params) == {"price": 45000}
    assert cache.hits == 1 and cache.misses == 1


def test_signature_canonicalization_ignores_key_order(tmp_path):
    a = make_signature("flights", {"a": 1, "b": 2})
    b = make_signature("flights", {"b": 2, "a": 1})
    assert a == b


def test_signature_distinguishes_service_and_params():
    base = make_signature("flights", {"a": 1})
    assert base != make_signature("hotels", {"a": 1})
    assert base != make_signature("flights", {"a": 2})


def test_ttl_expiry(tmp_path, monkeypatch):
    cache = make_cache(tmp_path, ttls={"flights": 3600})
    cache.set("flights", {"q": 1}, {"price": 1})

    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 3601)
    assert cache.get("flights", {"q": 1}) is None


def test_per_service_ttl(tmp_path, monkeypatch):
    cache = make_cache(tmp_path, ttls={"flights": 3600, "places": 86400})
    cache.set("flights", {"q": 1}, "f")
    cache.set("places", {"q": 1}, "p")

    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 7200)
    assert cache.get("flights", {"q": 1}) is None   # past 1h TTL
    assert cache.get("places", {"q": 1}) == "p"     # within 24h TTL


def test_persists_across_instances(tmp_path):
    make_cache(tmp_path).set("routes", {"m": 1}, [[0, 5], [5, 0]])
    assert make_cache(tmp_path).get("routes", {"m": 1}) == [[0, 5], [5, 0]]


def test_clear(tmp_path):
    cache = make_cache(tmp_path)
    cache.set("hotels", {"q": 1}, "x")
    cache.clear()
    assert cache.get("hotels", {"q": 1}) is None
