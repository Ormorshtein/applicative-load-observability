"""
Builds the observability record from a raw Nginx payload.
No I/O — all functions are pure transformations.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypedDict

from .parser import (
    parse_applicative_provider,
    parse_docs_affected,
    parse_es_took_ms,
    parse_geo_vertex_count,
    parse_hits,
    parse_labels,
    parse_msearch_pairs,
    parse_operation,
    parse_shards_total,
    parse_shards_total_bulk,
    parse_size,
    parse_target,
    parse_user_agent,
    parse_username,
    scrub_bulk_template,
    scrub_template,
)
from .stress import (
    _ALL_COUNT_FIELDS,
    StressContext,
    calc_stress,
    count_clauses,
    evaluate_cost_indicators,
)


def _utc_timestamp() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
_STRESS_PRECISION = 4


@dataclass
class RawFields:
    method:               str
    path:                 str
    headers:              dict
    request_body:         dict
    request_body_raw:     str
    response_body:        dict
    client_host:          str
    response_status:      int
    gateway_took_ms:      float
    request_size_bytes:   int
    response_size_bytes:  int


def _parse_json_field(raw: str) -> dict[str, Any]:
    """Safely parse a JSON string; return {} on failure."""
    if not raw:
        return {}
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        return {}


def _parse_upstream_response_time(raw: str) -> float:
    """Convert upstream_response_time (seconds string) to milliseconds."""
    if not raw:
        return 0.0
    try:
        return float(raw) * 1000
    except (ValueError, TypeError):
        return 0.0


def _parse_content_length(raw: str) -> int:
    """Convert content_length string to int bytes."""
    if not raw:
        return 0
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 0


def extract_raw_fields(payload: dict) -> RawFields:
    raw_body = payload.get("request_body", "")
    return RawFields(
        method=              payload.get("method", "GET"),
        path=                payload.get("path", "/"),
        headers=             payload.get("headers", {}),
        request_body=        _parse_json_field(raw_body),
        request_body_raw=    raw_body,
        response_body=       _parse_json_field(payload.get("response_body", "")),
        client_host=         payload.get("client_host", ""),
        response_status=     int(payload.get("response_status", 0)),
        gateway_took_ms=     _parse_upstream_response_time(
                                 payload.get("upstream_response_time", "")),
        request_size_bytes=  _parse_content_length(
                                 payload.get("content_length", "")),
        response_size_bytes= int(payload.get("response_size_bytes", 0)),
    )


_CLAUSE_COUNT_OUTPUT_KEYS = {
    "bool_clause_count":    "bool",
    "bool_must_count":      "bool_must",
    "bool_should_count":    "bool_should",
    "bool_filter_count":    "bool_filter",
    "bool_must_not_count":  "bool_must_not",
    "terms_values_count":   "terms_values",
    "knn_clause_count":     "knn",
    "fuzzy_clause_count":   "fuzzy",
    "geo_bbox_count":       "geo_bbox",
    "geo_distance_count":   "geo_distance",
    "geo_shape_count":      "geo_shape",
    "agg_clause_count":     "agg",
    "wildcard_clause_count": "wildcard",
    "nested_clause_count":  "nested",
    "runtime_mapping_count": "runtime_mapping",
    "script_clause_count":  "script",
}

_QUERY_OPS = frozenset({
    "_search", "_msearch", "_count", "_explain", "_validate",
    "_update_by_query", "_delete_by_query",
})
_ES_NANOSECOND_BUG_RATIO = 1000


# ---------------------------------------------------------------------------
# Output TypedDicts — schema-as-code for the observability record
# ---------------------------------------------------------------------------

class IdentitySection(TypedDict):
    username: str
    applicative_provider: str
    user_agent: str
    client_host: str
    labels: list[str]


class RequestSection(TypedDict, total=False):
    method: str
    path: str
    operation: str
    target: str
    template: str
    body: str
    size_bytes: int
    size: int
    geo_vertex_count: int


class ResponseSection(TypedDict):
    status: int
    es_took_ms: float
    gateway_took_ms: float
    hits: int
    shards_total: int
    docs_affected: int
    size_bytes: int


class StressSection(TypedDict):
    score: float
    base: float
    multiplier: float
    components: dict[str, float]
    bonuses: dict[str, float]
    cost_indicator_count: int
    cost_indicator_names: list[str]


class ObservabilityRecord(TypedDict):
    """The full record indexed into Elasticsearch."""

    timestamp: str  # key is "@timestamp" in output
    identity: IdentitySection
    request: RequestSection
    response: ResponseSection
    clause_counts: dict[str, int]
    cost_indicators: dict[str, int]
    stress: StressSection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _output_clause_counts(counts: dict[str, int]) -> dict[str, int]:
    return {out: counts[internal] for internal, out in _CLAUSE_COUNT_OUTPUT_KEYS.items()}


def _fix_es_nanosecond_bug(operation: str, es_took_ms: float, gateway_took_ms: float) -> float:
    """ES 8.13-8.15 bulk bug: took sometimes reported in nanoseconds."""
    if (operation == "_bulk"
            and es_took_ms > gateway_took_ms > 0
            and es_took_ms / gateway_took_ms > _ES_NANOSECOND_BUG_RATIO):
        return es_took_ms / 1_000_000
    return es_took_ms


def _compute_stress(
    operation: str, raw: RawFields, es_took_ms: float,
    hits: int, hits_lower_bound: bool, shards_total: int, docs_affected: int,
) -> tuple[dict[str, int], dict[str, int], float, int, float, dict[str, float], dict[str, float]]:
    """Compute clause counts, cost indicators, and stress score."""
    geo_vertex_count = 0
    if operation in _QUERY_OPS:
        clause_counts = count_clauses(raw.request_body)
        clause_counts["hits_lower_bound"] = int(hits_lower_bound)
        geo_vertex_count = parse_geo_vertex_count(raw.request_body)
        clause_counts["geo_vertex_count"] = geo_vertex_count
        cost_indicators, stress_multiplier = evaluate_cost_indicators(clause_counts)
    else:
        clause_counts = {k: 0 for k in _ALL_COUNT_FIELDS}
        cost_indicators, stress_multiplier = {}, 1.0

    ctx = StressContext(
        es_took_ms=es_took_ms,
        gateway_took_ms=raw.gateway_took_ms,
        hits=hits,
        shards_total=shards_total,
        docs_affected=docs_affected,
    )
    score, bonuses, components = calc_stress(
        operation, ctx, stress_multiplier, clause_counts,
    )
    return (clause_counts, cost_indicators, stress_multiplier,
            geo_vertex_count, score, bonuses, components)


def _build_request_section(
    raw: RawFields, operation: str, target: str, template: str,
    size: int, geo_vertex_count: int,
) -> dict[str, Any]:
    """Assemble the request section of the observability record."""
    request: dict[str, Any] = {
        "method": raw.method,
        "path": raw.path,
        "operation": operation,
        "target": target,
        "template": template,
        "body": json.dumps(raw.request_body, ensure_ascii=False) if raw.request_body
               else raw.request_body_raw,
        "size_bytes": raw.request_size_bytes,
    }
    if geo_vertex_count > 0:
        request["geo_vertex_count"] = geo_vertex_count
    if operation == "_search":
        request["size"] = size
    return request


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_record(raw: RawFields) -> dict[str, Any] | list[dict[str, Any]]:
    """Build observability record(s) from parsed raw fields.

    Returns a single dict for most operations, or a list of dicts
    for _msearch (one record per sub-query).
    """
    operation = parse_operation(raw.method, raw.path)

    if operation == "_msearch":
        return {"_msearch_records": _build_msearch_records(raw)}

    target = parse_target(raw.path)
    if operation == "_bulk":
        template, bulk_target = scrub_bulk_template(raw.request_body_raw)
        if target == "_all":
            target = bulk_target
    else:
        template = scrub_template(raw.request_body) if raw.request_body else ""

    hits, hits_lower_bound = parse_hits(raw.response_body)
    shards_total = (parse_shards_total_bulk(raw.response_body) if operation == "_bulk"
                    else parse_shards_total(raw.response_body))
    docs_affected = parse_docs_affected(operation, raw.response_body)
    es_took_ms = _fix_es_nanosecond_bug(
        operation, parse_es_took_ms(raw.response_body), raw.gateway_took_ms,
    )

    (clause_counts, cost_indicators, stress_multiplier,
     geo_vertex_count, score, bonuses, components) = _compute_stress(
        operation, raw, es_took_ms, hits, hits_lower_bound,
        shards_total, docs_affected,
    )

    return _assemble_record(
        raw, operation, target, template, es_took_ms,
        hits, shards_total, docs_affected, clause_counts,
        cost_indicators, stress_multiplier, geo_vertex_count,
        score, bonuses, components,
    )


def _assemble_record(
    raw: RawFields, operation: str, target: str, template: str,
    es_took_ms: float, hits: int, shards_total: int, docs_affected: int,
    clause_counts: dict[str, int], cost_indicators: dict[str, int],
    stress_multiplier: float, geo_vertex_count: int,
    score: float, bonuses: dict[str, float], components: dict[str, float],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a single observability record dict."""
    record: dict[str, Any] = {
        "@timestamp": _utc_timestamp(),
        "identity": {
            "username": parse_username(raw.headers),
            "applicative_provider": parse_applicative_provider(raw.headers),
            "user_agent": parse_user_agent(raw.headers),
            "client_host": raw.client_host,
            "labels": parse_labels(raw.headers),
        },
        "request": _build_request_section(
            raw, operation, target, template, parse_size(raw.request_body),
            geo_vertex_count,
        ),
        "response": {
            "status": raw.response_status,
            "es_took_ms": es_took_ms,
            "gateway_took_ms": raw.gateway_took_ms,
            "hits": hits,
            "shards_total": shards_total,
            "docs_affected": docs_affected,
            "size_bytes": raw.response_size_bytes,
        },
        "clause_counts": _output_clause_counts(clause_counts),
        "cost_indicators": cost_indicators,
        "stress": {
            "score": round(score, _STRESS_PRECISION),
            "base": round(sum(components.values()), _STRESS_PRECISION),
            "multiplier": stress_multiplier,
            "components": {k: round(v, _STRESS_PRECISION)
                           for k, v in components.items()},
            "bonuses": {k: round(v, _STRESS_PRECISION)
                        for k, v in bonuses.items()},
            "cost_indicator_count": len(cost_indicators),
            "cost_indicator_names": (list(cost_indicators.keys())
                                     or ["unflagged"]),
        },
    }
    if extra:
        record.update(extra)
    return record


