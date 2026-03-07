"""
Pure extraction functions — no I/O, no side effects.
"""

import base64
import json
import re


# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------

def parse_username(headers: dict) -> str:
    auth = headers.get("authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8", errors="replace")
            return decoded.split(":")[0]
        except Exception:
            pass
    return ""


def parse_applicative_provider(headers: dict) -> str:
    opaque = headers.get("x-opaque-id", "")
    if opaque:
        return opaque.split("/")[0]

    app_name = headers.get("x-app-name", "")
    if app_name:
        return app_name

    ua = headers.get("user-agent", "")
    if ua:
        return re.split(r"[/ ]", ua)[0]

    return ""


def parse_user_agent(headers: dict) -> str:
    return headers.get("user-agent", "")


def parse_client_host(payload: dict) -> str:
    return payload.get("client_host", "")


# ---------------------------------------------------------------------------
# Path / URL extraction
# ---------------------------------------------------------------------------

def parse_target(path: str) -> str:
    segments = [s for s in path.split("/") if s]
    for seg in segments:
        if not seg.startswith("_"):
            return seg
    return "_all"


def parse_operation_kind(method: str, path: str) -> str:
    if "_search" in path:
        return "query"
    if "_bulk" in path:
        return "insert"
    if "_create" in path:
        return "insert"
    if "_update_by_query" in path:
        return "update"
    if "_update" in path:
        return "update"
    if "_delete_by_query" in path:
        return "delete"
    if method == "DELETE":
        return "delete"
    if method == "PUT" or "_doc" in path:
        return "insert"
    return "query"


def parse_operation_type(method: str, path: str, body: dict) -> str:
    if path.endswith("_bulk"):
        return "bulk"
    if path.endswith("_update_by_query") or path.endswith("_delete_by_query"):
        return "by_query"
    if "aggs" in body or "aggregations" in body:
        return "agg"
    if "knn" in body or (isinstance(body.get("query"), dict) and "knn" in body["query"]):
        return "knn"
    query = body.get("query", {})
    if isinstance(query, dict):
        geo_types = {"geo_distance", "geo_shape", "geo_bounding_box", "geo_polygon", "geo_grid"}
        if any(k in query for k in geo_types):
            return "geo"
        text_types = {"match", "multi_match", "query_string", "simple_query_string"}
        if any(k in query for k in text_types):
            return "text"
    return "single"


# ---------------------------------------------------------------------------
# Request body extraction
# ---------------------------------------------------------------------------

def parse_size(body: dict) -> int:
    return body.get("size", 10)


def _has_key_recursive(obj, key: str) -> bool:
    if isinstance(obj, dict):
        if key in obj:
            return True
        return any(_has_key_recursive(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key_recursive(item, key) for item in obj)
    return False


def parse_has_script(body: dict) -> bool:
    return _has_key_recursive(body, "script")


def parse_has_runtime_mappings(body: dict) -> bool:
    return "runtime_mappings" in body


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(item) for item in obj]
    return "?"


def scrub_template(body: dict) -> str:
    return json.dumps(_scrub(body), sort_keys=True)


# ---------------------------------------------------------------------------
# Response body extraction
# ---------------------------------------------------------------------------

def parse_hits(response_body: dict) -> int:
    return response_body.get("hits", {}).get("total", {}).get("value", 0)


def parse_shards_total(response_body: dict) -> int:
    return response_body.get("_shards", {}).get("total", 0)


def parse_docs_affected(path: str, response_body: dict) -> int:
    if "_bulk" in path:
        return len(response_body.get("items", []))
    if "_update_by_query" in path:
        return response_body.get("updated", 0)
    if "_delete_by_query" in path:
        return response_body.get("deleted", 0)
    return 0


def parse_es_took_ms(response_body: dict) -> float:
    return float(response_body.get("took", 0))
