"""Config module for challenge v1: detect the stress source among 4 applications.

Four apps hit a shared index simultaneously. Most do normal work; one hides
expensive query patterns (runtime_mappings, script_fields, deep aggs) in its
traffic. Each task name IS an app name — the runner sends the X-App-Name header
via closures bound at definition time.
"""

import json
import random
from types import SimpleNamespace

from helpers import http_request, ndjson, rand_category, rand_doc, rand_str

INDEX = "challenge"
CULPRIT = "analytics-dashboard"
DESCRIPTION = "Challenge: detect the stress source among 4 applications"
HINT = None
CULPRIT_EXPLANATION = (
    "analytics-dashboard mixed runtime_mappings, script_fields, and deep\n"
    "  aggs into ~47% of queries, stacking cost-indicator multipliers up to 2.9x."
)
MISS_EXPLANATION = (
    "The culprit was analytics-dashboard. It mixed runtime_mappings,\n"
    "  script_fields, and deep aggs to stack multipliers up to 2.9x."
)


# ---------------------------------------------------------------------------
# App-bound operation factory — returns (gw, tracker) -> (op, status)
# ---------------------------------------------------------------------------

def _make_app_ops(app_name: str) -> SimpleNamespace:
    """Build operations bound to a specific app_name via closure."""

    def send(gw: str, method: str, path: str, body=None, **kw) -> tuple[int, bytes]:
        return http_request(
            gw, method, path, body, headers={"X-App-Name": app_name}, **kw,
        )

    def search(gw: str, body: dict) -> tuple[str, int]:
        s, _ = send(gw, "POST", f"/{INDEX}/_search", body)
        return "_search", s

    def simple_search(gw: str, _tr) -> tuple[str, int]:
        q = random.choice([
            {"query": {"match": {"title": rand_str(5)}}, "size": 50},
            {"query": {"term": {"category": rand_category()}}, "size": 50},
            {"query": {"range": {"price": {"gte": random.randint(1, 200),
                                            "lte": random.randint(300, 999)}}},
             "size": 50},
            {"query": {"wildcard": {"title": {"value": f"*{rand_str(2)}*"}}},
             "size": 30},
        ])
        return search(gw, q)

    def bool_search(gw: str, _tr) -> tuple[str, int]:
        return search(gw, {"query": {"bool": {
            "must": [{"match": {"description": rand_str(6)}}],
            "filter": [
                {"term": {"category": rand_category()}},
                {"range": {"price": {"gte": random.randint(1, 100),
                                      "lte": random.randint(200, 999)}}},
            ],
        }}, "size": 100})

    def single_index(gw: str, tr) -> tuple[str, int]:
        if not tr.writes_allowed:
            return simple_search(gw, tr)
        doc_id = rand_str(12)
        s, _ = send(gw, "PUT", f"/{INDEX}/_doc/{doc_id}", rand_doc())
        if 200 <= s < 300:
            tr.remember(doc_id)
        return "index", s

    def bulk_index(gw: str, tr, lo: int = 5, hi: int = 20) -> tuple[str, int]:
        if not tr.writes_allowed:
            return simple_search(gw, tr)
        actions: list[str] = []
        for _ in range(random.randint(lo, hi)):
            did = rand_str(12)
            actions.append(json.dumps({"index": {"_index": INDEX, "_id": did}}))
            actions.append(json.dumps(rand_doc()))
            tr.remember(did)
        s, _ = send(
            gw, "POST", "/_bulk", ndjson(actions),
            content_type="application/x-ndjson", timeout=30,
        )
        return "_bulk", s

    def match_all(gw: str, _tr) -> tuple[str, int]:
        return search(gw, {"query": {"match_all": {}}, "size": 50})

    def light_agg(gw: str, _tr) -> tuple[str, int]:
        return search(gw, {"size": 0, "aggs": {"by_cat": {
            "terms": {"field": "category", "size": 10},
            "aggs": {"avg_price": {"avg": {"field": "price"}}}}}})

    def geo_search(gw: str, _tr) -> tuple[str, int]:
        lat = round(random.uniform(30, 45), 4)
        lon = round(random.uniform(-120, -75), 4)
        return search(gw, {"query": {"geo_distance": {
            "distance": f"{random.randint(50, 500)}km",
            "location": {"lat": lat, "lon": lon}}},
            "sort": [{"_geo_distance": {"location": {"lat": lat, "lon": lon},
                                         "order": "asc"}}],
            "size": 100})

    def runtime_mapping_search(gw: str, _tr) -> tuple[str, int]:
        return search(gw, {
            "runtime_mappings": {
                "price_tier": {"type": "keyword", "script": {"source":
                    "emit(doc['price'].value > 500 ? 'premium'"
                    " : doc['price'].value > 100 ? 'mid' : 'budget')"}},
                "discounted": {"type": "double", "script": {"source":
                    "emit(doc['price'].value * 0.85)"}},
                "score_label": {"type": "keyword", "script": {"source":
                    "double s = doc['rating'].value * doc['price'].value;"
                    " emit(s > 1000 ? 'hot' : s > 200 ? 'warm' : 'cold')"}},
                "qty_flag": {"type": "keyword", "script": {"source":
                    "emit(doc['quantity'].value < 10 ? 'low_stock' : 'ok')"}},
            },
            "query": {"match_all": {}},
            "fields": ["price_tier", "discounted", "score_label", "qty_flag"],
            "size": 50,
        })

    def script_fields_search(gw: str, _tr) -> tuple[str, int]:
        return search(gw, {
            "query": {"script_score": {"query": {"match_all": {}},
                "script": {"source":
                    "Math.log(2 + doc['price'].value) * doc['rating'].value"
                    " + doc['quantity'].value * 0.01"}}},
            "script_fields": {
                "tax_price": {"script": {"source":
                    "doc['price'].value * 1.17"}},
                "margin": {"script": {"source":
                    "doc['price'].value * 0.3 - doc['quantity'].value * 0.01"}},
                "label": {"script": {"source":
                    "'[' + doc['category'].value + '] ' + doc['color'].value"}},
                "value_score": {"script": {"source":
                    "doc['rating'].value * Math.sqrt(doc['price'].value)"}}},
            "size": 50,
        })

    def deep_agg_search(gw: str, _tr) -> tuple[str, int]:
        return search(gw, {"size": 0, "aggs": {"by_cat": {
            "terms": {"field": "category", "size": 50}, "aggs": {
                "by_color": {"terms": {"field": "color", "size": 20}, "aggs": {
                    "price_stats": {"stats": {"field": "price"}},
                    "price_hist": {"histogram": {"field": "price",
                                                  "interval": 50}},
                    "rating_pct": {"percentiles": {"field": "rating"}}}},
                "avg_price": {"avg": {"field": "price"}},
                "max_rating": {"max": {"field": "rating"}}}}}})

    def combo_search(gw: str, _tr) -> tuple[str, int]:
        return search(gw, {
            "runtime_mappings": {
                "adjusted": {"type": "double", "script": {"source":
                    "emit(doc['price'].value * (1 + doc['rating'].value / 10))"}},
                "demand": {"type": "keyword", "script": {"source":
                    "emit(doc['quantity'].value > 100 ? 'high' : 'low')"}},
            },
            "query": {"script_score": {"query": {"match_all": {}},
                "script": {"source":
                    "Math.log(2 + doc['price'].value) * doc['rating'].value"}}},
            "script_fields": {
                "profit": {"script": {"source":
                    "doc['price'].value * 0.4 - doc['quantity'].value * 0.02"}},
                "rank": {"script": {"source":
                    "doc['rating'].value * Math.log(1 + doc['price'].value)"}}},
            "fields": ["adjusted", "demand"],
            "size": 50,
        })

    return SimpleNamespace(
        simple_search=simple_search, bool_search=bool_search,
        single_index=single_index, bulk_index=bulk_index,
        match_all=match_all, light_agg=light_agg, geo_search=geo_search,
        runtime_mapping_search=runtime_mapping_search,
        script_fields_search=script_fields_search,
        deep_agg_search=deep_agg_search, combo_search=combo_search,
    )


