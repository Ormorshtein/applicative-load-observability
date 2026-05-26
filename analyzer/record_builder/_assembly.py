"""Record assembly — builds flat ClickHouse-shaped records from parsed components. No I/O."""

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

_ALL_STRESS_COMPONENT_KEYS: tuple[str, ...] = (
    "took", "shards", "hits", "docs_affected", "bulk_doc_count", "bonus",
)

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
    now = datetime.now(UTC)
    # CH DateTime64 JSONEachRow format: "YYYY-MM-DD HH:MM:SS.mmm" (no T, no Z)
    return now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"


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


def assemble_record(
    raw: RawFields,
    op_meta: OperationMeta,
    metrics: ResponseMetrics,
    stress: StressResult,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body_text = (json.dumps(raw.request_body, ensure_ascii=False)
                 if raw.request_body else raw.request_body_raw)
    body, body_truncated = truncate_body(body_text)
    clause_counts = _output_clause_counts(stress.clause_counts)

    record: dict[str, Any] = {
        "timestamp": utc_timestamp(),
        "cluster_name": raw.cluster_name,

        # identity
        "identity_username": parse_username(raw.headers),
        "identity_applicative_provider": parse_applicative_provider(raw.headers),
        "identity_user_agent": parse_user_agent(raw.headers),
        "identity_client_host": raw.client_host,
        "identity_labels": parse_labels(raw.headers),

        # request
        "request_method": raw.method,
        "request_path": raw.path,
        "request_operation": op_meta.operation,
        "request_target": op_meta.target,
        "request_template": op_meta.template,
        "request_body": body,
        "request_body_truncated": int(body_truncated),
        "request_size_bytes": raw.request_size_bytes,
        "request_size": parse_size(raw.request_body) if op_meta.operation == "_search" else 0,
        "request_geo_vertex_count": stress.geo_vertex_count,
        "request_bulk_doc_count": metrics.bulk_doc_count,

        # response
        "response_status": raw.response_status,
        "response_es_took_ms": metrics.es_took_ms,
        "response_gateway_took_ms": raw.gateway_took_ms,
        "response_hits": metrics.hits,
        "response_shards_total": metrics.shards_total,
        "response_docs_affected": metrics.docs_affected,
        "response_size_bytes": raw.response_size_bytes,

        # stress aggregates
        "stress_score": round(stress.score, _STRESS_PRECISION),
        "stress_base": round(sum(stress.components.values()), _STRESS_PRECISION),
        "stress_multiplier": stress.stress_multiplier,
        "stress_cost_indicator_count": len(stress.cost_indicators),
        "stress_cost_indicator_names": list(stress.cost_indicators.keys()) or ["unflagged"],
        "stress_cost_indicator_multipliers": stress.indicator_multipliers,
        "stress_bonuses": {k: round(v, _STRESS_PRECISION) for k, v in stress.bonuses.items()},
    }

    # flat clause_counts_* columns
    for suffix, value in clause_counts.items():
        record[f"clause_counts_{suffix}"] = value

    # flat cost_indicators_* columns (0/1 per indicator)
    from analyzer.stress._cost_indicators import _COST_INDICATORS
    flagged = set(stress.cost_indicators)
    for indicator in _COST_INDICATORS:
        record[f"cost_indicators_{indicator.name}"] = int(indicator.name in flagged)

    # flat stress_components_* columns — always emit all known keys (0.0 when absent)
    for component in _ALL_STRESS_COMPONENT_KEYS:
        record[f"stress_components_{component}"] = round(
            stress.components.get(component, 0.0), _STRESS_PRECISION
        )

    if extra:
        record.update(extra)
    return record
