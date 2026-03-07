"""
Pure extraction functions — no I/O, no side effects.
"""

import base64
import json
import re
from typing import Callable

_BASIC_AUTH_PREFIX = "Basic "
_ES_DEFAULT_SIZE   = 10
_SCRUB_PLACEHOLDER = "?"

# (operation, response_body → docs affected count)
_DOCS_AFFECTED_EXTRACTORS: list[tuple[str, Callable[[dict], int]]] = [
    ("_bulk",            lambda response_body: len(response_body.get("items", []))),
    ("_update_by_query", lambda response_body: response_body.get("updated", 0)),
    ("_delete_by_query", lambda response_body: response_body.get("deleted", 0)),
]


# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------

def parse_username(headers: dict) -> str:
    auth = headers.get("authorization", "")
    if auth.startswith(_BASIC_AUTH_PREFIX):
        try:
            decoded = base64.b64decode(auth[len(_BASIC_AUTH_PREFIX):]).decode("utf-8", errors="replace")
            return decoded.split(":")[0]
        except ValueError:
            pass
    return ""


def parse_applicative_provider(headers: dict) -> str:
    opaque = headers.get("x-opaque-id", "")
    if opaque:
        return opaque.split("/")[0]

    app_name = headers.get("x-app-name", "")
    if app_name:
        return app_name

    user_agent = headers.get("user-agent", "")
    if user_agent:
        return re.split(r"[/ ]", user_agent)[0]

    return ""


def parse_user_agent(headers: dict) -> str:
    return headers.get("user-agent", "")


def parse_client_host(payload: dict) -> str:
    return payload.get("client_host", "")


# ---------------------------------------------------------------------------
# Path / URL extraction
# ---------------------------------------------------------------------------

def parse_target(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment]
    for segment in segments:
        if not segment.startswith("_"):
            return segment
    return "_all"


def parse_operation(method: str, path: str) -> str:
    for segment in reversed(path.split("/")):
        if segment.startswith("_"):
            if segment == "_doc":
                return "index" if method == "PUT" else "delete"
            return segment
    return "_search"


# ---------------------------------------------------------------------------
# Request body extraction
# ---------------------------------------------------------------------------

def parse_size(body: dict) -> int:
    return body.get("size", _ES_DEFAULT_SIZE)


def _has_key_recursive(node, key: str) -> bool:
    if isinstance(node, dict):
        if key in node:
            return True
        return any(_has_key_recursive(value, key) for value in node.values())
    if isinstance(node, list):
        return any(_has_key_recursive(item, key) for item in node)
    return False


def parse_has_script(body: dict) -> bool:
    return _has_key_recursive(body, "script")


def parse_has_runtime_mappings(body: dict) -> bool:
    return "runtime_mappings" in body


def _scrub(node):
    if isinstance(node, dict):
        return {key: _scrub(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_scrub(item) for item in node]
    return _SCRUB_PLACEHOLDER


def scrub_template(body: dict) -> str:
    return json.dumps(_scrub(body), sort_keys=True)


# ---------------------------------------------------------------------------
# Response body extraction
# ---------------------------------------------------------------------------

def parse_hits(response_body: dict) -> int:
    return response_body.get("hits", {}).get("total", {}).get("value", 0)


def parse_shards_total(response_body: dict) -> int:
    return response_body.get("_shards", {}).get("total", 0)


def parse_docs_affected(operation: str, response_body: dict) -> int:
    for registered_op, extractor in _DOCS_AFFECTED_EXTRACTORS:
        if operation == registered_op:
            return extractor(response_body)
    return 0


def parse_es_took_ms(response_body: dict) -> float:
    return float(response_body.get("took", 0))
