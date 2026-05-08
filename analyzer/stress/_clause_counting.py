"""Clause counting — walk an ES query body and tally structural clause types."""

from typing import Any

_SINGLE_CLAUSE_KEYS = {
    "wildcard": "wildcard_clause_count",
    "regexp":   "wildcard_clause_count",
    "prefix":   "wildcard_clause_count",
    "fuzzy":    "fuzzy_clause_count",
    "nested":   "nested_clause_count",
    "bool":     "bool_clause_count",
    "knn":      "knn_clause_count",
    "script":   "script_clause_count",
    "geo_distance":     "geo_distance_count",
    "geo_shape":        "geo_shape_count",
    "geo_polygon":      "geo_shape_count",
    "geo_bounding_box": "geo_bbox_count",
    "geo_grid":         "geo_bbox_count",
}

_ALL_COUNT_FIELDS = [
    "bool_clause_count", "bool_must_count", "bool_should_count",
    "bool_filter_count", "bool_must_not_count", "terms_values_count",
    "knn_clause_count", "fuzzy_clause_count", "geo_bbox_count",
    "geo_distance_count", "geo_shape_count", "agg_clause_count",
    "wildcard_clause_count", "nested_clause_count",
    "runtime_mapping_count", "script_clause_count",
]


def _walk_query_clauses(node: Any, counts: dict[str, int]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SINGLE_CLAUSE_KEYS:
                counts[_SINGLE_CLAUSE_KEYS[key]] += 1
            if key == "bool" and isinstance(value, dict):
                for sub_key in ("must", "should", "filter", "must_not"):
                    sub = value.get(sub_key)
                    if isinstance(sub, list):
                        counts[f"bool_{sub_key}_count"] += len(sub)
                    elif isinstance(sub, dict):
                        counts[f"bool_{sub_key}_count"] += 1
            elif key == "terms" and isinstance(value, dict):
                for field_vals in value.values():
                    if isinstance(field_vals, list):
                        counts["terms_values_count"] += len(field_vals)
            _walk_query_clauses(value, counts)
    elif isinstance(node, list):
        for item in node:
            _walk_query_clauses(item, counts)


def _count_aggs(node: Any) -> int:
    if not isinstance(node, dict):
        return 0
    count = 0
    for _key, value in node.items():
        if isinstance(value, dict):
            count += 1
            count += _count_aggs(value.get("aggs") or value.get("aggregations") or {})
    return count


def count_clauses(body: dict) -> dict[str, int]:
    counts: dict[str, int] = {k: 0 for k in _ALL_COUNT_FIELDS}

    aggs = body.get("aggs") or body.get("aggregations")
    if isinstance(aggs, dict):
        counts["agg_clause_count"] = _count_aggs(aggs)

    if isinstance(body.get("runtime_mappings"), dict):
        counts["runtime_mapping_count"] = len(body["runtime_mappings"])

    if "knn" in body:
        counts["knn_clause_count"] += 1

    _walk_query_clauses(body.get("query", {}), counts)
    _walk_query_clauses(body.get("script_fields", {}), counts)
    return counts