def _build_msearch_records(raw: RawFields) -> list[dict[str, Any]]:
    """Fan out an _msearch request into one record per sub-query."""
    pairs = parse_msearch_pairs(raw.request_body_raw)
    responses = raw.response_body.get("responses", [])
    batch_size = len(pairs)
    request_id = uuid.uuid4().hex[:12]
    records: list[dict[str, Any]] = []

    for i, (header, body) in enumerate(pairs):
        sub_resp = responses[i] if i < len(responses) else {}

        hits, hits_lower_bound = parse_hits(sub_resp)
        shards_total = parse_shards_total(sub_resp)
        es_took_ms = parse_es_took_ms(sub_resp)

        clause_counts = count_clauses(body)
        clause_counts["hits_lower_bound"] = int(hits_lower_bound)
        geo_vertex_count = parse_geo_vertex_count(body)
        clause_counts["geo_vertex_count"] = geo_vertex_count
        cost_indicators, stress_multiplier = evaluate_cost_indicators(clause_counts)

        ctx = StressContext(
            es_took_ms=es_took_ms,
            gateway_took_ms=raw.gateway_took_ms,
            hits=hits,
            shards_total=shards_total,
            docs_affected=0,
        )
        score, bonuses, components = calc_stress(
            "_msearch", ctx, stress_multiplier, clause_counts,
        )

        idx = header.get("index", "")
        if isinstance(idx, list):
            target = ",".join(idx) if idx else "_all"
        else:
            target = idx or parse_target(raw.path)

        template = scrub_template(body) if body else ""
        body_str = json.dumps(body, ensure_ascii=False) if body else ""

        # Override per-query body in the request section
        sub_raw = RawFields(
            method=raw.method, path=raw.path, headers=raw.headers,
            request_body=body, request_body_raw=body_str,
            response_body=sub_resp, client_host=raw.client_host,
            response_status=raw.response_status,
            gateway_took_ms=raw.gateway_took_ms,
            request_size_bytes=raw.request_size_bytes,
            response_size_bytes=raw.response_size_bytes,
        )

        record = _assemble_record(
            sub_raw, "_msearch", target, template, es_took_ms,
            hits, shards_total, 0, clause_counts,
            cost_indicators, stress_multiplier, geo_vertex_count,
            score, bonuses, components,
            extra={"msearch": {
                "request_id": request_id,
                "batch_size": batch_size,
                "sub_query_index": i,
            }},
        )
        records.append(record)

    return records


def partial_error_record(payload: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return {
        "@timestamp": _utc_timestamp(),
        "error": str(exc),
        "path": payload.get("path", ""),
        "method": payload.get("method", ""),
    }
