"""Unit tests for analyzer/stress.py — clause counting, cost indicators, stress formulas."""

import pytest

from stress import (
    normalize,
    count_clauses,
    evaluate_cost_indicators,
    calc_stress,
    StressContext,
    BASELINES,
    _count_aggs,
)


# ---------------------------------------------------------------------------
# norm()
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_at_baseline(self):
        assert normalize(100, 100) == 1.0

    def test_below_baseline(self):
        assert normalize(50, 100) == 0.5

    def test_above_baseline(self):
        assert normalize(200, 100) == 2.0

    def test_zero_value(self):
        assert normalize(0, 100) == 0.0


# ---------------------------------------------------------------------------
# count_clauses — _walk_query_clauses + _count_aggs
# ---------------------------------------------------------------------------

class TestCountClauses:
    def test_empty_body(self):
        counts = count_clauses({})
        assert all(v == 0 for v in counts.values())

    def test_simple_bool(self):
        body = {"query": {"bool": {"must": [{"match": {"title": "test"}}]}}}
        counts = count_clauses(body)
        assert counts["bool_clause_count"] == 1
        assert counts["bool_must_count"] == 1

    def test_bool_with_all_sub_clauses(self):
        body = {"query": {"bool": {
            "must": [{"term": {"a": 1}}, {"term": {"b": 2}}],
            "should": [{"term": {"c": 3}}],
            "filter": [{"range": {"d": {"gte": 0}}}],
            "must_not": [{"term": {"e": 4}}, {"term": {"f": 5}}, {"term": {"g": 6}}],
        }}}
        counts = count_clauses(body)
        assert counts["bool_clause_count"] == 1
        assert counts["bool_must_count"] == 2
        assert counts["bool_should_count"] == 1
        assert counts["bool_filter_count"] == 1
        assert counts["bool_must_not_count"] == 3

    def test_bool_sub_clause_as_dict_counts_as_one(self):
        body = {"query": {"bool": {"must": {"match": {"title": "test"}}}}}
        counts = count_clauses(body)
        assert counts["bool_must_count"] == 1

    def test_nested_bool(self):
        body = {"query": {"bool": {"must": [
            {"bool": {"should": [{"term": {"a": 1}}, {"term": {"b": 2}}]}}
        ]}}}
        counts = count_clauses(body)
        assert counts["bool_clause_count"] == 2  # outer + inner
        assert counts["bool_must_count"] == 1
        assert counts["bool_should_count"] == 2

    def test_wildcard_regexp_prefix(self):
        body = {"query": {"bool": {"should": [
            {"wildcard": {"title": {"value": "*test*"}}},
            {"regexp": {"desc": {"value": "te.*"}}},
            {"prefix": {"name": {"value": "te"}}},
        ]}}}
        counts = count_clauses(body)
        assert counts["wildcard_clause_count"] == 3

    def test_fuzzy(self):
        body = {"query": {"fuzzy": {"title": {"value": "test"}}}}
        counts = count_clauses(body)
        assert counts["fuzzy_clause_count"] == 1

    def test_nested(self):
        body = {"query": {"nested": {"path": "comments", "query": {"match_all": {}}}}}
        counts = count_clauses(body)
        assert counts["nested_clause_count"] == 1

    def test_knn_in_body_top_level(self):
        body = {"knn": {"field": "vec", "query_vector": [0.1, 0.2], "k": 10}}
        counts = count_clauses(body)
        assert counts["knn_clause_count"] == 1

    def test_knn_in_query(self):
        """knn inside query is counted by walker only (no top-level body["knn"])."""
        body = {"query": {"knn": {"field": "vec", "query_vector": [0.1], "k": 5}}}
        counts = count_clauses(body)
        assert counts["knn_clause_count"] == 1

    def test_knn_top_level_and_query(self):
        """knn at top level + inside query = 2."""
        body = {
            "knn": {"field": "vec", "query_vector": [0.1], "k": 10},
            "query": {"knn": {"field": "vec2", "query_vector": [0.2], "k": 5}},
        }
        counts = count_clauses(body)
        assert counts["knn_clause_count"] == 2

    def test_script_in_query(self):
        body = {"query": {"script_score": {
            "query": {"match_all": {}},
            "script": {"source": "doc['price'].value"}
        }}}
        counts = count_clauses(body)
        assert counts["script_clause_count"] == 1

    def test_script_fields(self):
        body = {"script_fields": {
            "f1": {"script": {"source": "1"}},
            "f2": {"script": {"source": "2"}},
        }}
        counts = count_clauses(body)
        assert counts["script_clause_count"] == 2

    def test_terms_values_count(self):
        body = {"query": {"terms": {"color": ["red", "blue", "green"]}}}
        counts = count_clauses(body)
        assert counts["terms_values_count"] == 3

    def test_terms_large_list(self):
        body = {"query": {"terms": {"ids": list(range(600))}}}
        counts = count_clauses(body)
        assert counts["terms_values_count"] == 600

    def test_geo_distance(self):
        body = {"query": {"geo_distance": {"distance": "10km", "location": {"lat": 40, "lon": -74}}}}
        counts = count_clauses(body)
        assert counts["geo_distance_count"] == 1

    def test_geo_shape(self):
        body = {"query": {"geo_shape": {"location": {"shape": {}}}}}
        counts = count_clauses(body)
        assert counts["geo_shape_count"] == 1

    def test_geo_polygon_counted_as_shape(self):
        body = {"query": {"geo_polygon": {"location": {"points": []}}}}
        counts = count_clauses(body)
        assert counts["geo_shape_count"] == 1

    def test_geo_bounding_box(self):
        body = {"query": {"geo_bounding_box": {"location": {"top_left": {}, "bottom_right": {}}}}}
        counts = count_clauses(body)
        assert counts["geo_bbox_count"] == 1

    def test_geo_grid_counted_as_bbox(self):
        body = {"query": {"geo_grid": {"field": "location"}}}
        counts = count_clauses(body)
        assert counts["geo_bbox_count"] == 1

    def test_runtime_mappings(self):
        body = {"runtime_mappings": {
            "price_bucket": {"type": "keyword", "script": {}},
            "discount": {"type": "double", "script": {}},
        }}
        counts = count_clauses(body)
        assert counts["runtime_mapping_count"] == 2

    def test_runtime_mappings_absent(self):
        counts = count_clauses({"query": {"match_all": {}}})
        assert counts["runtime_mapping_count"] == 0


