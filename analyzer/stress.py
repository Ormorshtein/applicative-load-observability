"""
Stress score calculation — research-backed formula.
All values default to 0; score is unbounded above.
"""

import math
import os
from dataclasses import dataclass
from typing import Any, Callable


def _load_baselines() -> dict:
    defaults = {
        "took_ms":          100,
        "hits":           10000,
        "shards_total":       5,
        "size":             100,
        "docs_affected":    500,
    }
    for key in defaults:
        env_val = os.environ.get(f"STRESS_BASELINE_{key.upper()}")
        if env_val is not None:
            defaults[key] = float(env_val)
    return defaults


BASELINES = _load_baselines()

# Clause keys that map 1:1 to a count field (used in _walk_query_clauses)
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


@dataclass
class StressContext:
    es_took_ms:       float
    hits:             int
    size:             int
    shards_total:     int
    docs_affected:    int


def normalize(value: float, baseline: float) -> float:
    return value / baseline


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
    for key, value in node.items():
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


_COST_INDICATOR_BOOL_THRESHOLD = int(os.environ.get("COST_INDICATOR_BOOL_THRESHOLD", 50))
_COST_INDICATOR_TERMS_THRESHOLD = int(os.environ.get("COST_INDICATOR_TERMS_THRESHOLD", 500))
_COST_INDICATOR_AGGS_THRESHOLD = int(os.environ.get("COST_INDICATOR_AGGS_THRESHOLD", 10))

# (name, condition, multiplier, detail_extractor)
_COST_INDICATORS: list[tuple[str, Callable[[dict], bool], float, Callable[[dict], int]]] = [
    ("has_script",          lambda c: c["script_clause_count"] >= 1,           1.5,
                            lambda c: c["script_clause_count"]),
    ("has_runtime_mapping", lambda c: c["runtime_mapping_count"] >= 1,         1.5,
                            lambda c: c["runtime_mapping_count"]),
    ("has_wildcard",        lambda c: c["wildcard_clause_count"] >= 1,         1.3,
                            lambda c: c["wildcard_clause_count"]),
    ("has_nested",          lambda c: c["nested_clause_count"] >= 1,           1.3,
                            lambda c: c["nested_clause_count"]),
    ("has_fuzzy",           lambda c: c["fuzzy_clause_count"] >= 1,            1.2,
                            lambda c: c["fuzzy_clause_count"]),
    ("has_geo",             lambda c: c["geo_distance_count"] + c["geo_shape_count"] >= 1, 1.2,
                            lambda c: c["geo_distance_count"] + c["geo_shape_count"]),
    ("has_knn",             lambda c: c["knn_clause_count"] >= 1,              1.2,
                            lambda c: c["knn_clause_count"]),
    ("excessive_bool",      lambda c: (c["bool_must_count"] + c["bool_should_count"] +
                                       c["bool_filter_count"] + c["bool_must_not_count"])
                                      >= _COST_INDICATOR_BOOL_THRESHOLD,       1.3,
                            lambda c: (c["bool_must_count"] + c["bool_should_count"] +
                                       c["bool_filter_count"] + c["bool_must_not_count"])),
    ("large_terms_list",    lambda c: c["terms_values_count"] >= _COST_INDICATOR_TERMS_THRESHOLD, 1.2,
                            lambda c: c["terms_values_count"]),
    ("deep_aggs",           lambda c: c["agg_clause_count"] >= _COST_INDICATOR_AGGS_THRESHOLD,    1.3,
                            lambda c: c["agg_clause_count"]),
]


def evaluate_cost_indicators(counts: dict) -> tuple[dict[str, int], float]:
    indicators = {}
    multiplier = 1.0
    for name, condition, mult, extract in _COST_INDICATORS:
        if condition(counts):
            indicators[name] = extract(counts)
            multiplier *= mult
    return indicators, multiplier


# ---------------------------------------------------------------------------
# Stress formulas — one function per operation class
# ---------------------------------------------------------------------------

def _stress_query(ctx: StressContext) -> float:
    return (
        0.55 * normalize(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.20 * normalize(ctx.shards_total, BASELINES["shards_total"])
        + 0.15 * normalize(ctx.hits, BASELINES["hits"])
        + 0.10 * normalize(ctx.size, BASELINES["size"])
    )


def _stress_bulk(ctx: StressContext) -> float:
    return (
        0.45 * normalize(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.55 * normalize(ctx.docs_affected, BASELINES["docs_affected"])
    )


def _stress_by_query(ctx: StressContext) -> float:
    return (
        0.40 * normalize(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.35 * normalize(ctx.docs_affected, BASELINES["docs_affected"])
        + 0.25 * normalize(ctx.shards_total, BASELINES["shards_total"])
    )


def _stress_update(ctx: StressContext) -> float:
    return (
        0.60 * normalize(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.40 * normalize(ctx.shards_total, BASELINES["shards_total"])
    )


def _stress_doc_write(ctx: StressContext) -> float:
    return (
        0.70 * normalize(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.30 * normalize(ctx.shards_total, BASELINES["shards_total"])
    )


_STRESS_DISPATCH: dict[str, Callable[[StressContext], float]] = {
    "_search":          _stress_query,
    "_bulk":            _stress_bulk,
    "_update_by_query": _stress_by_query,
    "_delete_by_query": _stress_by_query,
    "_update":          _stress_update,
    "_create":          _stress_doc_write,
    "index":            _stress_doc_write,
    "delete":           _stress_doc_write,
}


_NO_MULTIPLIER_OPS = {"_bulk", "_create", "index", "delete"}

_CLAUSE_THRESHOLD = int(os.environ.get("STRESS_CLAUSE_THRESHOLD", 4))
_CLAUSE_WEIGHT = float(os.environ.get("STRESS_CLAUSE_WEIGHT", 0.10))
_CLAUSE_CAP = float(os.environ.get("STRESS_CLAUSE_CAP", 0.50))


def calc_stress(
    operation: str,
    ctx: StressContext,
    stress_multiplier: float = 1.0,
    bool_clause_total: int = 0,
) -> float:
    formula = _STRESS_DISPATCH.get(operation, _stress_doc_write)
    base = formula(ctx)
    if operation in _NO_MULTIPLIER_OPS:
        return base
    if bool_clause_total > _CLAUSE_THRESHOLD:
        excess = bool_clause_total - _CLAUSE_THRESHOLD
        clause_bonus = min(_CLAUSE_WEIGHT * math.log(1 + excess), _CLAUSE_CAP)
        base += clause_bonus
    return base * stress_multiplier
