"""
FastAPI analyzer service.
POST /analyze  — accepts raw Nginx payload, returns observability record.
Never crashes: returns 200 with partial record on any parse error.
"""

import json
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from parser import (
    parse_applicative_provider,
    parse_client_host,
    parse_docs_affected,
    parse_has_runtime_mappings,
    parse_has_script,
    parse_hits,
    parse_operation_kind,
    parse_operation_type,
    parse_shards_total,
    parse_size,
    parse_target,
    parse_user_agent,
    parse_username,
    scrub_template,
)
from stress import calc_query_complexity, calc_stress

app = FastAPI()


def _parse_json_field(raw: str) -> dict:
    """Safely parse a JSON string; return {} on failure."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


@app.post("/analyze")
async def analyze(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=200, content={"error": "unparseable payload"})

    try:
        method = payload.get("method", "GET")
        path = payload.get("path", "/")
        headers = payload.get("headers", {})
        request_body = _parse_json_field(payload.get("request_body", ""))
        response_body = _parse_json_field(payload.get("response_body", ""))
        response_status = payload.get("response_status", 0)
        took_ms = float(payload.get("response_took_ms", 0))
        request_size_bytes = int(payload.get("request_size_bytes", 0))
        response_size_bytes = int(payload.get("response_size_bytes", 0))

        operation_kind = parse_operation_kind(method, path)
        operation_type = parse_operation_type(method, path, request_body)
        target = parse_target(path)
        template = scrub_template(request_body) if request_body else ""

        username = parse_username(headers)
        client_host = parse_client_host(payload)
        applicative_provider = parse_applicative_provider(headers)
        user_agent = parse_user_agent(headers)

        hits = parse_hits(response_body)
        shards_total = parse_shards_total(response_body)
        docs_affected = parse_docs_affected(path, response_body)
        size = parse_size(request_body)
        has_script = parse_has_script(request_body)
        has_runtime_mappings = parse_has_runtime_mappings(request_body)

        complexity_info = calc_query_complexity(request_body)
        query_complexity = complexity_info["query_complexity"]

        stress_score = calc_stress(
            operation_kind=operation_kind,
            operation_type=operation_type,
            took_ms=took_ms,
            hits=hits,
            size=size,
            shards_total=shards_total,
            docs_affected=docs_affected,
            query_complexity=query_complexity,
            has_script=has_script,
            has_runtime_mappings=has_runtime_mappings,
        )

        record = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "operation_kind": operation_kind,
            "operation_type": operation_type,
            "target": target,
            "template": template,
            "username": username,
            "client_host": client_host,
            "applicative_provider": applicative_provider,
            "user_agent": user_agent,
            "response_took_ms": took_ms,
            "hits": hits,
            "shards_total": shards_total,
            "size": size,
            "docs_affected": docs_affected,
            "has_script": has_script,
            "has_runtime_mappings": has_runtime_mappings,
            "request_size_bytes": request_size_bytes,
            "response_size_bytes": response_size_bytes,
            "stress_score": round(stress_score, 4),
        }

    except Exception as exc:
        # Best-effort partial record — never crash
        record = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "error": str(exc),
            "path": payload.get("path", ""),
            "method": payload.get("method", ""),
        }

    return JSONResponse(status_code=200, content=record)


@app.get("/health")
async def health():
    return {"status": "ok"}
