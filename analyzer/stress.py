"""
Stress score calculation — research-backed formula.
All values default to 0; score is unbounded above.
"""

BASELINES = {
    "took_ms":          100,
    "hits":            1000,
    "shards_total":       5,
    "size":             100,
    "docs_affected":    100,
    "query_complexity":  10,
}

# Clause keys that map 1:1 to a count field (used in walk())
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
    "agg_clause_count":       3,
    "runtime_mapping_count":  5,
    "script_clause_count":    6,
}


def norm(value: float, baseline: float) -> float:
    return value / baseline


def calc_query_complexity(body: dict) -> dict:
    """
    Count clause types and return raw counts + weighted score.
    Handles top-level aggs, knn, and runtime_mappings; recurses into body["query"].
    """
    counts = {k: 0 for k in CLAUSE_WEIGHTS}

    # Top-level batch counts
    aggs = body.get("aggs") or body.get("aggregations")
    if isinstance(aggs, dict):
        counts["agg_clause_count"] = len(aggs)

    if isinstance(body.get("runtime_mappings"), dict):
        counts["runtime_mapping_count"] = len(body["runtime_mappings"])

    if "knn" in body:
        counts["knn_clause_count"] += 1

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in _SINGLE_CLAUSE_KEYS:
                    counts[_SINGLE_CLAUSE_KEYS[k]] += 1
                elif k in _GEO_CLAUSE_KEYS:
                    counts["geo_clause_count"] += 1
                elif k == "terms" and isinstance(v, dict):
                    for field_vals in v.values():
                        if isinstance(field_vals, list):
                            counts["terms_values_count"] += len(field_vals)
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(body.get("query", {}))

    score = sum(w * counts[k] for k, w in CLAUSE_WEIGHTS.items())
    return {**counts, "query_complexity": score}


# ---------------------------------------------------------------------------
# Stress formulas — one function per operation class
# ---------------------------------------------------------------------------

def _stress_query(es_took_ms, hits, size, shards_total, docs_affected, query_complexity):
    return (
        0.40 * norm(es_took_ms, BASELINES["took_ms"])
        + 0.20 * norm(hits, BASELINES["hits"])
        + 0.15 * norm(query_complexity, BASELINES["query_complexity"])
        + 0.15 * norm(size, BASELINES["size"])
        + 0.10 * norm(shards_total, BASELINES["shards_total"])
    )


def _stress_insert(es_took_ms, hits, size, shards_total, docs_affected, query_complexity):
    return (
        0.40 * norm(es_took_ms, BASELINES["took_ms"])
        + 0.40 * norm(docs_affected, BASELINES["docs_affected"])
        + 0.20 * norm(shards_total, BASELINES["shards_total"])
    )


def _stress_by_query(es_took_ms, hits, size, shards_total, docs_affected, query_complexity):
    return (
        0.35 * norm(es_took_ms, BASELINES["took_ms"])
        + 0.30 * norm(docs_affected, BASELINES["docs_affected"])
        + 0.20 * norm(query_complexity, BASELINES["query_complexity"])
        + 0.15 * norm(shards_total, BASELINES["shards_total"])
    )


def _stress_update(es_took_ms, hits, size, shards_total, docs_affected, query_complexity):
    return (
        0.50 * norm(es_took_ms, BASELINES["took_ms"])
        + 0.30 * norm(query_complexity, BASELINES["query_complexity"])
        + 0.20 * norm(shards_total, BASELINES["shards_total"])
    )


def _stress_single(es_took_ms, hits, size, shards_total, docs_affected, query_complexity):
    return (
        0.70 * norm(es_took_ms, BASELINES["took_ms"])
        + 0.30 * norm(shards_total, BASELINES["shards_total"])
    )


_STRESS_DISPATCH = {
    "_search":          _stress_query,
    "_bulk":            _stress_insert,
    "_update_by_query": _stress_by_query,
    "_delete_by_query": _stress_by_query,
    "_update":          _stress_update,
    "_create":          _stress_single,
    "index":            _stress_single,
    "delete":           _stress_single,
}


def calc_stress(
    operation: str,
    es_took_ms: float,
    hits: int,
    size: int,
    shards_total: int,
    docs_affected: int,
    query_complexity: float,
) -> float:
    formula = _STRESS_DISPATCH.get(operation, _stress_single)
    return formula(es_took_ms, hits, size, shards_total, docs_affected, query_complexity)