# ---------------------------------------------------------------------------
# count_aggs
# ---------------------------------------------------------------------------

class TestCountAggs:
    def test_simple_agg(self):
        body = {"aggs": {"by_cat": {"terms": {"field": "category"}}}}
        counts = count_clauses(body)
        assert counts["agg_clause_count"] == 1

    def test_nested_aggs(self):
        body = {"aggs": {
            "by_cat": {
                "terms": {"field": "category"},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "by_color": {"terms": {"field": "color"}},
                },
            },
        }}
        counts = count_clauses(body)
        # by_cat(1) + avg_price(1) + by_color(1) = 3
        assert counts["agg_clause_count"] == 3

    def test_three_level_aggs(self):
        body = {"aggs": {
            "level1": {"terms": {"field": "a"}, "aggs": {
                "level2": {"terms": {"field": "b"}, "aggs": {
                    "level3": {"avg": {"field": "c"}}
                }}
            }}
        }}
        counts = count_clauses(body)
        assert counts["agg_clause_count"] == 3

    def test_multiple_top_level_aggs(self):
        body = {"aggs": {
            "a1": {"terms": {"field": "x"}},
            "a2": {"avg": {"field": "y"}},
            "a3": {"max": {"field": "z"}},
        }}
        counts = count_clauses(body)
        assert counts["agg_clause_count"] == 3

    def test_aggregations_alias(self):
        body = {"aggregations": {"by_cat": {"terms": {"field": "category"}}}}
        counts = count_clauses(body)
        assert counts["agg_clause_count"] == 1

    def test_no_aggs(self):
        counts = count_clauses({"query": {"match_all": {}}})
        assert counts["agg_clause_count"] == 0

    def test_deep_aggs_10_plus(self):
        """Build a chain of nested aggs that exceeds 10 total."""
        body = {"aggs": {}}
        for i in range(12):
            body["aggs"][f"a{i}"] = {"terms": {"field": f"f{i}"}}
        counts = count_clauses(body)
        assert counts["agg_clause_count"] == 12


