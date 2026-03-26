"""
FastAPI analyzer service.
POST /analyze  — accepts raw Nginx payload, returns observability record.
Never crashes: returns 200 with partial record on any parse error.
"""

import json

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from record_builder import build_record, extract_raw_fields, partial_error_record

app = FastAPI()

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
        payload = await request.json()
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return JSONResponse(status_code=200, content={"error": "unparseable payload"})

    try:
        record = build_record(extract_raw_fields(payload))
    except Exception as exc:
        record = partial_error_record(payload, exc)

    return JSONResponse(status_code=200, content=record)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
