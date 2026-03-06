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

OP_MULTIPLIERS = {
    "agg":    1.3,
    "geo":    1.2,
    "knn":    1.2,
    "text":   1.0,
    "single": 1.0,
    "bulk":   1.0,
    "by_query": 1.0,
}


def norm(value: float, baseline: float) -> float:
    return value / baseline


def calc_query_complexity(body: dict) -> dict:
    """
    Count clause types and return raw counts + weighted score.
    Searches recursively through the query tree.
    """
    counts = {
        "wildcard_clause_count": 0,
        "fuzzy_clause_count": 0,
        "geo_clause_count": 0,
        "nested_clause_count": 0,
        "bool_clause_count": 0,
        "terms_values_count": 0,
    }

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "wildcard":
                    counts["wildcard_clause_count"] += 1
                elif k == "fuzzy":
                    counts["fuzzy_clause_count"] += 1
                elif k in {"geo_distance", "geo_shape", "geo_bounding_box",
                           "geo_polygon", "geo_grid"}:
                    counts["geo_clause_count"] += 1
                elif k == "nested":
                    counts["nested_clause_count"] += 1
                elif k == "bool":
                    counts["bool_clause_count"] += 1
                elif k == "terms" and isinstance(v, dict):
                    # terms: { "field": ["val1", "val2"] }
                    for field_vals in v.values():
                        if isinstance(field_vals, list):
                            counts["terms_values_count"] += len(field_vals)
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(body.get("query", {}))

    score = (
        3 * counts["wildcard_clause_count"]
        + 2 * counts["fuzzy_clause_count"]
        + 2 * counts["geo_clause_count"]
        + 2 * counts["nested_clause_count"]
        + 1 * counts["bool_clause_count"]
        + 1 * counts["terms_values_count"]
    )

    return {**counts, "query_complexity": score}


def calc_stress(
    operation_kind: str,
    operation_type: str,
    took_ms: float,
    hits: int,
    size: int,
    shards_total: int,
    docs_affected: int,
    query_complexity: float,
    has_script: bool,
    has_runtime_mappings: bool,
) -> float:
    if operation_kind == "query":
        base = (
            0.40 * norm(took_ms, BASELINES["took_ms"])
            + 0.20 * norm(hits, BASELINES["hits"])
            + 0.15 * norm(query_complexity, BASELINES["query_complexity"])
            + 0.15 * norm(size, BASELINES["size"])
            + 0.10 * norm(shards_total, BASELINES["shards_total"])
        )
        stress = base * OP_MULTIPLIERS.get(operation_type, 1.0)
        if has_script:
            stress *= 1.5
        if has_runtime_mappings:
            stress *= 1.3
        return stress

    if operation_kind == "insert":
        return (
            0.40 * norm(took_ms, BASELINES["took_ms"])
            + 0.40 * norm(docs_affected, BASELINES["docs_affected"])
            + 0.20 * norm(shards_total, BASELINES["shards_total"])
        )

    if operation_kind in ("update", "delete"):
        if operation_type == "by_query":
            stress = (
                0.40 * norm(took_ms, BASELINES["took_ms"])
                + 0.40 * norm(docs_affected, BASELINES["docs_affected"])
                + 0.20 * norm(shards_total, BASELINES["shards_total"])
            )
            if has_script:
                stress *= 1.5
            return stress
        # single update / delete
        return 0.5 * norm(took_ms, BASELINES["took_ms"]) + 0.5

    # fallback
    return 0.5 * norm(took_ms, BASELINES["took_ms"]) + 0.5
