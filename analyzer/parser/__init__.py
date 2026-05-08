"""Parser package — pure extraction functions, no I/O, no side effects."""

from ._geo import parse_geo_vertex_count
from ._headers import (
    parse_applicative_provider,
    parse_labels,
    parse_user_agent,
    parse_username,
)
from ._path import parse_operation, parse_target
from ._request_body import (
    parse_bulk_doc_count,
    parse_msearch_pairs,
    parse_size,
    scrub_bulk_template,
    scrub_template,
)
from ._response_body import (
    parse_docs_affected,
    parse_es_took_ms,
    parse_hits,
    parse_shards_total,
    parse_shards_total_bulk,
)

__all__ = [
    "parse_applicative_provider",
    "parse_bulk_doc_count",
    "parse_docs_affected",
    "parse_es_took_ms",
    "parse_geo_vertex_count",
    "parse_hits",
    "parse_labels",
    "parse_msearch_pairs",
    "parse_operation",
    "parse_shards_total",
    "parse_shards_total_bulk",
    "parse_size",
    "parse_target",
    "parse_user_agent",
    "parse_username",
    "scrub_bulk_template",
    "scrub_template",
]
