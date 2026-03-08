"""Unit tests for cost indicator evaluation in analyzer/stress.py."""

import pytest

from stress import evaluate_cost_indicators, count_clauses


def _zero_counts() -> dict[str, int]:
    return {k: 0 for k in [
        "bool_clause_count", "bool_must_count", "bool_should_count",
        "bool_filter_count", "bool_must_not_count", "terms_values_count",
        "knn_clause_count", "fuzzy_clause_count", "geo_bbox_count",
        "geo_distance_count", "geo_shape_count", "agg_clause_count",
        "wildcard_clause_count", "nested_clause_count",
        "runtime_mapping_count", "script_clause_count",
    ]}


class TestEvaluateCostIndicators:
    def test_no_indicators(self):
        indicators, mult = evaluate_cost_indicators(_zero_counts())
        assert indicators == {}
        assert mult == 1.0

    def test_has_script(self):
        c = _zero_counts()
        c["script_clause_count"] = 3
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_script" in indicators
        assert indicators["has_script"] == 3
        assert mult == pytest.approx(1.5)

    def test_has_runtime_mapping(self):
        c = _zero_counts()
        c["runtime_mapping_count"] = 2
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_runtime_mapping" in indicators
        assert indicators["has_runtime_mapping"] == 2
        assert mult == pytest.approx(1.5)

    def test_has_wildcard(self):
        c = _zero_counts()
        c["wildcard_clause_count"] = 4
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_wildcard" in indicators
        assert indicators["has_wildcard"] == 4
        assert mult == pytest.approx(1.3)

    def test_has_nested(self):
        c = _zero_counts()
        c["nested_clause_count"] = 1
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_nested" in indicators
        assert indicators["has_nested"] == 1
        assert mult == pytest.approx(1.3)

    def test_has_fuzzy(self):
        c = _zero_counts()
        c["fuzzy_clause_count"] = 1
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_fuzzy" in indicators
        assert indicators["has_fuzzy"] == 1
        assert mult == pytest.approx(1.2)

    def test_has_geo_distance(self):
        c = _zero_counts()
        c["geo_distance_count"] = 2
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_geo" in indicators
        assert indicators["has_geo"] == 2
        assert mult == pytest.approx(1.2)

    def test_has_geo_shape(self):
        c = _zero_counts()
        c["geo_shape_count"] = 1
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_geo" in indicators
        assert indicators["has_geo"] == 1

    def test_has_geo_combined_count(self):
        c = _zero_counts()
        c["geo_distance_count"] = 2
        c["geo_shape_count"] = 3
        indicators, _ = evaluate_cost_indicators(c)
        assert indicators["has_geo"] == 5

    def test_geo_bbox_alone_no_indicator(self):
        """geo_bounding_box is cheap — should NOT trigger has_geo."""
        c = _zero_counts()
        c["geo_bbox_count"] = 5
        indicators, _ = evaluate_cost_indicators(c)
        assert "has_geo" not in indicators

    def test_has_knn(self):
        c = _zero_counts()
        c["knn_clause_count"] = 1
        indicators, mult = evaluate_cost_indicators(c)
        assert "has_knn" in indicators
        assert indicators["has_knn"] == 1
        assert mult == pytest.approx(1.2)

    def test_excessive_bool(self):
        c = _zero_counts()
        c["bool_must_count"] = 25
        c["bool_should_count"] = 25
        indicators, mult = evaluate_cost_indicators(c)
        assert "excessive_bool" in indicators
        assert indicators["excessive_bool"] == 50
        assert mult == pytest.approx(1.3)

    def test_excessive_bool_below_threshold(self):
        c = _zero_counts()
        c["bool_must_count"] = 20
        c["bool_should_count"] = 20
        c["bool_filter_count"] = 9
        indicators, _ = evaluate_cost_indicators(c)
        assert "excessive_bool" not in indicators

    def test_large_terms_list(self):
        c = _zero_counts()
        c["terms_values_count"] = 500
        indicators, mult = evaluate_cost_indicators(c)
        assert "large_terms_list" in indicators
        assert indicators["large_terms_list"] == 500
        assert mult == pytest.approx(1.2)

    def test_large_terms_below_threshold(self):
        c = _zero_counts()
        c["terms_values_count"] = 499
        indicators, _ = evaluate_cost_indicators(c)
        assert "large_terms_list" not in indicators

    def test_deep_aggs(self):
        c = _zero_counts()
        c["agg_clause_count"] = 10
        indicators, mult = evaluate_cost_indicators(c)
        assert "deep_aggs" in indicators
        assert indicators["deep_aggs"] == 10
        assert mult == pytest.approx(1.3)

    def test_deep_aggs_below_threshold(self):
        c = _zero_counts()
        c["agg_clause_count"] = 9
        indicators, _ = evaluate_cost_indicators(c)
        assert "deep_aggs" not in indicators

    def test_multiple_indicators_multiplicative(self):
        """script (1.5) + wildcard (1.3) = 1.95"""
        c = _zero_counts()
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
        c = _zero_counts()
        c["script_clause_count"] = 1
        c["nested_clause_count"] = 2
        c["geo_distance_count"] = 1
        indicators, mult = evaluate_cost_indicators(c)
        assert len(indicators) == 3
        assert indicators == {"has_script": 1, "has_nested": 2, "has_geo": 1}
        assert mult == pytest.approx(1.5 * 1.3 * 1.2)


class TestClauseCountToCostIndicators:
    """Integration: count_clauses -> evaluate_cost_indicators."""

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
        assert indicators["has_script"] == 3

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
