import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

from datasources import cache

calls = {"n": 0}


@cache.cached(ttl_seconds=60)
def _expensive(x):
    calls["n"] += 1
    return {"x": x, "call": calls["n"]}


def test_function_runs_once_per_argument():
    cache.clear_cache()
    calls["n"] = 0
    assert _expensive(1) == _expensive(1)
    assert calls["n"] == 1
    _expensive(2)
    assert calls["n"] == 2


def test_dataframe_roundtrip():
    idx = pd.to_datetime(["2024-06-03", "2024-06-04"])
    df = pd.DataFrame({"Close": [115.0, 116.44], "Adj Close": [114.9, 116.3], "Volume": [100, 200]}, index=idx)
    key = cache.make_key("test.df", "NVDA")
    cache.cache_set(key, df, 60)
    assert_frame_equal(cache.cache_get(key), df, check_freq=False, check_names=False)


def test_series_roundtrip():
    s = pd.Series([1.5, 4.0, 10.0], index=pd.to_datetime(["2007-09-11", "2021-07-20", "2024-06-10"]),
                  name="Stock Splits")
    key = cache.make_key("test.series", "NVDA")
    cache.cache_set(key, s, 60)
    assert_series_equal(cache.cache_get(key), s, check_freq=False, check_names=False)


def test_expired_and_empty_are_misses():
    expired = cache.make_key("test.expired")
    cache.cache_set(expired, {"a": 1}, -1)          # already expired
    assert cache.cache_get(expired) is cache.MISS
    empty = cache.make_key("test.empty")
    cache.cache_set(empty, pd.DataFrame(), 60)      # empty results are never cached
    assert cache.cache_get(empty) is cache.MISS


def test_values_stored_as_json_not_pickle():
    key = cache.make_key("test.json")
    cache.cache_set(key, {"ticker": "NVDA", "price": 182.77}, 60)
    with cache._get_pool().connection() as conn:
        raw = conn.execute("SELECT value FROM market_cache WHERE key = %s", (key,)).fetchone()[0]
    assert raw.startswith('{"__type__"') and "182.77" in raw