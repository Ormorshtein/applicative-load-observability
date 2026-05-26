"""Unit tests for analyzer/main.py — FastAPI endpoint tests."""

import base64
import gzip
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from analyzer.main import app

client = TestClient(app)


def _post_payload_with_binary_field(payload: dict) -> dict:
    """Send a payload whose string fields may contain latin-1 codepoints.

    Mirrors what reaches the analyzer when the gateway forwards a gzipped
    request body through the Logstash pre-escape pipeline.
    """
    body = json.dumps(payload).encode("utf-8")
    resp = client.post("/analyze", content=body,
                       headers={"content-type": "application/json"})
    return resp.json()


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
        for col in (
            "timestamp", "cluster_name",
            "identity_username", "identity_applicative_provider",
            "identity_user_agent", "identity_client_host",
            "request_method", "request_path", "request_operation",
            "request_target", "request_template", "request_body",
            "request_size_bytes",
            "response_es_took_ms", "response_gateway_took_ms",
            "response_hits", "response_shards_total",
            "response_docs_affected", "response_size_bytes",
            "stress_score", "stress_multiplier",
            "stress_cost_indicator_count", "stress_cost_indicator_names",
            "stress_bonuses",
        ):
            assert col in rec, f"Missing column {col}"

    def test_search_record_values(self):
        rec = client.post("/analyze", json=self._payload()).json()
        assert rec["request_operation"] == "_search"
        assert rec["request_target"] == "products"
        assert rec["identity_username"] == "alice"
        assert rec["identity_applicative_provider"] == "search-api"
        assert rec["response_es_took_ms"] == 42
        assert rec["response_hits"] == 1500
        assert rec["request_size"] == 10

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
        assert rec["request_operation"] == "_bulk"
        assert rec["response_docs_affected"] == 2

    def test_index_operation(self):
        payload = self._payload(
            method="PUT",
            path="/myindex/_doc/123",
            request_body=json.dumps({"title": "test"}),
            response_body=json.dumps({"took": 5, "_shards": {"total": 2}}),
        )
        rec = client.post("/analyze", json=payload).json()
        assert rec["request_operation"] == "index"
        # Flat schema always emits the column; non-search defaults to 0.
        assert rec["request_size"] == 0

    def test_delete_operation(self):
        payload = self._payload(
            method="DELETE",
            path="/myindex/_doc/123",
            request_body="",
            response_body=json.dumps({"took": 3, "_shards": {"total": 2}}),
        )
        rec = client.post("/analyze", json=payload).json()
        assert rec["request_operation"] == "delete"

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
        assert rec["cost_indicators_has_script"] >= 1
        assert rec["stress_multiplier"] >= 1.5


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
        rec = resp.json()
        assert rec["request_method"] == "GET"
        assert rec["request_path"] == "/"
        assert rec["request_operation"] == "get"

    def test_missing_fields_best_effort(self):
        resp = client.post("/analyze", json={"method": "GET", "path": "/"})
        assert resp.status_code == 200
        rec = resp.json()
        assert rec["request_operation"] == "get"
        assert rec["response_es_took_ms"] == 0
        assert rec["identity_username"] == ""

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
        assert rec["request_operation"] == "_search"

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
        assert rec["response_es_took_ms"] == 0
        assert rec["response_hits"] == 0

    def test_build_record_exception_returns_partial_error(self):
        """Payload that parses as JSON but causes build_record to throw."""
        payload = {
            "method": "POST",
            "path": "/idx/_search",
            "response_status": "not_a_number",
        }
        resp = client.post("/analyze", json=payload)
        assert resp.status_code == 200
        rec = resp.json()
        assert "error" in rec
        assert rec["request_path"] == "/idx/_search"
        assert rec["request_method"] == "POST"


# ---------------------------------------------------------------------------
# POST /analyze/bulk
# ---------------------------------------------------------------------------

def _search_payload(**overrides):
    base = {
        "method": "POST",
        "path": "/products/_search",
        "headers": {"x-app-name": "test-app"},
        "request_body": json.dumps({"query": {"match_all": {}}, "size": 10}),
        "response_body": json.dumps({
            "took": 5,
            "hits": {"total": {"value": 100}, "hits": []},
            "_shards": {"total": 3},
        }),
        "client_host": "10.0.0.1",
        "response_status": 200,
        "upstream_response_time": "0.005",
        "content_length": "50",
        "response_size_bytes": 500,
    }
    base.update(overrides)
    return base


def _bulk_payload():
    return {
        "method": "POST",
        "path": "/_bulk",
        "headers": {"x-app-name": "ingest"},
        "request_body": '{"index":{"_index":"x"}}\n{"title":"t"}\n',
        "response_body": json.dumps({
            "took": 10, "errors": False,
            "items": [{"index": {"_index": "x", "_id": "1", "status": 201,
                                 "_shards": {"total": 2}}}],
        }),
        "response_status": 200,
        "upstream_response_time": "0.010",
        "content_length": "80",
        "response_size_bytes": 200,
    }


def _index_payload():
    return {
        "method": "PUT",
        "path": "/myindex/_doc/abc",
        "headers": {"x-app-name": "writer"},
        "request_body": json.dumps({"title": "hello"}),
        "response_body": json.dumps({
            "result": "created", "_shards": {"total": 2},
        }),
        "response_status": 201,
        "upstream_response_time": "0.003",
        "content_length": "20",
        "response_size_bytes": 100,
    }


