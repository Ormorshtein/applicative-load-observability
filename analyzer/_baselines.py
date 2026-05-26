"""
Dynamic stress baselines from ClickHouse percentile aggregations.

When ``CLICKHOUSE_URL`` is set, refreshes ``took_ms`` and ``shards_total``
from the median of recent search traffic every ``BASELINE_CACHE_TTL``
seconds (default 60). Falls back to static defaults when ClickHouse is
unavailable or returns no rows.

Connection env vars match the rest of the stack:
``CLICKHOUSE_URL``, ``CLICKHOUSE_USER``, ``CLICKHOUSE_PASSWORD``,
``CLICKHOUSE_DATABASE``, ``CLICKHOUSE_CA_CERT``, ``CLICKHOUSE_INSECURE``.
"""

import base64
import json
import logging
import math
import os
import ssl
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_CH_URL = os.environ.get("CLICKHOUSE_URL")
_CH_USER = os.environ.get("CLICKHOUSE_USER", "default")
_CH_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
_CH_DATABASE = os.environ.get("CLICKHOUSE_DATABASE", "alo")
_CH_CA_CERT = os.environ.get("CLICKHOUSE_CA_CERT", "")
_CH_INSECURE = os.environ.get("CLICKHOUSE_INSECURE", "").lower() in ("1", "true", "yes")

_CACHE_TTL = float(os.environ.get("BASELINE_CACHE_TTL", "60"))
# CH interval syntax; default 1h matches the ES setup's "1h".
_QUERY_WINDOW = os.environ.get("BASELINE_QUERY_WINDOW", "1 HOUR")
_CH_QUERY_TIMEOUT = 5

_STATIC: dict[str, float] = {
    "took_ms":       float(os.environ.get("STRESS_BASELINE_TOOK_MS", "100")),
    "hits":          float(os.environ.get("STRESS_BASELINE_HITS", "500")),
    "shards_total":  float(os.environ.get("STRESS_BASELINE_SHARDS_TOTAL", "5")),
    "docs_affected": float(os.environ.get("STRESS_BASELINE_DOCS_AFFECTED", "500")),
}

_DYNAMIC_KEYS = ("took_ms", "shards_total")

_cache: dict[str, float] = dict(_STATIC)
_cache_ts: float = 0.0


def _build_ssl_context() -> ssl.SSLContext | None:
    if _CH_INSECURE:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if _CH_CA_CERT:
        return ssl.create_default_context(cafile=_CH_CA_CERT)
    return None


def _build_headers() -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "text/plain; charset=utf-8"}
    if _CH_USER:
        headers["X-ClickHouse-User"] = _CH_USER
    if _CH_PASSWORD:
        headers["X-ClickHouse-Key"] = _CH_PASSWORD
        token = base64.b64encode(f"{_CH_USER}:{_CH_PASSWORD}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    return headers


def _fetch_p50() -> dict[str, float]:
    """Query ClickHouse for the median of took_ms and shards_total."""
    assert _CH_URL is not None  # caller checks _CH_URL before calling
    sql = (
        f"SELECT "
        f"quantile(0.5)(response_es_took_ms)  AS took_ms, "
        f"quantile(0.5)(response_shards_total) AS shards_total "
        f"FROM {_CH_DATABASE}.alo_raw "
        f"WHERE timestamp >= now() - INTERVAL {_QUERY_WINDOW} "
        f"  AND request_operation IN ('_search','_msearch','_count') "
        f"FORMAT JSON"
    )
    url = f"{_CH_URL.rstrip('/')}/?database={_CH_DATABASE}"
    req = urllib.request.Request(url, data=sql.encode(),
                                 headers=_build_headers(), method="POST")

    ssl_ctx = _build_ssl_context()
    with urllib.request.urlopen(req, timeout=_CH_QUERY_TIMEOUT, context=ssl_ctx) as resp:
        data = json.loads(resp.read())

    rows = data.get("data", [])
    if not rows:
        return {}
    row = rows[0]
    result: dict[str, float] = {}
    for key in _DYNAMIC_KEYS:
        raw = row.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isnan(val) or val <= 0:
            continue
        result[key] = val
    return result


def _refresh() -> None:
    """Refresh cache if stale.

    NOTE: no lock — concurrent requests at TTL boundary may all fire
    _fetch_p50(). Acceptable: results are identical and CH handles it.
    """
    global _cache_ts

    now = time.monotonic()
    if now - _cache_ts < _CACHE_TTL:
        return

    if _CH_URL:
        try:
            dynamic = _fetch_p50()
            for key in _DYNAMIC_KEYS:
                _cache[key] = dynamic.get(key, _STATIC[key])
            logger.info(
                "Dynamic baselines refreshed: %s",
                {k: _cache[k] for k in _DYNAMIC_KEYS},
            )
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError):
            logger.warning(
                "ClickHouse unreachable for dynamic baselines, keeping current values",
                exc_info=True,
            )

    _cache_ts = now


def get_baselines() -> dict[str, float]:
    """Return current baselines, refreshing from ClickHouse if cache is stale."""
    _refresh()
    return dict(_cache)
