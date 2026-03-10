"""Unit tests for analyzer/record_builder.py — record building and raw field extraction."""

import base64
import json
import pytest
from unittest.mock import patch
from datetime import datetime, timezone

from record_builder import (
    extract_raw_fields,
    build_record,
    partial_error_record,
    RawFields,
    _parse_json_field,
)


# ---------------------------------------------------------------------------
# _parse_json_field
# ---------------------------------------------------------------------------

class TestParseJsonField:
    def test_valid_json(self):
        assert _parse_json_field('{"a": 1}') == {"a": 1}

    def test_empty_string(self):
        assert _parse_json_field("") == {}

    def test_invalid_json(self):
        assert _parse_json_field("not json") == {}

    def test_none_like_empty(self):
        assert _parse_json_field("") == {}


# ---------------------------------------------------------------------------
# extract_raw_fields
# ---------------------------------------------------------------------------

class TestExtractRawFields:
    def test_full_payload(self):
        payload = {
            "method": "POST",
            "path": "/products/_search",
            "headers": {"user-agent": "curl/7"},
            "request_body": '{"query":{"match_all":{}}}',
            "response_body": '{"took":42,"hits":{"total":{"value":10},"hits":[]}}',
            "client_host": "10.0.0.5",
            "gateway_took_ms": 67,
            "request_size_bytes": 284,
            "response_size_bytes": 1920,
        }
        raw = extract_raw_fields(payload)
        assert raw.method == "POST"
        assert raw.path == "/products/_search"
        assert raw.headers == {"user-agent": "curl/7"}
        assert raw.request_body == {"query": {"match_all": {}}}
        assert raw.response_body["took"] == 42
        assert raw.client_host == "10.0.0.5"
        assert raw.gateway_took_ms == 67.0
        assert raw.request_size_bytes == 284
        assert raw.response_size_bytes == 1920

    def test_empty_payload_defaults(self):
        raw = extract_raw_fields({})
        assert raw.method == "GET"
        assert raw.path == "/"
        assert raw.headers == {}
        assert raw.request_body == {}
        assert raw.response_body == {}
        assert raw.client_host == ""
        assert raw.gateway_took_ms == 0.0
        assert raw.request_size_bytes == 0
        assert raw.response_size_bytes == 0

    def test_malformed_request_body(self):
        raw = extract_raw_fields({"request_body": "not json"})
        assert raw.request_body == {}

    def test_malformed_response_body(self):
        raw = extract_raw_fields({"response_body": "{broken"})
        assert raw.response_body == {}


# ---------------------------------------------------------------------------
# build_record
# ---------------------------------------------------------------------------

def _make_raw(**overrides):
    defaults = dict(
        method="POST",
        path="/products/_search",
        headers={
            "authorization": f"Basic {base64.b64encode(b'alice:pass').decode()}",
            "x-opaque-id": "search-api",
            "user-agent": "elasticsearch-py/8.13.0",
        },
        request_body={"query": {"match": {"title": "shoes"}}, "size": 10},
        response_body={
            "took": 42,
            "hits": {"total": {"value": 1500}, "hits": []},
            "_shards": {"total": 5},
        },
        client_host="10.0.0.5",
        gateway_took_ms=67.0,
        request_size_bytes=284,
        response_size_bytes=1920,
    )
    defaults.update(overrides)
    return RawFields(**defaults)


