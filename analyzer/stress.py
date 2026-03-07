"""
Stress score calculation — research-backed formula.
All values default to 0; score is unbounded above.
"""

import math
from dataclasses import dataclass
from typing import Callable

BASELINES = {
    "took_ms":          100,
    "hits":            1000,
    "shards_total":       5,
    "size":             100,
    "docs_affected":    100,
    "query_complexity":  10,
}

# Clause keys that map 1:1 to a count field (used in _walk_query_clauses)
_SINGLE_CLAUSE_KEYS = {
    "wildcard": "wildcard_clause_count",
    "fuzzy":    "fuzzy_clause_count",
    "nested":   "nested_clause_count",
    "bool":     "bool_clause_count",
    "knn":      "knn_clause_count",
    "script":   "script_clause_count",
}

_GEO_CLAUSE_KEYS = {"geo_distance", "geo_shape", "geo_bounding_box", "geo_polygon", "geo_grid"}

CLAUSE_WEIGHTS = {
    "wildcard_clause_count":  4,
    "fuzzy_clause_count":     2,
    "geo_clause_count":       3,
    "nested_clause_count":    4,
    "bool_clause_count":      1,
    "terms_values_count":     1,
    "knn_clause_count":       2,
    "has_scroll":             3,
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
            elif key in _GEO_CLAUSE_KEYS:
                counts["geo_clause_count"] += 1
            elif key == "terms" and isinstance(value, dict):
                for field_vals in value.values():
                    if isinstance(field_vals, list):
                        counts["terms_values_count"] += len(field_vals)
            _walk_query_clauses(value, counts)
    elif isinstance(node, list):
        for item in node:
            _walk_query_clauses(item, counts)


def _count_agg_nodes(aggs_dict, depth=1):
    """Walk aggregation tree recursively.
    Returns (total_node_count, max_depth, depth_weighted_score).
    Deeper aggs are weighted heavier: depth 1→3, 2→5, 3+→8.
    """
    _DEPTH_WEIGHT = {1: 3, 2: 5}
    total = 0
    max_depth = depth
    weighted = 0
    for agg_def in aggs_dict.values():
        if not isinstance(agg_def, dict):
            continue
        total += 1
        w = _DEPTH_WEIGHT.get(depth, 8)
        weighted += w
        nested_aggs = agg_def.get("aggs") or agg_def.get("aggregations")
        if isinstance(nested_aggs, dict):
            sub_total, sub_max, sub_weighted = _count_agg_nodes(nested_aggs, depth + 1)
            total += sub_total
            max_depth = max(max_depth, sub_max)
            weighted += sub_weighted
    return total, max_depth, weighted


def _deep_pagination_score(body: dict) -> float:
    from_val = body.get("from", 0) or 0
    if from_val <= 0:
        return 0.0
    return math.log10(1 + from_val) * 4


def _count_clauses(body: dict) -> tuple[dict, int]:
    counts = {k: 0 for k in CLAUSE_WEIGHTS}
    counts["agg_node_count"] = 0
    counts["agg_max_depth"] = 0
    counts["pagination_depth"] = 0

    aggs = body.get("aggs") or body.get("aggregations")
    agg_weighted = 0
    if isinstance(aggs, dict):
        total, max_depth, agg_weighted = _count_agg_nodes(aggs)
        counts["agg_node_count"] = total
        counts["agg_max_depth"] = max_depth

    from_val = body.get("from", 0) or 0
    size_val = body.get("size", 0) or 0
    counts["pagination_depth"] = from_val + size_val

    counts["has_scroll"] = 1 if "scroll" in body else 0

    if isinstance(body.get("runtime_mappings"), dict):
        counts["runtime_mapping_count"] = len(body["runtime_mappings"])

    if "knn" in body:
        counts["knn_clause_count"] += 1

    _walk_query_clauses(body.get("query", {}), counts)
    return counts, agg_weighted


def calc_query_complexity(body: dict) -> dict:
    """Count clause types and return raw counts + weighted score."""
    counts, agg_weighted = _count_clauses(body)
    clause_score = sum(w * counts[k] for k, w in CLAUSE_WEIGHTS.items())
    pagination_score = _deep_pagination_score(body)
    score = clause_score + agg_weighted + pagination_score
    return {**counts, "query_complexity": score}


# ---------------------------------------------------------------------------
# Stress formulas — one function per operation class
# ---------------------------------------------------------------------------

def _stress_query(ctx: StressContext) -> float:
    return (
        0.40 * norm(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.20 * norm(ctx.hits, BASELINES["hits"])
        + 0.15 * norm(ctx.query_complexity, BASELINES["query_complexity"])
        + 0.15 * norm(ctx.size, BASELINES["size"])
        + 0.10 * norm(ctx.shards_total, BASELINES["shards_total"])
    )


def _stress_bulk(ctx: StressContext) -> float:
    return (
        0.40 * norm(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.40 * norm(ctx.docs_affected, BASELINES["docs_affected"])
        + 0.20 * norm(ctx.shards_total, BASELINES["shards_total"])
    )


def _stress_by_query(ctx: StressContext) -> float:
    return (
        0.35 * norm(ctx.es_took_ms, BASELINES["took_ms"])
        + 0.30 * norm(ctx.docs_affected, BASELINES["docs_affected"])
        + 0.20 * norm(ctx.query_complexity, BASELINES["query_complexity"])
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
