"""Unit tests for analyzer/parser.py — all extraction functions."""

import base64
import json
import pytest

from parser import (
    parse_username,
    parse_applicative_provider,
    parse_user_agent,
    parse_target,
    parse_operation,
    parse_size,
    scrub_template,
    parse_hits,
    parse_shards_total,
    parse_shards_total_bulk,
    parse_docs_affected,
    parse_es_took_ms,
)


# ---------------------------------------------------------------------------
# Header extraction: parse_username
# ---------------------------------------------------------------------------

class TestParseUsername:
    def test_basic_auth(self):
        token = base64.b64encode(b"alice:password").decode()
        assert parse_username({"authorization": f"Basic {token}"}) == "alice"

    def test_basic_auth_no_password(self):
        token = base64.b64encode(b"bob:").decode()
        assert parse_username({"authorization": f"Basic {token}"}) == "bob"

    def test_basic_auth_colon_in_password(self):
        token = base64.b64encode(b"carol:p@ss:word").decode()
        assert parse_username({"authorization": f"Basic {token}"}) == "carol"

    def test_no_auth_header(self):
        assert parse_username({}) == ""

    def test_empty_auth_header(self):
        assert parse_username({"authorization": ""}) == ""

    def test_bearer_token_ignored(self):
        assert parse_username({"authorization": "Bearer eyJhbGciOiJI..."}) == ""

    def test_invalid_base64(self):
        assert parse_username({"authorization": "Basic !!!invalid!!!"}) == ""

    def test_case_sensitive_prefix(self):
        token = base64.b64encode(b"dave:pw").decode()
        # "basic " (lowercase) should not match — prefix is "Basic "
        assert parse_username({"authorization": f"basic {token}"}) == ""


# ---------------------------------------------------------------------------
# Header extraction: parse_applicative_provider
# ---------------------------------------------------------------------------

class TestParseApplicativeProvider:
    def test_x_opaque_id(self):
        assert parse_applicative_provider({"x-opaque-id": "search-api"}) == "search-api"

    def test_x_opaque_id_strips_pod_suffix(self):
        assert parse_applicative_provider({"x-opaque-id": "search-api/pod-abc123"}) == "search-api"

    def test_x_app_name_fallback(self):
        assert parse_applicative_provider({"x-app-name": "catalog-sync"}) == "catalog-sync"

    def test_x_opaque_id_takes_priority_over_x_app_name(self):
        headers = {"x-opaque-id": "opaque-svc", "x-app-name": "app-svc"}
        assert parse_applicative_provider(headers) == "opaque-svc"

    def test_user_agent_fallback(self):
        assert parse_applicative_provider({"user-agent": "elasticsearch-py/8.13.0"}) == "elasticsearch-py"

    def test_user_agent_with_space(self):
        assert parse_applicative_provider({"user-agent": "curl 7.81.0"}) == "curl"

    def test_no_headers(self):
        assert parse_applicative_provider({}) == ""

    def test_all_empty(self):
        headers = {"x-opaque-id": "", "x-app-name": "", "user-agent": ""}
        assert parse_applicative_provider(headers) == ""

    def test_x_app_name_priority_over_user_agent(self):
        headers = {"x-app-name": "my-app", "user-agent": "curl/7.81.0"}
        assert parse_applicative_provider(headers) == "my-app"


# ---------------------------------------------------------------------------
# Header extraction: parse_user_agent
# ---------------------------------------------------------------------------

class TestParseUserAgent:
    def test_present(self):
        assert parse_user_agent({"user-agent": "curl/7.81.0"}) == "curl/7.81.0"

    def test_missing(self):
        assert parse_user_agent({}) == ""


# ---------------------------------------------------------------------------
# Path parsing: parse_target
# ---------------------------------------------------------------------------

class TestParseTarget:
    def test_single_index(self):
        assert parse_target("/products/_search") == "products"

    def test_wildcard_index(self):
        assert parse_target("/logs-*/_search") == "logs-*"

    def test_multi_index(self):
        assert parse_target("/index1,index2/_search") == "index1,index2"

    def test_no_index_all_underscore(self):
        assert parse_target("/_search") == "_all"

    def test_doc_path(self):
        assert parse_target("/myindex/_doc/123") == "myindex"

    def test_bulk_no_index(self):
        assert parse_target("/_bulk") == "_all"

    def test_nested_path(self):
        assert parse_target("/myindex/_update_by_query") == "myindex"

    def test_root_path(self):
        assert parse_target("/") == "_all"

    def test_empty_path(self):
        assert parse_target("") == "_all"

    def test_create_path(self):
        assert parse_target("/myindex/_create/abc") == "myindex"


# ---------------------------------------------------------------------------
# Path parsing: parse_operation
# ---------------------------------------------------------------------------