# ---------------------------------------------------------------------------
# Per-app operation sets
# ---------------------------------------------------------------------------

_catalog = _make_app_ops("catalog-search")
_orders = _make_app_ops("order-ingest")
_analytics = _make_app_ops("analytics-dashboard")
_geo = _make_app_ops("geo-locator")


# ---------------------------------------------------------------------------
# Warmup — every operation that uses Painless scripts
# ---------------------------------------------------------------------------

SCRIPT_BUILDERS = (
    _analytics.runtime_mapping_search,
    _analytics.script_fields_search,
    _analytics.deep_agg_search,
    _analytics.combo_search,
    _geo.geo_search,
)


# ---------------------------------------------------------------------------
# Task configs: (name, workers, think_ms, [(op_fn, weight), ...])
# Each task name is an app name — no single APP_NAME for multi-app challenges.
# ---------------------------------------------------------------------------

TASK_CONFIGS = [
    ("catalog-search", 5, 0, [
        (_catalog.simple_search, 40), (_catalog.bool_search, 25),
        (_catalog.single_index, 20), (_catalog.light_agg, 15),
    ]),
    ("order-ingest", 3, 0, [
        (lambda gw, tr: _orders.bulk_index(gw, tr, 5, 20), 60),
        (_orders.single_index, 25), (_orders.match_all, 15),
    ]),
    ("analytics-dashboard", 5, 0, [
        (_analytics.simple_search, 45), (_analytics.runtime_mapping_search, 15),
        (_analytics.script_fields_search, 12), (_analytics.deep_agg_search, 10),
        (_analytics.combo_search, 10), (_analytics.single_index, 8),
    ]),
    ("geo-locator", 3, 0, [
        (_geo.simple_search, 50), (_geo.geo_search, 20),
        (_geo.single_index, 15), (_geo.bool_search, 15),
    ]),
]