class TestAnalyzeBulk:
    def test_returns_array_matching_input_length(self):
        payloads = [_search_payload(), _bulk_payload(), _index_payload()]
        resp = client.post("/analyze/bulk", json=payloads)
        assert resp.status_code == 200
        results = resp.json()
        assert isinstance(results, list)
        assert len(results) == 3

    def test_each_item_has_correct_structure(self):
        payloads = [_search_payload(), _search_payload()]
        results = client.post("/analyze/bulk", json=payloads).json()
        for rec in results:
            for col in ("timestamp", "identity_username", "request_operation",
                        "response_es_took_ms", "stress_score"):
                assert col in rec

    def test_item_matches_single_endpoint(self):
        payload = _search_payload()
        single = client.post("/analyze", json=payload).json()
        bulk = client.post("/analyze/bulk", json=[payload]).json()
        assert len(bulk) == 1
        # Compare everything except timestamp (generated independently)
        for key in single:
            if key == "timestamp":
                continue
            assert bulk[0][key] == single[key], f"Mismatch in {key}"

    def test_mixed_operations(self):
        payloads = [_search_payload(), _bulk_payload(), _index_payload()]
        results = client.post("/analyze/bulk", json=payloads).json()
        assert results[0]["request_operation"] == "_search"
        assert results[1]["request_operation"] == "_bulk"
        assert results[2]["request_operation"] == "index"

    def test_per_item_error_isolation(self):
        """One bad item doesn't poison the batch."""
        payloads = [
            _search_payload(),
            {"method": "POST", "path": "/x/_search",
             "response_status": "not_a_number"},  # will throw
            _search_payload(),
        ]
        results = client.post("/analyze/bulk", json=payloads).json()
        assert len(results) == 3
        assert "error" not in results[0]
        assert "error" in results[1]
        assert "error" not in results[2]

    def test_empty_array(self):
        resp = client.post("/analyze/bulk", json=[])
        assert resp.status_code == 200
        assert resp.json() == []

    def test_not_an_array(self):
        resp = client.post("/analyze/bulk", json={"method": "GET"})
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_non_object_item(self):
        payloads = [_search_payload(), "not_a_dict", _search_payload()]
        results = client.post("/analyze/bulk", json=payloads).json()
        assert len(results) == 3
        assert "error" not in results[0]
        assert "error" in results[1]
        assert "error" not in results[2]

    def test_unparseable_body(self):
        resp = client.post("/analyze/bulk", content=b"not json",
                           headers={"content-type": "application/json"})
        assert resp.status_code == 200
        assert "error" in resp.json()


# ---------------------------------------------------------------------------
# POST /analyze — gzip-compressed bodies
# ---------------------------------------------------------------------------

class TestAnalyzeCompressedBodies:
    def test_gzip_request_body_decompressed(self):
        original = json.dumps({"query": {"match": {"title": "shoes"}}, "size": 25})
        compressed = gzip.compress(original.encode("utf-8"))
        payload = {
            "method": "POST",
            "path": "/products/_search",
            "headers": {"content-encoding": "gzip"},
            "request_body": compressed.decode("latin-1"),
            "response_body": json.dumps({
                "took": 7,
                "hits": {"total": {"value": 3}, "hits": []},
                "_shards": {"total": 2},
            }),
            "client_host": "10.0.0.1",
            "response_status": 200,
        }
        rec = _post_payload_with_binary_field(payload)
        assert rec["request_operation"] == "_search"
        assert rec["request_size"] == 25
        # Template should reflect the decompressed query, not garbage.
        assert "match" in rec["request_template"]

    def test_gzip_bulk_request_body_decompressed(self):
        bulk = (
            '{"index":{"_index":"products"}}\n{"title":"alpha"}\n'
            '{"index":{"_index":"products"}}\n{"title":"beta"}\n'
        )
        compressed = gzip.compress(bulk.encode("utf-8"))
        payload = {
            "method": "POST",
            "path": "/_bulk",
            "headers": {"content-encoding": "gzip"},
            "request_body": compressed.decode("latin-1"),
            "response_body": json.dumps({
                "took": 4, "errors": False,
                "items": [
                    {"index": {"_index": "products", "_id": "1", "status": 201,
                               "_shards": {"total": 2}}},
                    {"index": {"_index": "products", "_id": "2", "status": 201,
                               "_shards": {"total": 2}}},
                ],
            }),
            "response_status": 200,
        }
        rec = _post_payload_with_binary_field(payload)
        assert rec["request_operation"] == "_bulk"
        assert rec["request_target"] == "products"
        assert rec["response_docs_affected"] == 2

    def test_gzip_response_body_decompressed(self):
        response_payload = json.dumps({
            "took": 11,
            "hits": {"total": {"value": 99}, "hits": []},
            "_shards": {"total": 4},
        })
        compressed = gzip.compress(response_payload.encode("utf-8"))
        payload = {
            "method": "POST",
            "path": "/products/_search",
            "headers": {},
            "request_body": json.dumps({"query": {"match_all": {}}, "size": 10}),
            "response_body": compressed.decode("latin-1"),
            "response_status": 200,
        }
        rec = _post_payload_with_binary_field(payload)
        assert rec["response_es_took_ms"] == 11
        assert rec["response_hits"] == 99
        assert rec["response_shards_total"] == 4