# ---------------------------------------------------------------------------
# Cost indicators
# ---------------------------------------------------------------------------

class TestEvaluateCostIndicators:
    def _zero_counts(self):
        return {k: 0 for k in [
            "bool_clause_count", "bool_must_count", "bool_should_count",
            "bool_filter_count", "bool_must_not_count", "terms_values_count",
            "knn_clause_count", "fuzzy_clause_count", "geo_bbox_count",
            "geo_distance_count", "geo_shape_count", "agg_clause_count",
            "wildcard_clause_count", "nested_clause_count",
            "runtime_mapping_count", "script_clause_count",
        ]}

    def test_no_indicators(self):
        indicators, mult = evaluate_cost_indicators(self._zero_counts())
        assert indicators == {}
        assert mult == 1.0

    def test_has_script(self):
        c = self._zero_counts()
        c["script_clause_count"] = 3
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_script" in indicators
        assert indicators["has_script"] == 3
        assert mult == pytest.approx(1.5)

    def test_has_runtime_mapping(self):
        c = self._zero_counts()
        c["runtime_mapping_count"] = 2
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_runtime_mapping" in indicators
        assert indicators["has_runtime_mapping"] == 2
        assert mult == pytest.approx(1.5)

    def test_has_wildcard(self):
        c = self._zero_counts()
        c["wildcard_clause_count"] = 4
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_wildcard" in indicators
        assert indicators["has_wildcard"] == 4
        assert mult == pytest.approx(1.3)

    def test_has_nested(self):
        c = self._zero_counts()
        c["nested_clause_count"] = 1
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_nested" in indicators
        assert indicators["has_nested"] == 1
        assert mult == pytest.approx(1.3)

    def test_has_fuzzy(self):
        c = self._zero_counts()
        c["fuzzy_clause_count"] = 1
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_fuzzy" in indicators
        assert indicators["has_fuzzy"] == 1
        assert mult == pytest.approx(1.2)

    def test_has_geo_distance(self):
        c = self._zero_counts()
        c["geo_distance_count"] = 2
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_geo" in indicators
        assert indicators["has_geo"] == 2
        assert mult == pytest.approx(1.2)

    def test_has_geo_shape(self):
        c = self._zero_counts()
        c["geo_shape_count"] = 1
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_geo" in indicators
        assert indicators["has_geo"] == 1

    def test_has_geo_combined_count(self):
        c = self._zero_counts()
        c["geo_distance_count"] = 2
        c["geo_shape_count"] = 3
        indicators, _ = evaluate_cost_indicators(c)
        assert indicators["has_geo"] == 5

    def test_geo_bbox_alone_no_indicator(self):
        """geo_bounding_box is cheap — should NOT trigger has_geo."""
        c = self._zero_counts()
        c["geo_bbox_count"] = 5
        indicators, _ = evaluate_cost_indicators(c)
        assert "has_geo" not in indicators

    def test_has_knn(self):
        c = self._zero_counts()
        c["knn_clause_count"] = 1
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_knn" in indicators
        assert indicators["has_knn"] == 1
        assert mult == pytest.approx(1.2)

    def test_excessive_bool(self):
        c = self._zero_counts()
        c["bool_must_count"] = 25
        c["bool_should_count"] = 25
        indicators, mult = evaluate_cost_indicators(c)
        assert "excessive_bool" in indicators
        assert indicators["excessive_bool"] == 50
        assert mult == pytest.approx(1.3)

    def test_excessive_bool_below_threshold(self):
        c = self._zero_counts()
        c["bool_must_count"] = 20
        c["bool_should_count"] = 20
        c["bool_filter_count"] = 9
        indicators, _ = evaluate_cost_indicators(c)
        assert "excessive_bool" not in indicators

    def test_large_terms_list(self):
        c = self._zero_counts()
        c["terms_values_count"] = 500
        indicators, mult = evaluate_cost_indicators(c)
        assert "large_terms_list" in indicators
        assert indicators["large_terms_list"] == 500
        assert mult == pytest.approx(1.2)

    def test_large_terms_below_threshold(self):
        c = self._zero_counts()
        c["terms_values_count"] = 499
        indicators, _ = evaluate_cost_indicators(c)
        assert "large_terms_list" not in indicators

    def test_deep_aggs(self):
        c = self._zero_counts()
        c["agg_clause_count"] = 10
        indicators, mult = evaluate_cost_indicators(c)
        assert "deep_aggs" in indicators
        assert indicators["deep_aggs"] == 10
        assert mult == pytest.approx(1.3)

    def test_deep_aggs_below_threshold(self):
        c = self._zero_counts()
        c["agg_clause_count"] = 9
        indicators, _ = evaluate_cost_indicators(c)
        assert "deep_aggs" not in indicators

    def test_multiple_indicators_multiplicative(self):
        """script (1.5) + wildcard (1.3) = 1.95"""
        c = self._zero_counts()
        c["script_clause_count"] = 2
        c["wildcard_clause_count"] = 3
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_script" in indicators
        assert "has_wildcard" in indicators
        assert indicators["has_script"] == 2
        assert indicators["has_wildcard"] == 3
        assert mult == pytest.approx(1.5 * 1.3)

    def test_three_indicators_compound(self):
        """script (1.5) + nested (1.3) + geo (1.2) = 2.34"""
        c = self._zero_counts()
        c["script_clause_count"] = 1
        c["nested_clause_count"] = 2
        c["geo_distance_count"] = 1
        indicators, mult = evaluate_cost_indicators(c)
        assert len(indicators) == 3
        assert indicators == {"has_script": 1, "has_nested": 2, "has_geo": 1}
        assert mult == pytest.approx(1.5 * 1.3 * 1.2)


