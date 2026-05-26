"""Unit tests for analyzer/record_builder.py — flat ClickHouse-shaped records."""

import base64
import json
from datetime import datetime
from typing import Any

import pytest

from analyzer import record_builder
from analyzer.record_builder import (
    _CLAUSE_COUNT_OUTPUT_KEYS,
    _COST_INDICATOR_KEYS,
    _STRESS_COMPONENT_KEYS,
    RawFields,
    _parse_content_length,
    _parse_json_field,
    _parse_upstream_response_time,
    _truncate_body,
    build_record,
    extract_raw_fields,
    partial_error_record,
)
from analyzer.stress import _ALL_COUNT_FIELDS


# ── Parse helpers ──────────────────────────────────────────────────────────

class TestParseJsonField:
    def test_valid_json(self):
        assert _parse_json_field('{"a": 1}') == {"a": 1}

    def test_empty_string(self):
        assert _parse_json_field("") == {}

    def test_invalid_json(self):
        assert _parse_json_field("not json") == {}

    def test_none_like_empty(self):
        assert _parse_json_field("") == {}


class TestParseUpstreamResponseTime:
    def test_normal_seconds_to_ms(self):
        assert _parse_upstream_response_time("0.067") == 67.0

    def test_empty_string(self):
        assert _parse_upstream_response_time("") == 0.0

    def test_invalid_value(self):
        assert _parse_upstream_response_time("abc") == 0.0

    def test_zero(self):
        assert _parse_upstream_response_time("0") == 0.0

    def test_large_value(self):
        assert _parse_upstream_response_time("1.5") == 1500.0


class TestParseContentLength:
    def test_normal_value(self):
        assert _parse_content_length("284") == 284

    def test_empty_string(self):
        assert _parse_content_length("") == 0

    def test_invalid_value(self):
        assert _parse_content_length("abc") == 0

    def test_zero(self):
        assert _parse_content_length("0") == 0


# ── extract_raw_fields ─────────────────────────────────────────────────────

