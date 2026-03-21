"""
Builds the observability record from a raw Nginx payload.
No I/O — all functions are pure transformations.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from parser import (
    parse_applicative_provider,
    parse_docs_affected,
    parse_es_took_ms,
    parse_hits,
    parse_labels,
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
from stress import (
    _ALL_COUNT_FIELDS,
    StressContext,
    calc_stress,
    count_clauses,
    evaluate_cost_indicators,
)

def _utc_timestamp() -> str:
    now = datetime.now(timezone.utc)
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
    gateway_took_ms:      float
    request_size_bytes:   int
    response_size_bytes:  int


def _parse_json_field(raw: str) -> dict:
    """Safely parse a JSON string; return {} on failure."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
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

_QUERY_OPS = frozenset({"_search", "_update_by_query", "_delete_by_query", "_count", "_validate"})


def _output_clause_counts(counts: dict) -> dict:
    return {out: counts[internal] for internal, out in _CLAUSE_COUNT_OUTPUT_KEYS.items()}


def build_record(raw: RawFields) -> dict:
    operation = parse_operation(raw.method, raw.path)
    target    = parse_target(raw.path)
    if operation == "_bulk":
        template, bulk_target = scrub_bulk_template(raw.request_body_raw)
        if target == "_all":
            target = bulk_target
    else:
        template = scrub_template(raw.request_body) if raw.request_body else ""

    username             = parse_username(raw.headers)
    applicative_provider = parse_applicative_provider(raw.headers)
    user_agent           = parse_user_agent(raw.headers)
    labels               = parse_labels(raw.headers)

    hits                 = parse_hits(raw.response_body)
    if operation == "_bulk":
        shards_total     = parse_shards_total_bulk(raw.response_body)
    else:
        shards_total     = parse_shards_total(raw.response_body)
    docs_affected        = parse_docs_affected(operation, raw.response_body)
    size                 = parse_size(raw.request_body)
    es_took_ms           = parse_es_took_ms(raw.response_body)

    # ES 8.13–8.15 bulk bug: took sometimes reported in nanoseconds.
    # es_took can never exceed gateway_took, so if it's 1000x+ larger
    # the value is in the wrong unit and needs conversion.
    if (operation == "_bulk"
            and es_took_ms > raw.gateway_took_ms > 0
            and es_took_ms / raw.gateway_took_ms > 1000):
        es_took_ms /= 1_000_000

    if operation in _QUERY_OPS:
        clause_counts = count_clauses(raw.request_body)
        cost_indicators, stress_multiplier = evaluate_cost_indicators(clause_counts)
    else:
        clause_counts = {k: 0 for k in _ALL_COUNT_FIELDS}
        cost_indicators, stress_multiplier = {}, 1.0

    ctx = StressContext(
        es_took_ms=       es_took_ms,
        gateway_took_ms=  raw.gateway_took_ms,
        hits=             hits,
        size=             size,
        shards_total=     shards_total,
        docs_affected=    docs_affected,
    )
    score, bonuses = calc_stress(operation, ctx, stress_multiplier, clause_counts)

    request = {
        "method":     raw.method,
        "path":       raw.path,
        "operation":  operation,
        "target":     target,
        "template":   template,
        "body":       raw.request_body_raw,
        "size_bytes": raw.request_size_bytes,
    }
    if operation == "_search":
        request["size"] = size

    return {
        "@timestamp": _utc_timestamp(),
        "identity": {
            "username":             username,
            "applicative_provider": applicative_provider,
            "user_agent":           user_agent,
            "client_host":          raw.client_host,
            "labels":              labels,
        },
        "request":  request,
        "response": {
            "es_took_ms":    es_took_ms,
            "gateway_took_ms": raw.gateway_took_ms,
            "hits":          hits,
            "shards_total":  shards_total,
            "docs_affected": docs_affected,
            "size_bytes":    raw.response_size_bytes,
        },
        "clause_counts":    _output_clause_counts(clause_counts),
        "cost_indicators":  cost_indicators,
        "stress": {
            "score":                round(score, _STRESS_PRECISION),
            "multiplier":           stress_multiplier,
            "bonuses":              {k: round(v, _STRESS_PRECISION) for k, v in bonuses.items()},
            "cost_indicator_count": len(cost_indicators),
            "cost_indicator_names": list(cost_indicators.keys()),
        },
    }


def partial_error_record(payload: dict, exc: Exception) -> dict:
    return {
        "@timestamp": _utc_timestamp(),
        "error":     str(exc),
        "path":      payload.get("path", ""),
        "method":    payload.get("method", ""),
    }
