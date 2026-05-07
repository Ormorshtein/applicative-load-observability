"""
FastAPI analyzer service.
POST /analyze  — accepts raw Nginx payload, returns observability record.
Never crashes: returns 200 with partial record on any parse error.
"""

import json
import logging
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from .record_builder import build_record, extract_raw_fields, partial_error_record

logger = logging.getLogger(__name__)

app = FastAPI()


# Logstash pre-escapes high bytes (0x80-0xFF) as \u00XX before JSON
# parsing, so the payload arriving here is always valid UTF-8.  Binary
# body fields (e.g. gzip-compressed request_body) survive as latin-1
# codepoints (U+0000-U+00FF) which the analyzer recovers downstream.
async def _read_payload(request: Request) -> Any:
    raw = await request.body()
    return json.loads(raw.decode("utf-8"))

Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
    excluded_handlers=["/health", "/metrics"],
).instrument(app).expose(app)


@app.post("/analyze")
async def analyze(request: Request) -> JSONResponse:
    try:
        payload = await _read_payload(request)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        logger.warning("unparseable payload: %s", exc)
        return JSONResponse(status_code=200, content={"error": "unparseable payload"})

    logger.debug("analyze: method=%s path=%s", payload.get("method"), payload.get("path"))

    try:
        record = build_record(extract_raw_fields(payload))
    except Exception as exc:
        logger.error(
            "record build failed for %s %s: %s",
            payload.get("method"), payload.get("path"), exc,
            exc_info=True,
        )
        record = partial_error_record(payload, exc)

    return JSONResponse(status_code=200, content=record)


@app.post("/analyze/bulk")
async def analyze_bulk(request: Request) -> JSONResponse:
    """Batch-analyze multiple payloads in a single call.

    Accepts a JSON array of payloads (same format as /analyze).
    Returns a JSON array of results with 1:1 positional correspondence.
    Individual failures produce partial_error_record for that slot;
    the rest of the batch is unaffected.
    """
    try:
        payloads = await _read_payload(request)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        logger.warning("bulk: unparseable payload: %s", exc)
        return JSONResponse(status_code=200, content={"error": "unparseable payload"})

    if not isinstance(payloads, list):
        logger.warning("bulk: expected JSON array, got %s", type(payloads).__name__)
        return JSONResponse(status_code=200, content={"error": "expected JSON array"})

    logger.info("bulk: processing %d items", len(payloads))

    results = []
    errors = 0
    for i, payload in enumerate(payloads):
        if not isinstance(payload, dict):
            logger.debug("bulk: item %d is not an object (type=%s)", i, type(payload).__name__)
            results.append({"error": "non-object item"})
            errors += 1
            continue
        try:
            results.append(build_record(extract_raw_fields(payload)))
        except Exception as exc:
            logger.error(
                "bulk: item %d (%s %s) failed: %s",
                i, payload.get("method"), payload.get("path"), exc,
                exc_info=True,
            )
            results.append(partial_error_record(payload, exc))
            errors += 1

    if errors:
        logger.warning("bulk: %d/%d items produced errors", errors, len(payloads))

    return JSONResponse(status_code=200, content=results)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)