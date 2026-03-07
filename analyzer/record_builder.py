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
    parse_has_runtime_mappings,
    parse_has_script,
    parse_hits,
    parse_operation,
    parse_shards_total,
    parse_shards_total_bulk,
    parse_size,
    parse_target,
    parse_user_agent,
    parse_username,
    scrub_template,
)
from stress import StressContext, calc_query_complexity, calc_stress

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.000Z"
_STRESS_PRECISION = 4


@dataclass
class RawFields:
    method:               str
    path:                 str
    headers:              dict
    request_body:         dict
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


def extract_raw_fields(payload: dict) -> RawFields:
    return RawFields(
        method=              payload.get("method", "GET"),
        path=                payload.get("path", "/"),
        headers=             payload.get("headers", {}),
        request_body=        _parse_json_field(payload.get("request_body", "")),
        response_body=       _parse_json_field(payload.get("response_body", "")),
        client_host=         payload.get("client_host", ""),
        gateway_took_ms=     float(payload.get("gateway_took_ms", 0)),
        request_size_bytes=  int(payload.get("request_size_bytes", 0)),
        response_size_bytes= int(payload.get("response_size_bytes", 0)),
    )


def build_record(raw: RawFields) -> dict:
    operation = parse_operation(raw.method, raw.path)
    target    = parse_target(raw.path)
    template  = scrub_template(raw.request_body) if raw.request_body else ""

    username             = parse_username(raw.headers)
    applicative_provider = parse_applicative_provider(raw.headers)
    user_agent           = parse_user_agent(raw.headers)

    hits                 = parse_hits(raw.response_body)
    if operation == "_bulk":
        shards_total     = parse_shards_total_bulk(raw.response_body)
    else:
        shards_total     = parse_shards_total(raw.response_body)
    docs_affected        = parse_docs_affected(operation, raw.response_body)
    size                 = parse_size(raw.request_body)
    has_script           = parse_has_script(raw.request_body)
    has_runtime_mappings = parse_has_runtime_mappings(raw.request_body)
    es_took_ms           = parse_es_took_ms(raw.response_body)

    clause_counts = calc_query_complexity(raw.request_body)

    ctx = StressContext(
        es_took_ms=       es_took_ms or raw.gateway_took_ms,
        hits=             hits,
        size=             size,
        shards_total=     shards_total,
        docs_affected=    docs_affected,
        query_complexity= clause_counts["query_complexity"],
    )

    return {
        "timestamp":            datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT),
        "operation":            operation,
        "method":               raw.method,
        "path":                 raw.path,
        "request_body":         raw.request_body,
        "target":               target,
        "template":             template,
        "username":             username,
        "client_host":          raw.client_host,
        "applicative_provider": applicative_provider,
        "user_agent":           user_agent,
        "gateway_took_ms":      raw.gateway_took_ms,
        "es_took_ms":           es_took_ms,
        "hits":                 hits,
        "shards_total":         shards_total,
        **clause_counts,
        **({"size": size} if operation == "_search" else {}),
        "docs_affected":        docs_affected,
        "has_script":           has_script,
        "has_runtime_mappings": has_runtime_mappings,
        "request_size_bytes":   raw.request_size_bytes,
        "response_size_bytes":  raw.response_size_bytes,
        "stress_score":         round(calc_stress(operation, ctx), _STRESS_PRECISION),
    }


def partial_error_record(payload: dict, exc: Exception) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT),
        "error":     str(exc),
        "path":      payload.get("path", ""),
        "method":    payload.get("method", ""),
    }
