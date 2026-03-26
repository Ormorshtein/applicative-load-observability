"""
Pure extraction functions — no I/O, no side effects.
"""

import base64
import json
import re
from collections.abc import Callable
from typing import Any

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
            raw = base64.b64decode(auth[len(_BASIC_AUTH_PREFIX):])
            decoded = raw.decode("utf-8", errors="replace")
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


_LABEL_PREFIX = "x-alo-"


def parse_labels(headers: dict) -> dict[str, str]:
    """Extract custom user labels from x-alo-* headers."""
    prefix_len = len(_LABEL_PREFIX)
    return {
        key[prefix_len:]: str(value)
        for key, value in headers.items()
        if key.startswith(_LABEL_PREFIX) and len(key) > prefix_len
    }


# ---------------------------------------------------------------------------
# Path / URL extraction
# ---------------------------------------------------------------------------

def parse_target(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment]
    for segment in segments:
        if not segment.startswith("_"):
            return segment
    return "_all"


_METHOD_DISPATCH = {
    "GET":    "get",
    "HEAD":   "get",
    "PUT":    "index",
    "POST":   "index",
    "DELETE": "delete",
}


def parse_operation(method: str, path: str) -> str:
    for segment in reversed(path.split("/")):
        if segment.startswith("_"):
            if segment == "_doc":
                return _METHOD_DISPATCH.get(method, "index")
            return segment
    return _METHOD_DISPATCH.get(method, "index")


# ---------------------------------------------------------------------------
# Request body extraction
# ---------------------------------------------------------------------------

def parse_size(body: dict) -> int:
    return body.get("size", _ES_DEFAULT_SIZE)


def _scrub(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _scrub(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_scrub(item) for item in node]
    return _SCRUB_PLACEHOLDER


def scrub_template(body: dict) -> str:
    return json.dumps(_scrub(body), sort_keys=True)


def scrub_bulk_template(raw_body: str) -> tuple[str, str]:
    """Build a structural template from an NDJSON bulk request body.

    Extracts unique action types and target indices from action lines,
    producing a stable template like:
        {"actions": ["index"], "target": ["my-index"]}

    Returns (template_str, comma_separated_targets).
    """
    actions = set()
    targets = set()
    for line in raw_body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for action_type in ("index", "create", "update", "delete"):
            if action_type in obj and isinstance(obj[action_type], dict):
                actions.add(action_type)
                idx = obj[action_type].get("_index", "")
                if idx:
                    targets.add(idx)
                break
    sorted_targets = sorted(targets) if targets else ["_all"]
    target_str = ",".join(sorted_targets) if targets else "_all"
    if not actions:
        return "", target_str
    template = json.dumps({
        "actions": sorted(actions),
        "target": sorted_targets,
    }, sort_keys=True)
    return template, target_str


# ---------------------------------------------------------------------------
# Geo vertex counting
# ---------------------------------------------------------------------------


def _count_geo_vertices(node: Any) -> int:
    """Walk a query body and count total vertices in geo_shape/geo_polygon."""
    if isinstance(node, list):
        return sum(_count_geo_vertices(item) for item in node)
    if not isinstance(node, dict):
        return 0
    total = 0
    for key, value in node.items():
        if key in ("geo_shape", "geo_polygon") and isinstance(value, dict):
            for field_val in value.values():
                if not isinstance(field_val, dict):
                    continue
                shape = field_val.get("shape", field_val)
                total += _count_coords(shape.get("coordinates", []))

        if isinstance(value, (dict, list)):
            total += _count_geo_vertices(value)
    return total


def _count_coords(node: Any) -> int:
    """Count coordinate points in nested arrays."""
    if not node or not isinstance(node, list):
        return 0
    if len(node) >= 2 and isinstance(node[0], (int, float)):
        return 1
    return sum(_count_coords(item) for item in node)


def parse_geo_vertex_count(body: dict) -> int:
    """Total vertices across all geo_shape/geo_polygon clauses in the query."""
    return _count_geo_vertices(body.get("query", {}))


# ---------------------------------------------------------------------------
# Response body extraction
# ---------------------------------------------------------------------------

def parse_hits(response_body: dict) -> tuple[int, bool]:
    """Return (hit_count, is_lower_bound).

    ``is_lower_bound`` is True when ES capped counting at ``track_total_hits``
    (default 10 000) — the real hit count is higher than reported.
    """
    total = (response_body.get("hits") or {}).get("total")
    if isinstance(total, dict):
        value = total.get("value", 0) or 0
        lower_bound = total.get("relation") == "gte"
        return value, lower_bound
    return 0, False


def parse_shards_total(response_body: dict) -> int:
    return response_body.get("_shards", {}).get("total", 0)


def parse_shards_total_bulk(response_body: dict) -> int:
    """Aggregate unique-index shard counts from bulk response items."""
    seen = set()
    total = 0
    for item in response_body.get("items", []):
        for action_result in item.values():
            idx = action_result.get("_index", "")
            shards = action_result.get("_shards", {}).get("total", 0)
            if idx and idx not in seen and shards:
                seen.add(idx)
                total += shards
    return total


def parse_docs_affected(operation: str, response_body: dict) -> int:
    for registered_op, extractor in _DOCS_AFFECTED_EXTRACTORS:
        if operation == registered_op:
            return extractor(response_body)
    return 0


def parse_es_took_ms(response_body: dict) -> float:
    return float(response_body.get("took", 0))
