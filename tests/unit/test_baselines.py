"""Unit tests for analyzer/_baselines.py — dynamic baseline cache."""

import time
from unittest.mock import patch

import _baselines


class TestStaticDefaults:
    def test_contains_all_keys(self):
        baselines = _baselines.get_baselines()
        expected_keys = {"took_ms", "hits", "shards_total", "docs_affected"}
        assert set(baselines.keys()) == expected_keys

    def test_default_values(self):
        baselines = _baselines.get_baselines()
        assert baselines["took_ms"] == 100
        assert baselines["hits"] == 500
        assert baselines["shards_total"] == 5
        assert baselines["docs_affected"] == 500


class TestCacheTTL:
    def test_skips_refresh_within_ttl(self):
        _baselines._cache_ts = time.monotonic()
        with patch.object(_baselines, "_fetch_p50") as mock:
            _baselines.get_baselines()
            mock.assert_not_called()

    def test_refreshes_after_ttl_expires(self):
        _baselines._cache_ts = time.monotonic() - _baselines._CACHE_TTL - 1
        with patch.object(_baselines, "_ES_URL", "http://fake:9200"), \
             patch.object(_baselines, "_fetch_p50", return_value={}):
            _baselines.get_baselines()
            _baselines._fetch_p50.assert_called_once()


class TestDynamicRefresh:
    def _force_stale(self):
        _baselines._cache_ts = 0.0

    def test_dynamic_values_override_static(self):
        self._force_stale()
        with patch.object(_baselines, "_ES_URL", "http://fake:9200"), \
             patch.object(_baselines, "_fetch_p50",
                          return_value={"took_ms": 75.0, "shards_total": 3.0}):
            bl = _baselines.get_baselines()
            assert bl["took_ms"] == 75.0
            assert bl["shards_total"] == 3.0
            assert bl["hits"] == 500  # static, unchanged

    def test_partial_dynamic_reverts_missing_to_static(self):
        self._force_stale()
        with patch.object(_baselines, "_ES_URL", "http://fake:9200"), \
             patch.object(_baselines, "_fetch_p50",
                          return_value={"took_ms": 50.0}):
            bl = _baselines.get_baselines()
            assert bl["took_ms"] == 50.0
            assert bl["shards_total"] == _baselines._STATIC["shards_total"]

    def test_fallback_on_es_error(self):
        self._force_stale()
        original_took = _baselines._cache["took_ms"]
        with patch.object(_baselines, "_ES_URL", "http://fake:9200"), \
             patch.object(_baselines, "_fetch_p50",
                          side_effect=ConnectionError("refused")):
            bl = _baselines.get_baselines()
            assert bl["took_ms"] == original_took

    def test_no_es_url_skips_fetch(self):
        self._force_stale()
        with patch.object(_baselines, "_ES_URL", None), \
             patch.object(_baselines, "_fetch_p50") as mock:
            _baselines.get_baselines()
            mock.assert_not_called()

    def teardown_method(self):
        _baselines._cache.update(_baselines._STATIC)
        _baselines._cache_ts = 0.0
