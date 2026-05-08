"""Stress score computation — pure functions, no I/O."""

from ..parser import parse_geo_vertex_count
from ..stress import (
    _ALL_COUNT_FIELDS,
    StressContext,
    calc_stress,
    count_clauses,
    evaluate_cost_indicators,
)
from ._models import RawFields, StressResult

_QUERY_OPS: frozenset[str] = frozenset({
    "_search", "_msearch", "_count", "_explain", "_validate",
    "_update_by_query", "_delete_by_query",
})


def compute_stress(
    operation: str,
    raw: RawFields,
    es_took_ms: float,
    hits: int,
    hits_lower_bound: bool,
    shards_total: int,
    docs_affected: int,
    bulk_doc_count: int,
) -> StressResult:
    geo_vertex_count = 0
    if operation in _QUERY_OPS:
        clause_counts = count_clauses(raw.request_body)
        clause_counts["hits_lower_bound"] = int(hits_lower_bound)
        geo_vertex_count = parse_geo_vertex_count(raw.request_body)
        clause_counts["geo_vertex_count"] = geo_vertex_count
        cost_indicators, stress_multiplier, indicator_multipliers = (
            evaluate_cost_indicators(clause_counts)
        )
    else:
        clause_counts = {k: 0 for k in _ALL_COUNT_FIELDS}
        cost_indicators, stress_multiplier, indicator_multipliers = {}, 1.0, {}

    ctx = StressContext(
        es_took_ms=es_took_ms,
        gateway_took_ms=raw.gateway_took_ms,
        hits=hits,
        shards_total=shards_total,
        docs_affected=docs_affected,
        bulk_doc_count=bulk_doc_count,
    )
    score, bonuses, components = calc_stress(
        operation, ctx, stress_multiplier, clause_counts,
    )
    return StressResult(
        clause_counts=clause_counts,
        cost_indicators=cost_indicators,
        stress_multiplier=stress_multiplier,
        indicator_multipliers=indicator_multipliers,
        geo_vertex_count=geo_vertex_count,
        score=score,
        bonuses=bonuses,
        components=components,
    )
