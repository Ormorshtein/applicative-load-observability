"""
Stress score calculation — research-backed formula.
All values default to 0; score is unbounded above.
"""

import os
from dataclasses import dataclass
from typing import Callable


def _load_baselines() -> dict:
    defaults = {
        "took_ms":          100,
        "hits":           10000,
        "shards_total":       5,
        "size":             100,
        "docs_affected":    500,
        "query_complexity":  10,
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

CLAUSE_WEIGHTS = {
    "wildcard_clause_count":  4,
    "fuzzy_clause_count":     3,
    "geo_distance_count":     3,
    "geo_shape_count":        4,
    "geo_bbox_count":         1,
    "nested_clause_count":    5,
    "bool_clause_count":      1,
    "terms_values_count":     1,
    "knn_clause_count":       4,
    "agg_clause_count":       3,
    "runtime_mapping_count":  5,
    "script_clause_count":    6,
}


@dataclass
class StressContext:
    es_took_ms:       float
    hits:             int
    size:             int
    shards_total:     int
    docs_affected:    int
    query_complexity: float


def norm(value: float, baseline: float) -> float:
    return value / baseline


def _walk_query_clauses(node, counts: dict) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SINGLE_CLAUSE_KEYS:
                counts[_SINGLE_CLAUSE_KEYS[key]] += 1
            elif key == "terms" and isinstance(value, dict):
                for field_vals in value.values():
                    if isinstance(field_vals, list):
                        counts["terms_values_count"] += len(field_vals)
            _walk_query_clauses(value, counts)
    elif isinstance(node, list):
        for item in node:
            _walk_query_clauses(item, counts)


def _count_aggs(node) -> int:
    if not isinstance(node, dict):
        return 0
    count = 0
    for key, value in node.items():
        if isinstance(value, dict):
            count += 1
            count += _count_aggs(value.get("aggs") or value.get("aggregations") or {})
    return count


def _count_clauses(body: dict) -> dict:
    counts = {k: 0 for k in CLAUSE_WEIGHTS}

    aggs = body.get("aggs") or body.get("aggregations")
    if isinstance(aggs, dict):
        counts["agg_clause_count"] = _count_aggs(aggs)

    if isinstance(body.get("runtime_mappings"), dict):
        counts["runtime_mapping_count"] = len(body["runtime_mappings"])

    if "knn" in body:
        counts["knn_clause_count"] += 1

    _walk_query_clauses(body.get("query", {}), counts)
    return counts


def calc_query_complexity(body: dict) -> dict:
    """Count clause types and return raw counts + weighted score."""
    counts = _count_clauses(body)
    score = sum(w * counts[k] for k, w in CLAUSE_WEIGHTS.items())
    return {**counts, "query_complexity": score}


# ---------------------------------------------------------------------------
# Stress formulas — one function per operation class
# ---------------------------------------------------------------------------

def _stress_query(ctx: StressContext) -> float:
    return (
        0.45 * norm(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.25 * norm(ctx.query_complexity, BASELINES["query_complexity"])
        + 0.15 * norm(ctx.shards_total, BASELINES["shards_total"])
        + 0.10 * norm(ctx.hits, BASELINES["hits"])
        + 0.05 * norm(ctx.size, BASELINES["size"])
    )


def _stress_bulk(ctx: StressContext) -> float:
    return (
        0.45 * norm(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.55 * norm(ctx.docs_affected, BASELINES["docs_affected"])
    )


def _stress_by_query(ctx: StressContext) -> float:
    return (
        0.30 * norm(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.30 * norm(ctx.docs_affected, BASELINES["docs_affected"])
        + 0.25 * norm(ctx.query_complexity, BASELINES["query_complexity"])
        + 0.15 * norm(ctx.shards_total, BASELINES["shards_total"])
    )


def _stress_update(ctx: StressContext) -> float:
    return (
        0.50 * norm(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.30 * norm(ctx.query_complexity, BASELINES["query_complexity"])
        + 0.20 * norm(ctx.shards_total, BASELINES["shards_total"])
    )


def _stress_doc_write(ctx: StressContext) -> float:
    return (
        0.70 * norm(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.30 * norm(ctx.shards_total, BASELINES["shards_total"])
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


def calc_stress(operation: str, ctx: StressContext) -> float:
    formula = _STRESS_DISPATCH.get(operation, _stress_doc_write)
    return formula(ctx)
