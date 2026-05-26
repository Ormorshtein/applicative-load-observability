"""Fans out an _msearch request into one observability record per sub-query."""

import json
import uuid
from typing import Any

from ..parser import (
    parse_es_took_ms,
    parse_hits,
    parse_msearch_pairs,
    parse_shards_total,
    parse_target,
    scrub_template,
)
from ._assembly import OperationMeta, ResponseMetrics, assemble_record
from ._models import RawFields
from ._stress import compute_stress


def build_msearch_records(raw: RawFields) -> list[dict[str, Any]]:
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

        idx = header.get("index", "")
        if isinstance(idx, list):
            target = ",".join(idx) if idx else "_all"
        else:
            target = idx or parse_target(raw.path)

        body_str = json.dumps(body, ensure_ascii=False) if body else ""
        sub_raw = RawFields(
            method=raw.method, path=raw.path, headers=raw.headers,
            request_body=body, request_body_raw=body_str,
            response_body=sub_resp, client_host=raw.client_host,
            response_status=raw.response_status,
            gateway_took_ms=raw.gateway_took_ms,
            request_size_bytes=raw.request_size_bytes,
            response_size_bytes=raw.response_size_bytes,
            cluster_name=raw.cluster_name,
        )

        stress = compute_stress(
            "_msearch", sub_raw, es_took_ms, hits, hits_lower_bound,
            shards_total, docs_affected=0, bulk_doc_count=0,
        )

        record = assemble_record(
            sub_raw,
            OperationMeta(
                operation="_msearch",
                target=target,
                template=scrub_template(body) if body else "",
            ),
            ResponseMetrics(
                es_took_ms=es_took_ms,
                hits=hits,
                shards_total=shards_total,
                docs_affected=0,
                bulk_doc_count=0,
            ),
            stress,
            extra={
                "msearch_request_id": request_id,
                "msearch_batch_size": batch_size,
                "msearch_sub_query_index": i,
            },
        )
        records.append(record)

    return records
