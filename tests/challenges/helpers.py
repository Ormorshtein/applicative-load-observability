"""Re-export shared utilities so challenge scripts can use bare imports."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from shared._data import (
    LOADTEST_MAPPING,
    ndjson,
    rand_category,
    rand_color,
    rand_doc,
    rand_int,
    rand_price,
    rand_str,
    rand_text,
)
from shared._http import add_auth_args, apply_auth_args, http_request
from shared._stats import Stats

__all__ = [
    "LOADTEST_MAPPING", "Stats",
    "add_auth_args", "apply_auth_args", "http_request", "ndjson",
    "rand_category", "rand_color", "rand_doc", "rand_int",
    "rand_price", "rand_str", "rand_text",
]
