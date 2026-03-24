"""
Stress score calculation — research-backed formula.
All values default to 0; score is unbounded above.
"""

import math
import os
from dataclasses import dataclass
from typing import Any, Callable

from _baselines import get_baselines

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
    gateway_took_ms:  float
    hits:             int
    shards_total:     int
    docs_affected:    int


def normalize(value: float, baseline: float) -> float:
    return value / baseline if baseline else 0.0


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
    ("unbound_hits",        lambda c: c.get("hits_lower_bound", 0) >= 1,  1.3,
                            lambda c: 1),
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

def _stress_query(ctx: StressContext, bl: dict[str, float]) -> float:
    return (
        0.50 * normalize(ctx.es_took_ms, bl["took_ms"])
        + 0.15 * normalize(ctx.shards_total, bl["shards_total"])
        + 0.35 * normalize(ctx.hits, bl["hits"])
    )


def _stress_bulk(ctx: StressContext, bl: dict[str, float]) -> float:
    return (
        0.45 * normalize(ctx.es_took_ms, bl["took_ms"])
        + 0.55 * normalize(ctx.docs_affected, bl["docs_affected"])
    )


def _stress_by_query(ctx: StressContext, bl: dict[str, float]) -> float:
    return (
        0.40 * normalize(ctx.es_took_ms, bl["took_ms"])
        + 0.35 * normalize(ctx.docs_affected, bl["docs_affected"])
        + 0.25 * normalize(ctx.shards_total, bl["shards_total"])
    )


def _stress_update(ctx: StressContext, bl: dict[str, float]) -> float:
    return (
        0.60 * normalize(ctx.es_took_ms, bl["took_ms"])
        + 0.40 * normalize(ctx.shards_total, bl["shards_total"])
    )


def _stress_doc_write(ctx: StressContext, bl: dict[str, float]) -> float:
    return (
        0.70 * normalize(ctx.es_took_ms, bl["took_ms"])
        + 0.30 * normalize(ctx.shards_total, bl["shards_total"])
    )


_STRESS_DISPATCH: dict[str, Callable[[StressContext, dict[str, float]], float]] = {
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

_AGG_THRESHOLD = int(os.environ.get("STRESS_AGG_THRESHOLD", 3))
_AGG_WEIGHT = float(os.environ.get("STRESS_AGG_WEIGHT", 0.10))
_AGG_CAP = float(os.environ.get("STRESS_AGG_CAP", 0.50))

# (count_key, threshold, weight, cap) — applied additively to base before multiplier
_CONTINUOUS_BONUSES: list[tuple[str, int, float, float]] = [
    ("bool_total",            _CLAUSE_THRESHOLD, _CLAUSE_WEIGHT, _CLAUSE_CAP),
    ("agg_clause_count",      _AGG_THRESHOLD,    _AGG_WEIGHT,    _AGG_CAP),
    ("wildcard_clause_count", 1, 0.10, 0.50),
    ("nested_clause_count",   1, 0.10, 0.50),
    ("fuzzy_clause_count",    1, 0.10, 0.50),
    ("geo_total",             1, 0.10, 0.50),
    ("knn_clause_count",      1, 0.10, 0.50),
    ("script_clause_count",   1, 0.10, 0.50),
    ("terms_values_count",    50, 0.10, 0.50),
]


def calc_stress(
    operation: str,
    ctx: StressContext,
    stress_multiplier: float = 1.0,
    clause_counts: dict[str, int] | None = None,
) -> tuple[float, dict[str, float]]:
    bl = get_baselines()
    formula = _STRESS_DISPATCH.get(operation, _stress_doc_write)
    base = formula(ctx, bl)
    if operation in _NO_MULTIPLIER_OPS:
        return base, {}
    bonuses: dict[str, float] = {}
    if clause_counts:
        counts = {
            **clause_counts,
            "bool_total": (clause_counts["bool_must_count"] + clause_counts["bool_should_count"]
                           + clause_counts["bool_filter_count"] + clause_counts["bool_must_not_count"]),
            "geo_total": (clause_counts["geo_distance_count"] + clause_counts["geo_shape_count"]
                          + clause_counts["geo_bbox_count"]),
        }
        for key, threshold, weight, cap in _CONTINUOUS_BONUSES:
            count = counts[key]
            if count > threshold:
                bonus = min(weight * math.log(1 + count - threshold), cap)
                bonuses[key] = bonus
                base += bonus
    return base * stress_multiplier, bonuses
