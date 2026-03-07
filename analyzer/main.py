"""
FastAPI analyzer service.
POST /analyze  — accepts raw Nginx payload, returns observability record.
Never crashes: returns 200 with partial record on any parse error.
"""

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from record_builder import build_record, extract_raw_fields, partial_error_record

app = FastAPI()


@app.post("/analyze")
async def analyze(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=200, content={"error": "unparseable payload"})

    try:
        record = build_record(extract_raw_fields(payload))
    except Exception as exc:
        record = partial_error_record(payload, exc)

    return JSONResponse(status_code=200, content=record)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