# ---------------------------------------------------------------------------
# Stress formulas
# ---------------------------------------------------------------------------

class TestCalcStress:
    def _ctx(self, **kw):
        defaults = dict(es_took_ms=100, hits=10000, size=100, shards_total=5, docs_affected=500)
        defaults.update(kw)
        return StressContext(**defaults)

    def test_search_at_baseline(self):
        """All values at baseline -> base = 0.55+0.20+0.15+0.10 = 1.0"""
        score = calc_stress("_search", self._ctx())
        assert score == pytest.approx(1.0)

    def test_search_with_multiplier(self):
        score = calc_stress("_search", self._ctx(), stress_multiplier=1.5)
        assert score == pytest.approx(1.5)

    def test_search_double_took(self):
        score = calc_stress("_search", self._ctx(es_took_ms=200))
        expected = 0.55 * 2.0 + 0.20 * 1.0 + 0.15 * 1.0 + 0.10 * 1.0
        assert score == pytest.approx(expected)

    def test_search_zero_values(self):
        score = calc_stress("_search", self._ctx(es_took_ms=0, hits=0, size=0, shards_total=0))
        assert score == pytest.approx(0.0)

    def test_bulk_at_baseline(self):
        score = calc_stress("_bulk", self._ctx())
        expected = 0.45 * 1.0 + 0.55 * 1.0
        assert score == pytest.approx(expected)

    def test_bulk_ignores_multiplier(self):
        """_bulk is in _NO_MULTIPLIER_OPS."""
        score_no_mult = calc_stress("_bulk", self._ctx())
        score_with_mult = calc_stress("_bulk", self._ctx(), stress_multiplier=2.0)
        assert score_no_mult == score_with_mult

    def test_update_by_query_at_baseline(self):
        score = calc_stress("_update_by_query", self._ctx())
        expected = 0.40 * 1.0 + 0.35 * 1.0 + 0.25 * 1.0
        assert score == pytest.approx(expected)

    def test_delete_by_query_same_formula(self):
        ctx = self._ctx()
        assert calc_stress("_delete_by_query", ctx) == calc_stress("_update_by_query", ctx)

    def test_update_at_baseline(self):
        score = calc_stress("_update", self._ctx())
        expected = 0.60 * 1.0 + 0.40 * 1.0
        assert score == pytest.approx(expected)

    def test_update_applies_multiplier(self):
        score = calc_stress("_update", self._ctx(), stress_multiplier=1.5)
        expected = (0.60 * 1.0 + 0.40 * 1.0) * 1.5
        assert score == pytest.approx(expected)

    def test_create_at_baseline(self):
        score = calc_stress("_create", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_create_ignores_multiplier(self):
        score_no = calc_stress("_create", self._ctx())
        score_with = calc_stress("_create", self._ctx(), stress_multiplier=2.0)
        assert score_no == score_with

    def test_index_at_baseline(self):
        score = calc_stress("index", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_index_ignores_multiplier(self):
        score_no = calc_stress("index", self._ctx())
        score_with = calc_stress("index", self._ctx(), stress_multiplier=2.0)
        assert score_no == score_with

    def test_delete_at_baseline(self):
        score = calc_stress("delete", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_delete_ignores_multiplier(self):
        score_no = calc_stress("delete", self._ctx())
        score_with = calc_stress("delete", self._ctx(), stress_multiplier=2.0)
        assert score_no == score_with

    def test_unknown_operation_uses_doc_write(self):
        score = calc_stress("_unknown", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_stress_unbounded(self):
        """Score should exceed 1.0 for extreme values."""
        ctx = self._ctx(es_took_ms=10000, hits=1000000, shards_total=100, size=10000)
        score = calc_stress("_search", ctx)
        assert score > 10.0

    def test_search_high_multiplier(self):
        """Extreme multiplier compounds stress."""
        ctx = self._ctx(es_took_ms=500)
        score = calc_stress("_search", ctx, stress_multiplier=3.0)
        base = 0.55 * 5.0 + 0.20 * 1.0 + 0.15 * 1.0 + 0.10 * 1.0
        assert score == pytest.approx(base * 3.0)


# ---------------------------------------------------------------------------
# Integration: count_clauses -> evaluate_cost_indicators
# ---------------------------------------------------------------------------

class TestClauseCountToCostIndicators:
    def test_script_heavy_query(self):
        body = {
            "query": {"script_score": {
                "query": {"match_all": {}},
                "script": {"source": "doc['price'].value"},
            }},
            "script_fields": {
                "f1": {"script": {"source": "1"}},
                "f2": {"script": {"source": "2"}},
            },
        }
        counts = count_clauses(body)
        indicators, mult = evaluate_cost_indicators(counts)
        assert "has_script" in indicators
        assert indicators["has_script"] == 3  # 1 in query + 2 in script_fields

    def test_complex_query_multiple_indicators(self):
        body = {
            "query": {"bool": {"must": [
                {"wildcard": {"title": {"value": "*test*"}}},
                {"nested": {"path": "comments", "query": {"match_all": {}}}},
            ]}},
            "runtime_mappings": {"x": {"type": "keyword", "script": {}}},
        }
        counts = count_clauses(body)
        indicators, mult = evaluate_cost_indicators(counts)
        assert "has_wildcard" in indicators
        assert "has_nested" in indicators
        assert "has_runtime_mapping" in indicators
        assert indicators["has_wildcard"] == 1
        assert indicators["has_nested"] == 1
        assert indicators["has_runtime_mapping"] == 1
        assert mult == pytest.approx(1.3 * 1.3 * 1.5)
