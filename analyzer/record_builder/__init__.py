"""Record builder package — public surface for the observability record pipeline."""

import os

from ._assembly import (
    _CLAUSE_COUNT_OUTPUT_KEYS,
    _TRUNCATION_SUFFIX,
    OperationMeta,
    ResponseMetrics,
    resolve_bulk_took,
)
from ._assembly import (
    truncate_body as _truncate_body,
)
from ._builder import (
    _parse_content_length,
    _parse_json_field,
    _parse_upstream_response_time,
    build_record,
    extract_raw_fields,
    partial_error_record,
)
from ._models import RawFields, StressResult

# ES keyword fields have a 32 766-byte UTF-8 limit.
# ALO_REQUEST_BODY_STORE_MAX_BYTES caps the *stored* request.body string at
# this size (suffix included). Default leaves a safety margin under the
# keyword limit. Override only when the request.body mapping has been
# changed (raise for text/match_only_text mappings, or set 0 to disable
# truncation entirely).
_MAX_BODY_BYTES = int(os.environ.get("ALO_REQUEST_BODY_STORE_MAX_BYTES", "32000"))

__all__ = [
    "_CLAUSE_COUNT_OUTPUT_KEYS",
    "_MAX_BODY_BYTES",
    "_TRUNCATION_SUFFIX",
    "OperationMeta",
    "RawFields",
    "ResponseMetrics",
    "StressResult",
    "_parse_content_length",
    "_parse_json_field",
    "_parse_upstream_response_time",
    "_truncate_body",
    "build_record",
    "extract_raw_fields",
    "partial_error_record",
    "resolve_bulk_took",
]