class TestParseOperation:
    def test_search(self):
        assert parse_operation("POST", "/products/_search") == "_search"

    def test_bulk(self):
        assert parse_operation("POST", "/_bulk") == "_bulk"

    def test_doc_put_is_index(self):
        assert parse_operation("PUT", "/myindex/_doc/123") == "index"

    def test_doc_delete(self):
        assert parse_operation("DELETE", "/myindex/_doc/123") == "delete"

    def test_create(self):
        assert parse_operation("PUT", "/myindex/_create/abc") == "_create"

    def test_update(self):
        assert parse_operation("POST", "/myindex/_update/abc") == "_update"

    def test_update_by_query(self):
        assert parse_operation("POST", "/myindex/_update_by_query") == "_update_by_query"

    def test_delete_by_query(self):
        assert parse_operation("POST", "/myindex/_delete_by_query") == "_delete_by_query"

    def test_no_underscore_segment_dispatches_on_method(self):
        assert parse_operation("GET", "/myindex") == "get"
        assert parse_operation("PUT", "/myindex") == "index"
        assert parse_operation("DELETE", "/myindex") == "delete"

    def test_root_dispatches_on_method(self):
        assert parse_operation("GET", "/") == "get"
        assert parse_operation("POST", "/") == "index"

    def test_doc_get(self):
        assert parse_operation("GET", "/myindex/_doc/123") == "get"


# ---------------------------------------------------------------------------
# Request body extraction
# ---------------------------------------------------------------------------

class TestParseSize:
    def test_explicit_size(self):
        assert parse_size({"size": 50}) == 50

    def test_default_size(self):
        assert parse_size({}) == 10

    def test_zero_size(self):
        assert parse_size({"size": 0}) == 0


class TestScrubTemplate:
    def test_simple_query(self):
        body = {"query": {"match": {"title": "shoes"}}, "size": 10}
        result = json.loads(scrub_template(body))
        assert result == {"query": {"match": {"title": "?"}}, "size": "?"}

    def test_nested_values_scrubbed(self):
        body = {"query": {"bool": {"must": [{"term": {"color": "red"}}]}}}
        result = json.loads(scrub_template(body))
        assert result == {"query": {"bool": {"must": [{"term": {"color": "?"}}]}}}

    def test_empty_body(self):
        assert scrub_template({}) == "{}"

    def test_list_values(self):
        body = {"terms": {"ids": [1, 2, 3]}}
        result = json.loads(scrub_template(body))
        assert result == {"terms": {"ids": ["?", "?", "?"]}}

    def test_sort_keys(self):
        body = {"z_field": 1, "a_field": 2}
        template = scrub_template(body)
        assert template.index("a_field") < template.index("z_field")


# ---------------------------------------------------------------------------
# Response body extraction
# ---------------------------------------------------------------------------

class TestParseHits:
    def test_standard_response(self):
        resp = {"hits": {"total": {"value": 1500}, "hits": []}}
        assert parse_hits(resp) == 1500

    def test_missing_hits(self):
        assert parse_hits({}) == 0

    def test_missing_total(self):
        assert parse_hits({"hits": {}}) == 0


class TestParseShardsTotal:
    def test_standard(self):
        assert parse_shards_total({"_shards": {"total": 5}}) == 5

    def test_missing(self):
        assert parse_shards_total({}) == 0


class TestParseShardsTotalBulk:
    def test_bulk_response(self):
        resp = {
            "items": [
                {"index": {"_index": "idx1", "_shards": {"total": 2}}},
                {"index": {"_index": "idx1", "_shards": {"total": 2}}},  # duplicate index
                {"index": {"_index": "idx2", "_shards": {"total": 3}}},
            ]
        }
        # idx1=2 + idx2=3 = 5 (deduped by index name)
        assert parse_shards_total_bulk(resp) == 5

    def test_empty_bulk(self):
        assert parse_shards_total_bulk({"items": []}) == 0

    def test_no_items(self):
        assert parse_shards_total_bulk({}) == 0

    def test_single_index(self):
        resp = {
            "items": [
                {"index": {"_index": "idx1", "_shards": {"total": 3}}},
                {"create": {"_index": "idx1", "_shards": {"total": 3}}},
            ]
        }
        assert parse_shards_total_bulk(resp) == 3


# ---------------------------------------------------------------------------
# docs_affected
# ---------------------------------------------------------------------------

class TestParseDocsAffected:
    def test_bulk(self):
        resp = {"items": [{"index": {}}, {"index": {}}, {"create": {}}]}
        assert parse_docs_affected("_bulk", resp) == 3

    def test_update_by_query(self):
        assert parse_docs_affected("_update_by_query", {"updated": 42}) == 42

    def test_delete_by_query(self):
        assert parse_docs_affected("_delete_by_query", {"deleted": 10}) == 10

    def test_search_returns_zero(self):
        assert parse_docs_affected("_search", {"hits": {"total": {"value": 100}}}) == 0

    def test_unknown_op(self):
        assert parse_docs_affected("_create", {}) == 0

    def test_missing_field(self):
        assert parse_docs_affected("_update_by_query", {}) == 0


# ---------------------------------------------------------------------------
# es_took_ms
# ---------------------------------------------------------------------------

class TestParseEsTookMs:
    def test_present(self):
        assert parse_es_took_ms({"took": 42}) == 42.0

    def test_missing(self):
        assert parse_es_took_ms({}) == 0.0

    def test_float_value(self):
        assert parse_es_took_ms({"took": 3.5}) == 3.5
