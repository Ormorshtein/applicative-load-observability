"""
Dynamic stress baselines from ES percentile aggregations.

When ELASTICSEARCH_URL is set, refreshes took_ms and shards_total from
P50 of recent search traffic every BASELINE_CACHE_TTL seconds (default 60).
Falls back to static defaults when ES is unavailable or has no data.

Supports the same ES connection config as the rest of the stack:
ELASTICSEARCH_URL, ES_USERNAME, ES_PASSWORD, ES_CA_CERT, ES_INSECURE.
"""

import json
import logging
import math
import os
import ssl
import time
import urllib.request
from base64 import b64encode

logger = logging.getLogger(__name__)

_ES_URL = os.environ.get("ELASTICSEARCH_URL")
_ES_USERNAME = os.environ.get("ES_USERNAME", "")
_ES_PASSWORD = os.environ.get("ES_PASSWORD", "")
_ES_CA_CERT = os.environ.get("ES_CA_CERT", "")
_ES_INSECURE = os.environ.get("ES_INSECURE", "").lower() in ("1", "true", "yes")

_CACHE_TTL = float(os.environ.get("BASELINE_CACHE_TTL", "60"))
_QUERY_WINDOW = os.environ.get("BASELINE_QUERY_WINDOW", "1h")

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
    if _ES_INSECURE:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if _ES_CA_CERT:
        return ssl.create_default_context(cafile=_ES_CA_CERT)
    return None


def _build_headers() -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if _ES_USERNAME and _ES_PASSWORD:
        token = b64encode(f"{_ES_USERNAME}:{_ES_PASSWORD}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    return headers


def _fetch_p50() -> dict[str, float]:
    """Query ES for P50 of took_ms and shards_total from recent searches."""
    assert _ES_URL is not None  # caller checks _ES_URL before calling
    body = json.dumps({
        "size": 0,
        "query": {"bool": {"filter": [
            {"range": {"@timestamp": {"gte": f"now-{_QUERY_WINDOW}"}}},
        ]}},
        "aggs": {
            "took_p50": {"percentiles": {
                "field": "response.es_took_ms", "percents": [50],
            }},
            "shards_p50": {"percentiles": {
                "field": "response.shards_total", "percents": [50],
            }},
        },
    }).encode()

    url = f"{_ES_URL.rstrip('/')}/logs-alo.search-*/_search"
    req = urllib.request.Request(url, data=body, headers=_build_headers(), method="POST")

    with urllib.request.urlopen(req, timeout=5, context=_build_ssl_context()) as resp:
        data = json.loads(resp.read())

    aggs = data.get("aggregations", {})
    result: dict[str, float] = {}
    for key, agg_name in (("took_ms", "took_p50"), ("shards_total", "shards_p50")):
        val = aggs.get(agg_name, {}).get("values", {}).get("50.0")
        if val is not None and not math.isnan(val) and val > 0:
            result[key] = val
    return result


def _refresh() -> None:
    """Refresh cache if stale.

    NOTE: no lock — concurrent requests at TTL boundary may all fire
    _fetch_p50().  Acceptable: results are identical and ES handles it.
    """
    global _cache_ts

    now = time.monotonic()
    if now - _cache_ts < _CACHE_TTL:
        return

    if _ES_URL:
        try:
            dynamic = _fetch_p50()
            for key in _DYNAMIC_KEYS:
                _cache[key] = dynamic.get(key, _STATIC[key])
            logger.info(
                "Dynamic baselines refreshed: %s",
                {k: _cache[k] for k in _DYNAMIC_KEYS},
            )
        except Exception:
            logger.warning(
                "ES unreachable for dynamic baselines, keeping current values",
                exc_info=True,
            )

    _cache_ts = now


def get_baselines() -> dict[str, float]:
    """Return current baselines, refreshing from ES if cache is stale."""
    _refresh()
    return dict(_cache)