class TestBuildRecord:
    def test_search_record_identity(self):
        rec = build_record(_make_raw())
        assert rec["identity"]["username"] == "alice"
        assert rec["identity"]["applicative_provider"] == "search-api"
        assert rec["identity"]["user_agent"] == "elasticsearch-py/8.13.0"
        assert rec["identity"]["client_host"] == "10.0.0.5"

    def test_search_record_request(self):
        rec = build_record(_make_raw())
        assert rec["request"]["operation"] == "_search"
        assert rec["request"]["method"] == "POST"
        assert rec["request"]["path"] == "/products/_search"
        assert rec["request"]["target"] == "products"
        assert rec["request"]["size"] == 10
        assert rec["request"]["size_bytes"] == 284

    def test_search_record_response(self):
        rec = build_record(_make_raw())
        assert rec["response"]["es_took_ms"] == 42
        assert rec["response"]["hits"] == 1500
        assert rec["response"]["shards_total"] == 5
        assert rec["response"]["gateway_took_ms"] == 67.0
        assert rec["response"]["size_bytes"] == 1920

    def test_search_includes_size(self):
        rec = build_record(_make_raw())
        assert "size" in rec["request"]

    def test_non_search_excludes_size(self):
        raw = _make_raw(
            method="PUT",
            path="/myindex/_doc/123",
            request_body={"title": "test"},
            response_body={"took": 5, "_shards": {"total": 2}},
        )
        rec = build_record(raw)
        assert rec["request"]["operation"] == "index"
        assert "size" not in rec["request"]

    def test_template_scrubbed(self):
        rec = build_record(_make_raw())
        template = json.loads(rec["request"]["template"])
        assert template["query"]["match"]["title"] == "?"
        assert template["size"] == "?"

    def test_empty_body_empty_template(self):
        raw = _make_raw(request_body={}, path="/myindex/_doc/123", method="PUT",
                        response_body={"took": 1, "_shards": {"total": 1}})
        rec = build_record(raw)
        assert rec["request"]["template"] == ""

    def test_timestamp_format(self):
        rec = build_record(_make_raw())
        ts = rec["@timestamp"]
        # Should parse as valid datetime
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.000Z")

    def test_clause_counts_present(self):
        rec = build_record(_make_raw())
        cc = rec["clause_counts"]
        assert "bool" in cc
        assert "wildcard" in cc
        assert "script" in cc
        assert "agg" in cc

    def test_cost_indicators_for_clean_query(self):
        rec = build_record(_make_raw())
        assert rec["cost_indicators"] == {}
        assert rec["stress"]["cost_indicator_count"] == 0
        assert rec["stress"]["cost_indicator_names"] == []
        assert rec["stress"]["multiplier"] == 1.0

    def test_cost_indicators_for_script_query(self):
        raw = _make_raw(
            request_body={
                "query": {"script_score": {
                    "query": {"match_all": {}},
                    "script": {"source": "doc['price'].value"},
                }},
                "size": 10,
            },
        )
        rec = build_record(raw)
        assert "has_script" in rec["cost_indicators"]
        assert rec["cost_indicators"]["has_script"] >= 1
        assert rec["stress"]["cost_indicator_count"] >= 1
        assert "has_script" in rec["stress"]["cost_indicator_names"]
        assert rec["stress"]["multiplier"] >= 1.5

    def test_stress_score_present_and_rounded(self):
        rec = build_record(_make_raw())
        score = rec["stress"]["score"]
        assert isinstance(score, float)
        # Should be rounded to 4 decimal places
        score_str = str(score)
        if "." in score_str:
            assert len(score_str.split(".")[1]) <= 4

    def test_bulk_uses_bulk_shards(self):
        raw = _make_raw(
            method="POST",
            path="/_bulk",
            request_body={},
            response_body={
                "took": 10,
                "items": [
                    {"index": {"_index": "idx1", "_shards": {"total": 2}}},
                    {"index": {"_index": "idx2", "_shards": {"total": 3}}},
                ],
            },
        )
        rec = build_record(raw)
        assert rec["request"]["operation"] == "_bulk"
        assert rec["response"]["shards_total"] == 5  # 2 + 3
        assert rec["response"]["docs_affected"] == 2

    def test_update_by_query_docs_affected(self):
        raw = _make_raw(
            method="POST",
            path="/myindex/_update_by_query",
            request_body={"query": {"match_all": {}}, "script": {"source": "ctx._source.x = 1"}},
            response_body={"took": 100, "updated": 42, "_shards": {"total": 3}},
        )
        rec = build_record(raw)
        assert rec["request"]["operation"] == "_update_by_query"
        assert rec["response"]["docs_affected"] == 42

    def test_delete_by_query_docs_affected(self):
        raw = _make_raw(
            method="POST",
            path="/myindex/_delete_by_query",
            request_body={"query": {"range": {"price": {"lt": 5}}}},
            response_body={"took": 50, "deleted": 10, "_shards": {"total": 3}},
        )
        rec = build_record(raw)
        assert rec["response"]["docs_affected"] == 10

    def test_multi_clause_bool_scores_higher(self):
        """A 10-clause bool query should score higher than a simple match query."""
        simple_raw = _make_raw()
        bool_body = {
            "query": {"bool": {
                "must": [{"match": {"f": "v"}} for _ in range(5)],
                "filter": [{"term": {"f": "v"}} for _ in range(5)],
            }},
            "size": 10,
        }
        complex_raw = _make_raw(request_body=bool_body)
        simple_score = build_record(simple_raw)["stress"]["score"]
        complex_score = build_record(complex_raw)["stress"]["score"]
        assert complex_score > simple_score

    def test_es_took_fallback_to_gateway(self):
        """When es_took_ms is 0, stress uses gateway_took_ms."""
        raw = _make_raw(
            response_body={"hits": {"total": {"value": 0}, "hits": []}, "_shards": {"total": 1}},
            gateway_took_ms=200.0,
        )
        rec = build_record(raw)
        # es_took_ms is 0, so ctx.es_took_ms should be gateway_took_ms=200
        assert rec["response"]["es_took_ms"] == 0
        assert rec["stress"]["score"] > 0  # gateway_took_ms drives score


# ---------------------------------------------------------------------------
# partial_error_record
# ---------------------------------------------------------------------------

class TestPartialErrorRecord:
    def test_basic(self):
        payload = {"path": "/test/_search", "method": "POST"}
        rec = partial_error_record(payload, ValueError("bad value"))
        assert rec["error"] == "bad value"
        assert rec["path"] == "/test/_search"
        assert rec["method"] == "POST"
        assert "@timestamp" in rec

    def test_empty_payload(self):
        rec = partial_error_record({}, RuntimeError("boom"))
        assert rec["error"] == "boom"
        assert rec["path"] == ""
        assert rec["method"] == ""
