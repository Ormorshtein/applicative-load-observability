"""Unit tests for clause counting logic in analyzer/stress.py."""

from stress import count_clauses


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
        body = {"query": {"knn": {"field": "vec", "query_vector": [0.1], "k": 5}}}
        counts = count_clauses(body)
        assert counts["knn_clause_count"] == 1

    def test_knn_top_level_and_query(self):
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
        body = {"aggs": {}}
        for i in range(12):
            body["aggs"][f"a{i}"] = {"terms": {"field": f"f{i}"}}
        counts = count_clauses(body)
        assert counts["agg_clause_count"] == 12
