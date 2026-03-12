"""Re-export integration helpers so the stress tool can use bare imports."""

import importlib.util
from pathlib import Path

_integration = Path(__file__).resolve().parent.parent.parent / "tests" / "integration" / "helpers.py"
_spec = importlib.util.spec_from_file_location("_integration_helpers", _integration)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

LOADTEST_MAPPING = _mod.LOADTEST_MAPPING
http_request = _mod.http_request
add_auth_args = _mod.add_auth_args
apply_auth_args = _mod.apply_auth_args
rand_category = _mod.rand_category
rand_color = _mod.rand_color
rand_doc = _mod.rand_doc
rand_int = _mod.rand_int
rand_price = _mod.rand_price
rand_str = _mod.rand_str
rand_text = _mod.rand_text
