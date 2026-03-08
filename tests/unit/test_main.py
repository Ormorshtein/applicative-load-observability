"""Unit tests for analyzer/main.py — FastAPI endpoint tests."""

import base64
import json
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /analyze — happy path
# ---------------------------------------------------------------------------

class TestAnalyzeHappyPath:
    def _payload(self, **overrides):
        base = {
            "method": "POST",
            "path": "/products/_search",
            "headers": {
                "authorization": f"Basic {base64.b64encode(b'alice:pass').decode()}",
                "x-opaque-id": "search-api",
                "user-agent": "elasticsearch-py/8.13.0",
            },
            "request_body": json.dumps({"query": {"match": {"title": "shoes"}}, "size": 10}),
            "response_body": json.dumps({
                "took": 42,
                "hits": {"total": {"value": 1500}, "hits": []},
                "_shards": {"total": 5},
            }),
            "client_host": "10.0.0.5",
            "gateway_took_ms": 67,
            "request_size_bytes": 284,
            "response_size_bytes": 1920,
        }
        base.update(overrides)
        return base

    def test_search_returns_200(self):
        resp = client.post("/analyze", json=self._payload())
        assert resp.status_code == 200

    def test_search_record_has_required_structure(self):
        rec = client.post("/analyze", json=self._payload()).json()
        # Top-level keys
        assert "timestamp" in rec
        assert "identity" in rec
        assert "request" in rec
        assert "response" in rec
        assert "clause_counts" in rec
        assert "cost_indicators" in rec
        assert "stress" in rec
        # Nested identity
        for f in ["username", "applicative_provider", "user_agent", "client_host"]:
            assert f in rec["identity"], f"Missing identity.{f}"
        # Nested request
        for f in ["method", "path", "operation", "target", "template", "body", "size_bytes"]:
            assert f in rec["request"], f"Missing request.{f}"
        # Nested response
        for f in ["es_took_ms", "gateway_took_ms", "hits", "shards_total", "docs_affected", "size_bytes"]:
            assert f in rec["response"], f"Missing response.{f}"
        # Nested stress
        for f in ["score", "multiplier", "cost_indicator_count", "cost_indicator_names"]:
            assert f in rec["stress"], f"Missing stress.{f}"

    def test_search_record_values(self):
        rec = client.post("/analyze", json=self._payload()).json()
        assert rec["request"]["operation"] == "_search"
        assert rec["request"]["target"] == "products"
        assert rec["identity"]["username"] == "alice"
        assert rec["identity"]["applicative_provider"] == "search-api"
        assert rec["response"]["es_took_ms"] == 42
        assert rec["response"]["hits"] == 1500
        assert rec["request"]["size"] == 10

    def test_bulk_operation(self):
        payload = self._payload(
            method="POST",
            path="/_bulk",
            request_body="",
            response_body=json.dumps({
                "took": 10,
                "items": [
                    {"index": {"_index": "idx1", "_shards": {"total": 2}}},
                    {"index": {"_index": "idx2", "_shards": {"total": 3}}},
                ],
            }),
        )
        rec = client.post("/analyze", json=payload).json()
        assert rec["request"]["operation"] == "_bulk"
        assert rec["response"]["docs_affected"] == 2

    def test_index_operation(self):
        payload = self._payload(
            method="PUT",
            path="/myindex/_doc/123",
            request_body=json.dumps({"title": "test"}),
            response_body=json.dumps({"took": 5, "_shards": {"total": 2}}),
        )
        rec = client.post("/analyze", json=payload).json()
        assert rec["request"]["operation"] == "index"
        assert "size" not in rec["request"]

    def test_delete_operation(self):
        payload = self._payload(
            method="DELETE",
            path="/myindex/_doc/123",
            request_body="",
            response_body=json.dumps({"took": 3, "_shards": {"total": 2}}),
        )
        rec = client.post("/analyze", json=payload).json()
        assert rec["request"]["operation"] == "delete"

    def test_script_query_flags(self):
        body = {
            "query": {"script_score": {
                "query": {"match_all": {}},
                "script": {"source": "doc['price'].value"},
            }},
            "size": 10,
        }
        payload = self._payload(request_body=json.dumps(body))
        rec = client.post("/analyze", json=payload).json()
        assert "has_script" in rec["cost_indicators"]
        assert rec["stress"]["multiplier"] >= 1.5


# ---------------------------------------------------------------------------
# POST /analyze — error handling
# ---------------------------------------------------------------------------

class TestAnalyzeErrorHandling:
    def test_unparseable_body_returns_200(self):
        resp = client.post("/analyze", content=b"not json",
                           headers={"content-type": "application/json"})
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_empty_payload_returns_200(self):
        resp = client.post("/analyze", json={})
        assert resp.status_code == 200
        # Should still produce a valid record with defaults
        rec = resp.json()
        assert "request" in rec or "error" in rec

    def test_missing_fields_best_effort(self):
        resp = client.post("/analyze", json={"method": "GET", "path": "/"})
        assert resp.status_code == 200
        rec = resp.json()
        assert rec.get("request", {}).get("operation") is not None or "error" in rec

    def test_malformed_request_body_still_works(self):
        payload = {
            "method": "POST",
            "path": "/idx/_search",
            "request_body": "not valid json",
            "response_body": json.dumps({"took": 1, "_shards": {"total": 1}}),
        }
        resp = client.post("/analyze", json=payload)
        assert resp.status_code == 200
        rec = resp.json()
        assert rec["request"]["operation"] == "_search"

    def test_malformed_response_body_still_works(self):
        payload = {
            "method": "POST",
            "path": "/idx/_search",
            "request_body": json.dumps({"query": {"match_all": {}}}),
            "response_body": "not valid json",
        }
        resp = client.post("/analyze", json=payload)
        assert resp.status_code == 200
        rec = resp.json()
        assert rec["response"]["es_took_ms"] == 0
        assert rec["response"]["hits"] == 0
