"""Record assembly — builds the ES document from parsed components. No I/O."""

import json
from datetime import UTC, datetime
from typing import Any

from ..parser import (
    parse_applicative_provider,
    parse_labels,
    parse_size,
    parse_user_agent,
    parse_username,
)
from ._models import OperationMeta, RawFields, ResponseMetrics, StressResult

_TRUNCATION_SUFFIX = "…[TRUNCATED]"
_TRUNCATION_SUFFIX_BYTES = len(_TRUNCATION_SUFFIX.encode("utf-8"))
_STRESS_PRECISION = 4

_CLAUSE_COUNT_OUTPUT_KEYS: dict[str, str] = {
    "bool_clause_count":     "bool",
    "bool_must_count":       "bool_must",
    "bool_should_count":     "bool_should",
    "bool_filter_count":     "bool_filter",
    "bool_must_not_count":   "bool_must_not",
    "terms_values_count":    "terms_values",
    "knn_clause_count":      "knn",
    "fuzzy_clause_count":    "fuzzy",
    "geo_bbox_count":        "geo_bbox",
    "geo_distance_count":    "geo_distance",
    "geo_shape_count":       "geo_shape",
    "agg_clause_count":      "agg",
    "wildcard_clause_count": "wildcard",
    "nested_clause_count":   "nested",
    "runtime_mapping_count": "runtime_mapping",
    "script_clause_count":   "script",
}


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def truncate_body(body: str) -> tuple[str, bool]:
    # Lazy import avoids circular dependency: record_builder → _assembly → record_builder.
    # At call time the module is fully loaded; monkeypatch on record_builder._MAX_BODY_BYTES works.
    from .. import record_builder as _rb
    max_bytes: int = _rb._MAX_BODY_BYTES
    if max_bytes <= 0:
        return body, False
    encoded = body.encode("utf-8")
    if len(encoded) <= max_bytes:
        return body, False
    head_bytes = max(0, max_bytes - _TRUNCATION_SUFFIX_BYTES)
    truncated = encoded[:head_bytes].decode("utf-8", errors="ignore")
    return truncated + _TRUNCATION_SUFFIX, True


def _output_clause_counts(counts: dict[str, int]) -> dict[str, int]:
    return {out: counts[internal] for internal, out in _CLAUSE_COUNT_OUTPUT_KEYS.items()}


def resolve_bulk_took(operation: str, es_took_ms: float, gateway_took_ms: float) -> float:
    """Use the gateway-observed elapsed time as the bulk ``took``.

    ES ``_bulk took`` has been wrong on every version since 8.13:
        * 8.13-8.15 reported it in nanoseconds (#111854 / #111863).
        * 8.16+ reads it from a 200ms-cached clock so values are quantized
          to {0, 200, 400, ...} (see BULK_TOOK_ISSUE_DRAFT.md).

    Gateway round-trip time is the ES processing time plus a tiny network
    hop, so it's a strictly better signal for ``_bulk``. Non-bulk
    operations keep using the upstream ``took`` since their query path is
    not affected by these bugs.
    """
    if operation == "_bulk" and gateway_took_ms > 0:
        return gateway_took_ms
    return es_took_ms


def build_request_section(
    raw: RawFields,
    op_meta: OperationMeta,
    geo_vertex_count: int,
    bulk_doc_count: int = 0,
) -> dict[str, Any]:
    body_text = (json.dumps(raw.request_body, ensure_ascii=False)
                 if raw.request_body else raw.request_body_raw)
    body, body_truncated = truncate_body(body_text)
    request: dict[str, Any] = {
        "method": raw.method,
        "path": raw.path,
        "operation": op_meta.operation,
        "target": op_meta.target,
        "template": op_meta.template,
        "body": body,
        "size_bytes": raw.request_size_bytes,
    }
    if body_truncated:
        request["body_truncated"] = True
    if geo_vertex_count > 0:
        request["geo_vertex_count"] = geo_vertex_count
    if op_meta.operation == "_search":
        request["size"] = parse_size(raw.request_body)
    if op_meta.operation == "_bulk":
        request["bulk_doc_count"] = bulk_doc_count
    return request


def assemble_record(
    raw: RawFields,
    op_meta: OperationMeta,
    metrics: ResponseMetrics,
    stress: StressResult,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "@timestamp": utc_timestamp(),
        "cluster_name": raw.cluster_name,
        "identity": {
            "username": parse_username(raw.headers),
            "applicative_provider": parse_applicative_provider(raw.headers),
            "user_agent": parse_user_agent(raw.headers),
            "client_host": raw.client_host,
            "labels": parse_labels(raw.headers),
        },
        "request": build_request_section(
            raw, op_meta, stress.geo_vertex_count, metrics.bulk_doc_count,
        ),
        "response": {
            "status": raw.response_status,
            "es_took_ms": metrics.es_took_ms,
            "gateway_took_ms": raw.gateway_took_ms,
            "hits": metrics.hits,
            "shards_total": metrics.shards_total,
            "docs_affected": metrics.docs_affected,
            "size_bytes": raw.response_size_bytes,
        },
        "clause_counts": _output_clause_counts(stress.clause_counts),
        "cost_indicators": stress.cost_indicators,
        "stress": {
            "score": round(stress.score, _STRESS_PRECISION),
            "base": round(sum(stress.components.values()), _STRESS_PRECISION),
            "multiplier": stress.stress_multiplier,
            "components": {k: round(v, _STRESS_PRECISION)
                           for k, v in stress.components.items()},
            "bonuses": {k: round(v, _STRESS_PRECISION)
                        for k, v in stress.bonuses.items()},
            "cost_indicator_count": len(stress.cost_indicators),
            "cost_indicator_names": (list(stress.cost_indicators.keys())
                                     or ["unflagged"]),
            "cost_indicator_multipliers": stress.indicator_multipliers,
        },
    }
    if extra:
        record.update(extra)
    return record
