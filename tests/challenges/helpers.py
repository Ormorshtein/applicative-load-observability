"""Re-export integration helpers so challenge scripts can use bare imports."""

import importlib.util
from pathlib import Path

_integration_helpers = Path(__file__).resolve().parent.parent / "integration" / "helpers.py"
_spec = importlib.util.spec_from_file_location("_integration_helpers", _integration_helpers)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

LOADTEST_MAPPING = _mod.LOADTEST_MAPPING
Stats = _mod.Stats
http_request = _mod.http_request
rand_category = _mod.rand_category
rand_color = _mod.rand_color
rand_doc = _mod.rand_doc
rand_int = _mod.rand_int
rand_price = _mod.rand_price
rand_str = _mod.rand_str
rand_text = _mod.rand_text
add_auth_args = _mod.add_auth_args
apply_auth_args = _mod.apply_auth_args