class TestExtractRawFields:
    def test_full_payload(self):
        payload = {
            "method": "POST",
            "path": "/products/_search",
            "headers": {"user-agent": "curl/7"},
            "request_body": '{"query":{"match_all":{}}}',
            "response_body": '{"took":42,"hits":{"total":{"value":10},"hits":[]}}',
            "client_host": "10.0.0.5",
            "upstream_response_time": "0.067",
            "content_length": "284",
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


# ── Structural sync ────────────────────────────────────────────────────────

class TestClauseCountKeySync:
    def test_all_count_fields_have_output_mapping(self):
        assert set(_ALL_COUNT_FIELDS) == set(_CLAUSE_COUNT_OUTPUT_KEYS.keys())

    def test_cost_indicator_keys_count(self):
        # Sanity: must match the column inventory in clickhouse_setup/_schema.py
        assert len(_COST_INDICATOR_KEYS) == 11

    def test_stress_component_keys_count(self):
        # took, shards, hits, docs_affected, bonus → 5 component columns
        assert set(_STRESS_COMPONENT_KEYS) == {
            "took", "shards", "hits", "docs_affected", "bonus",
        }


# ── build_record (flat shape) ──────────────────────────────────────────────

def _make_raw(**overrides: Any) -> RawFields:
    defaults = dict(
        method="POST",
        path="/products/_search",
        headers={
            "authorization": f"Basic {base64.b64encode(b'alice:pass').decode()}",
            "x-opaque-id": "search-api",
            "user-agent": "elasticsearch-py/8.13.0",
        },
        request_body={"query": {"match": {"title": "shoes"}}, "size": 10},
        request_body_raw='{"query": {"match": {"title": "shoes"}}, "size": 10}',
        response_body={
            "took": 42,
            "hits": {"total": {"value": 1500}, "hits": []},
            "_shards": {"total": 5},
        },
        client_host="10.0.0.5",
        response_status=200,
        gateway_took_ms=67.0,
        request_size_bytes=284,
        response_size_bytes=1920,
        cluster_name="default",
    )
    defaults.update(overrides)
    return RawFields(**defaults)


class TestBuildRecord:
    def test_search_record_identity(self):
        rec = build_record(_make_raw())
        assert rec["identity_username"] == "alice"
        assert rec["identity_applicative_provider"] == "search-api"
        assert rec["identity_user_agent"] == "elasticsearch-py/8.13.0"
        assert rec["identity_client_host"] == "10.0.0.5"
        assert rec["identity_labels"] == {}

    def test_custom_labels_from_alo_headers(self):
        headers = {
            "authorization": f"Basic {base64.b64encode(b'alice:pass').decode()}",
            "x-opaque-id": "search-api",
            "user-agent": "elasticsearch-py/8.13.0",
            "x-alo-team": "payments",
            "x-alo-env": "staging",
        }
        rec = build_record(_make_raw(headers=headers))
        assert rec["identity_labels"] == {"team": "payments", "env": "staging"}

    def test_search_record_request(self):
        rec = build_record(_make_raw())
        assert rec["request_operation"] == "_search"
        assert rec["request_method"] == "POST"
        assert rec["request_path"] == "/products/_search"
        assert rec["request_target"] == "products"
        assert rec["request_size"] == 10
        assert rec["request_size_bytes"] == 284

    def test_search_record_response(self):
        rec = build_record(_make_raw())
        assert rec["response_es_took_ms"] == 42
        assert rec["response_hits"] == 1500
        assert rec["response_shards_total"] == 5
        assert rec["response_gateway_took_ms"] == 67.0
        assert rec["response_size_bytes"] == 1920

    def test_search_records_size(self):
        rec = build_record(_make_raw())
        assert rec["request_size"] == 10

    def test_non_search_size_defaults_to_zero(self):
        raw = _make_raw(
            method="PUT",
            path="/myindex/_doc/123",
            request_body={"title": "test"},
            response_body={"took": 5, "_shards": {"total": 2}},
        )
        rec = build_record(raw)
        assert rec["request_operation"] == "index"
        # Flat schema always emits the column; non-search defaults to 0.
        assert rec["request_size"] == 0

    def test_template_scrubbed(self):
        rec = build_record(_make_raw())
        template = json.loads(rec["request_template"])
        assert template["query"]["match"]["title"] == "?"
        assert template["size"] == "?"

    def test_empty_body_empty_template(self):
        raw = _make_raw(request_body={}, path="/myindex/_doc/123", method="PUT",
                        response_body={"took": 1, "_shards": {"total": 1}})
        rec = build_record(raw)
        assert rec["request_template"] == ""

    def test_timestamp_format(self):
        rec = build_record(_make_raw())
        ts = rec["timestamp"]
        # CH DateTime64 format: "YYYY-MM-DD HH:MM:SS.mmm"
        datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f")

    def test_clause_counts_flattened(self):
        rec = build_record(_make_raw())
        for suffix in _CLAUSE_COUNT_OUTPUT_KEYS.values():
            assert f"clause_counts_{suffix}" in rec

    def test_cost_indicators_for_clean_query(self):
        rec = build_record(_make_raw())
        for name in _COST_INDICATOR_KEYS:
            assert rec[f"cost_indicators_{name}"] == 0
        assert rec["stress_cost_indicator_count"] == 0
        assert rec["stress_cost_indicator_names"] == ["unflagged"]
        assert rec["stress_multiplier"] == 1.0

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
        assert rec["cost_indicators_has_script"] >= 1
        assert rec["stress_cost_indicator_count"] >= 1
        assert "has_script" in rec["stress_cost_indicator_names"]
        assert rec["stress_multiplier"] >= 1.5
        assert rec["stress_cost_indicator_multipliers"]["has_script"] == 1.5

    def test_stress_score_present_and_rounded(self):
        rec = build_record(_make_raw())
        score = rec["stress_score"]
        assert isinstance(score, float)
        score_str = str(score)
        if "." in score_str:
            assert len(score_str.split(".")[1]) <= 4

    def test_all_stress_components_emitted(self):
        rec = build_record(_make_raw())
        for key in _STRESS_COMPONENT_KEYS:
            assert f"stress_components_{key}" in rec

    def test_bulk_uses_bulk_shards(self):
        bulk_ndjson = (
            '{"index":{"_index":"idx1"}}\n'
            '{"title":"a"}\n'
            '{"index":{"_index":"idx2"}}\n'
            '{"title":"b"}\n'
        )
        raw = _make_raw(
            method="POST",
            path="/_bulk",
            request_body={},
            request_body_raw=bulk_ndjson,
            response_body={
                "took": 10,
                "items": [
                    {"index": {"_index": "idx1", "_shards": {"total": 2}}},
                    {"index": {"_index": "idx2", "_shards": {"total": 3}}},
                ],
            },
        )
        rec = build_record(raw)
        assert rec["request_operation"] == "_bulk"
        assert rec["response_shards_total"] == 5
        assert rec["response_docs_affected"] == 2
        assert rec["request_target"] == "idx1,idx2"
        assert "index" in rec["request_template"]

    def test_bulk_doc_count_absent_for_non_bulk(self):
        """request.bulk_doc_count must not appear in non-bulk records."""
        rec = build_record(_make_raw())  # _search
        assert "bulk_doc_count" not in rec["request"]

    def test_bulk_doc_count_zero_for_empty_body(self):
        """A bulk request with no body lines → bulk_doc_count = 0."""
        raw = _make_raw(
            method="POST",
            path="/_bulk",
            request_body={},
            request_body_raw="",
            response_body={
                "took": 10,
                "items": [],
            },
        )
        rec = build_record(raw)
        assert rec["request"]["bulk_doc_count"] == 0

    def test_update_by_query_docs_affected(self):
        raw = _make_raw(
            method="POST",
            path="/myindex/_update_by_query",
            request_body={"query": {"match_all": {}}, "script": {"source": "ctx._source.x = 1"}},
            response_body={"took": 100, "updated": 42, "_shards": {"total": 3}},
        )
        rec = build_record(raw)
        assert rec["request_operation"] == "_update_by_query"
        assert rec["response_docs_affected"] == 42

    def test_delete_by_query_docs_affected(self):
        raw = _make_raw(
            method="POST",
            path="/myindex/_delete_by_query",
            request_body={"query": {"range": {"price": {"lt": 5}}}},
            response_body={"took": 50, "deleted": 10, "_shards": {"total": 3}},
        )
        rec = build_record(raw)
        assert rec["response_docs_affected"] == 10

    def test_non_query_ops_zero_clause_counts(self):
        raw = _make_raw(
            method="PUT",
            path="/myindex/_doc/123",
            request_body={"title": "test"},
            response_body={"took": 5, "_shards": {"total": 2}},
        )
        rec = build_record(raw)
        assert rec["request_operation"] == "index"
        for suffix in _CLAUSE_COUNT_OUTPUT_KEYS.values():
            assert rec[f"clause_counts_{suffix}"] == 0
        for name in _COST_INDICATOR_KEYS:
            assert rec[f"cost_indicators_{name}"] == 0
        assert rec["stress_multiplier"] == 1.0

    def test_get_operation(self):
        raw = _make_raw(
            method="GET",
            path="/myindex/_doc/123",
            request_body={},
            response_body={"took": 5, "_shards": {"total": 2}},
        )
        rec = build_record(raw)
        assert rec["request_operation"] == "get"
        for suffix in _CLAUSE_COUNT_OUTPUT_KEYS.values():
            assert rec[f"clause_counts_{suffix}"] == 0
        assert rec["stress_score"] > 0

    def test_count_operation_gets_clause_counts(self):
        raw = _make_raw(
            method="POST",
            path="/myindex/_count",
            request_body={"query": {"bool": {"must": [{"match": {"f": "v"}}]}}},
            response_body={"count": 42, "_shards": {"total": 3}},
        )
        rec = build_record(raw)
        assert rec["request_operation"] == "_count"
        assert rec["clause_counts_bool"] == 1
        assert rec["clause_counts_bool_must"] == 1

    def test_multi_clause_bool_scores_higher(self):
        simple_raw = _make_raw()
        bool_body = {
            "query": {"bool": {
                "must": [{"match": {"f": "v"}} for _ in range(5)],
                "filter": [{"term": {"f": "v"}} for _ in range(5)],
            }},
            "size": 10,
        }
        complex_raw = _make_raw(request_body=bool_body)
        simple_score = build_record(simple_raw)["stress_score"]
        complex_score = build_record(complex_raw)["stress_score"]
        assert complex_score > simple_score

    def test_bulk_nanosecond_took_normalized(self):
        raw = _make_raw(
            method="POST",
            path="/_bulk",
            request_body={},
            request_body_raw='{"index":{"_index":"idx"}}\n{"title":"a"}\n',
            response_body={
                "took": 24_124_260_718,
                "items": [{"index": {"_index": "idx", "_shards": {"total": 2}}}],
            },
            gateway_took_ms=24_200.0,
        )
        rec = build_record(raw)
        assert rec["response_es_took_ms"] == pytest.approx(24_124.26, rel=1e-3)

    def test_bulk_normal_took_not_normalized(self):
        raw = _make_raw(
            method="POST",
            path="/_bulk",
            request_body={},
            request_body_raw='{"index":{"_index":"idx"}}\n{"title":"a"}\n',
            response_body={
                "took": 150,
                "items": [{"index": {"_index": "idx", "_shards": {"total": 2}}}],
            },
            gateway_took_ms=0.0,
        )
        rec = build_record(raw)
        assert rec["response_es_took_ms"] == 150.0

    def test_search_high_took_not_normalized(self):
        raw = _make_raw(
            response_body={
                "took": 5_000_000,
                "hits": {"total": {"value": 0}, "hits": []},
                "_shards": {"total": 1},
            },
            gateway_took_ms=200.0,
        )
        rec = build_record(raw)
        assert rec["response_es_took_ms"] == 5_000_000.0

    def test_score_nonzero_when_es_took_is_zero(self):
        raw = _make_raw(
            response_body={"hits": {"total": {"value": 0}, "hits": []}, "_shards": {"total": 1}},
            gateway_took_ms=200.0,
        )
        rec = build_record(raw)
        assert rec["response_es_took_ms"] == 0
        assert rec["stress_score"] > 0


class TestMsearchFanOut:
    def test_msearch_returns_records_envelope(self):
        ndjson = '{"index":"a"}\n{"query":{"match_all":{}}}\n'
        raw = _make_raw(
            method="POST",
            path="/_msearch",
            request_body={},
            request_body_raw=ndjson,
            response_body={"responses": [
                {"took": 5, "hits": {"total": {"value": 1}, "hits": []},
                 "_shards": {"total": 1}},
            ]},
        )
        result = build_record(raw)
        assert "_msearch_records" in result
        records = result["_msearch_records"]
        assert len(records) == 1
        rec = records[0]
        assert rec["request_operation"] == "_msearch"
        assert rec["msearch_batch_size"] == 1
        assert rec["msearch_sub_query_index"] == 0
        assert isinstance(rec["msearch_request_id"], str)


# ── partial_error_record ──────────────────────────────────────────────────

class TestPartialErrorRecord:
    def test_basic(self):
        payload = {"path": "/test/_search", "method": "POST", "cluster_name": "prod"}
        rec = partial_error_record(payload, ValueError("bad value"))
        assert rec["error"] == "bad value"
        assert rec["request_path"] == "/test/_search"
        assert rec["request_method"] == "POST"
        assert rec["cluster_name"] == "prod"
        assert "timestamp" in rec
        assert "raw" in rec

    def test_empty_payload(self):
        rec = partial_error_record({}, RuntimeError("boom"))
        assert rec["error"] == "boom"
        assert rec["request_path"] == ""
        assert rec["request_method"] == ""
        assert rec["cluster_name"] == "default"
