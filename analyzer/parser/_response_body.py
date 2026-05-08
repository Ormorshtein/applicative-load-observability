"""Response body extraction — parse hits, shards, docs-affected, and timing from ES responses."""

from collections.abc import Callable

_DOCS_AFFECTED_EXTRACTORS: list[tuple[str, Callable[[dict], int]]] = [
    ("_bulk",            lambda response_body: len(response_body.get("items", []))),
    ("_update_by_query", lambda response_body: response_body.get("updated", 0)),
    ("_delete_by_query", lambda response_body: response_body.get("deleted", 0)),
]


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
    return int(response_body.get("_shards", {}).get("total", 0))


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
