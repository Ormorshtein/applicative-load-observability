"""Builds the observability record from a raw Nginx payload. No I/O."""

import json
import logging
from typing import Any

from .._decompression import decompress_body
from ..parser import (
    parse_bulk_doc_count,
    parse_docs_affected,
    parse_es_took_ms,
    parse_hits,
    parse_operation,
    parse_shards_total,
    parse_shards_total_bulk,
    parse_target,
    scrub_bulk_template,
    scrub_template,
)
from ._assembly import OperationMeta, ResponseMetrics, assemble_record, resolve_bulk_took, truncate_body
from ._assembly import utc_timestamp as _utc_timestamp
from ._models import RawFields
from ._msearch import build_msearch_records
from ._stress import compute_stress

logger = logging.getLogger(__name__)


def _parse_json_field(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError as exc:
        logger.debug("body field not JSON: %s", exc)
        return {}


def _parse_upstream_response_time(raw: str) -> float:
    if not raw:
        return 0.0
    try:
        return float(raw) * 1000
    except (ValueError, TypeError):
        logger.debug("bad upstream_response_time: %r", raw)
        return 0.0


def _parse_content_length(raw: str) -> int:
    if not raw:
        return 0
    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.debug("bad content_length: %r", raw)
        return 0


def extract_raw_fields(payload: dict[str, Any]) -> RawFields:
    raw_body = decompress_body(payload.get("request_body", ""))
    raw_response = decompress_body(payload.get("response_body", ""))
    return RawFields(
        method=              payload.get("method", "GET"),
        path=                payload.get("path", "/"),
        headers=             payload.get("headers", {}),
        request_body=        _parse_json_field(raw_body),
        request_body_raw=    raw_body,
        response_body=       _parse_json_field(raw_response),
        client_host=         payload.get("client_host", ""),
        response_status=     int(payload.get("response_status", 0)),
        gateway_took_ms=     _parse_upstream_response_time(
                                 payload.get("upstream_response_time", "")),
        request_size_bytes=  _parse_content_length(
                                 payload.get("content_length", "")),
        response_size_bytes= int(payload.get("response_size_bytes", 0)),
        cluster_name=        payload.get("cluster_name", "default"),
    )


def build_record(raw: RawFields) -> dict[str, Any]:
    operation = parse_operation(raw.method, raw.path)

    if operation == "_msearch":
        return {"_msearch_records": build_msearch_records(raw)}

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
    bulk_doc_count = parse_bulk_doc_count(raw.request_body_raw) if operation == "_bulk" else 0
    es_took_ms = resolve_bulk_took(
        operation, parse_es_took_ms(raw.response_body), raw.gateway_took_ms,
    )

    stress = compute_stress(
        operation, raw, es_took_ms, hits, hits_lower_bound,
        shards_total, docs_affected, bulk_doc_count,
    )

    return assemble_record(
        raw,
        OperationMeta(operation=operation, target=target, template=template),
        ResponseMetrics(
            es_took_ms=es_took_ms,
            hits=hits,
            shards_total=shards_total,
            docs_affected=docs_affected,
            bulk_doc_count=bulk_doc_count,
        ),
        stress,
    )


def partial_error_record(payload: dict[str, Any], exc: Exception) -> dict[str, Any]:
    raw_text, _ = truncate_body(json.dumps(payload, ensure_ascii=False))
    return {
        "timestamp": _utc_timestamp(),
        "cluster_name": payload.get("cluster_name", "default"),
        "error": str(exc),
        "request_path": payload.get("path", ""),
        "request_method": payload.get("method", ""),
        "raw": raw_text,
    }
