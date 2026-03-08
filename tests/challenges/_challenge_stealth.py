"""Task definitions and query builders for the stealth challenge.

The culprit uses NO exotic features — no scripts, no runtime_mappings,
no wildcards, no deep aggs. Just complex bool queries with many clauses.
Red herrings dominate every cost-indicator panel.
"""

import json
import random

from helpers import rand_category, rand_color, rand_doc, rand_str, http_request

INDEX = "challenge-stealth"
APP_NAME = "platform-core"
CULPRIT = "recommendation"

_TAGS = ["sale", "new", "popular", "limited", "exclusive", "clearance", "premium"]


# ---------------------------------------------------------------------------
# Shared query helpers
# ---------------------------------------------------------------------------

def _send(gw, method, path, body=None, **kw):
    return http_request(gw, method, path, body,
                        headers={"X-App-Name": APP_NAME}, **kw)


def _search(gw, body):
    s, _ = _send(gw, "POST", f"/{INDEX}/_search", body)
    return "_search", s


def _simple_search(gw, tr):
    q = random.choice([
        {"query": {"match": {"title": rand_str(5)}}, "size": 20},
        {"query": {"term": {"category": rand_category()}}, "size": 20},
        {"query": {"range": {"price": {"gte": random.randint(1, 300),
                                        "lte": random.randint(400, 999)}}}}])
    return _search(gw, q)


def _match_all(gw, tr):
    return _search(gw, {"query": {"match_all": {}}, "size": 20})


def _single_index(gw, tr):
    if not tr.writes_allowed:
        return _simple_search(gw, tr)
    doc_id = rand_str(12)
    s, _ = _send(gw, "PUT", f"/{INDEX}/_doc/{doc_id}", rand_doc())
    if 200 <= s < 300:
        tr.remember(doc_id)
    return "index", s


def _bulk_index(gw, tr, lo=5, hi=15):
    if not tr.writes_allowed:
        return _simple_search(gw, tr)
    actions = []
    for _ in range(random.randint(lo, hi)):
        did = rand_str(12)
        actions.append(json.dumps({"index": {"_index": INDEX, "_id": did}}))
        actions.append(json.dumps(rand_doc()))
        tr.remember(did)
    s, _ = _send(gw, "POST", "/_bulk", "\n".join(actions) + "\n",
                 content_type="application/x-ndjson", timeout=30)
    return "_bulk", s


# ---------------------------------------------------------------------------
# Bool queries at varying clause counts — shared across tasks to dilute signal
# ---------------------------------------------------------------------------

def _light_bool_search(gw, tr):
    """Bool with 2 clauses — used by innocent tasks."""
    return _search(gw, {"query": {"bool": {
        "must": [{"match": {"title": rand_str(5)}}],
        "filter": [{"term": {"category": rand_category()}}],
    }}, "size": 20})


def _medium_bool_search(gw, tr):
    """Bool with 5 clauses — used by red herrings to blend with culprit."""
    return _search(gw, {"query": {"bool": {
        "must": [
            {"match": {"title": rand_str(5)}},
            {"match": {"description": rand_str(6)}},
        ],
        "filter": [
            {"term": {"category": rand_category()}},
            {"range": {"price": {"gte": random.randint(1, 300),
                                  "lte": random.randint(400, 999)}}},
            {"term": {"color": rand_color()}},
        ],
    }}, "size": 50})


# ---------------------------------------------------------------------------
# Red herring builders — flashy cost indicators, moderate actual load
# ---------------------------------------------------------------------------

def _deep_agg_v2(gw, tr):
    """3-level aggregation with 11 agg clauses — triggers deep_aggs."""
    return _search(gw, {"size": 0, "aggs": {
        "by_cat": {
            "terms": {"field": "category", "size": 50},
            "aggs": {
                "by_color": {
                    "terms": {"field": "color", "size": 20},
                    "aggs": {
                        "price_stats": {"stats": {"field": "price"}},
                        "qty_pct": {"percentiles": {"field": "quantity"}},
                        "rating_hist": {"histogram":
                                        {"field": "rating", "interval": 1}},
                    },
                },
                "avg_price": {"avg": {"field": "price"}},
                "max_rating": {"max": {"field": "rating"}},
            },
        },
        "global_stats": {
            "global": {},
            "aggs": {
                "total_avg": {"avg": {"field": "price"}},
                "total_count": {"value_count": {"field": "price"}},
            },
        },
        "price_range": {
            "range": {"field": "price",
                      "ranges": [{"to": 100}, {"from": 100, "to": 500},
                                 {"from": 500}]},
        },
    }})


def _wildcard_search(gw, tr):
    """Wildcard on text fields — triggers has_wildcard."""
    return _search(gw, {"query": {"bool": {"should": [
        {"wildcard": {"title": {"value": f"*{rand_str(2)}*"}}},
        {"wildcard": {"description": {"value": f"*{rand_str(3)}*"}}},
    ], "minimum_should_match": 1}}, "size": 20})


def _ubq_narrow(gw, tr):
    """update_by_query with script — triggers has_script."""
    lo = random.randint(100, 900)
    body = {
        "query": {"range": {"price": {"gte": lo, "lt": lo + 5}}},
        "script": {
            "source": "ctx._source.quantity += params.v",
            "params": {"v": random.randint(1, 5)},
        },
        "max_docs": 10,
    }
    s, _ = _send(gw, "POST",
                 f"/{INDEX}/_update_by_query?conflicts=proceed", body)
    return "_update_by_query", s


def _script_score_search(gw, tr):
    """script_score search — triggers has_script."""
    return _search(gw, {
        "query": {"script_score": {"query": {"match_all": {}},
            "script": {"source":
                "Math.log(2 + doc['price'].value) * doc['rating'].value"}}},
        "size": 50})


# ---------------------------------------------------------------------------
# Culprit builders — high clause count, ZERO cost indicators
#
# These are just bool queries with many match/term/range clauses.
# No scripts, no wildcards, no runtime_mappings, no deep aggs.
# The stress multiplier is always 1.0 — invisible in cost indicator panels.
# But the queries are genuinely expensive for ES due to clause evaluation.
# ---------------------------------------------------------------------------

def _fat_bool_search(gw, tr):
    """Bool with 10 clauses across must/filter/should."""
    return _search(gw, {"query": {"bool": {
        "must": [
            {"match": {"title": rand_str(5)}},
            {"match": {"description": rand_str(6)}},
            {"match_phrase": {"description":
                              rand_str(4) + " " + rand_str(4)}},
        ],
        "filter": [
            {"term": {"category": rand_category()}},
            {"term": {"color": rand_color()}},
            {"range": {"price": {"gte": random.randint(1, 200),
                                  "lte": random.randint(300, 999)}}},
            {"range": {"rating": {"gte": round(random.uniform(1, 3), 1),
                                   "lte": round(random.uniform(3.5, 5), 1)}}},
        ],
        "should": [
            {"match": {"title": rand_str(4)}},
            {"term": {"tags": random.choice(_TAGS)}},
            {"range": {"quantity": {"gte": random.randint(0, 100),
                                     "lte": random.randint(200, 500)}}},
        ],
        "minimum_should_match": 1,
    }}, "size": 100})


def _nested_bool_search(gw, tr):
    """Nested bool-in-bool, 9 leaf clauses total."""
    return _search(gw, {"query": {"bool": {
        "must": [
            {"bool": {
                "should": [
                    {"match": {"title": rand_str(5)}},
                    {"match": {"description": rand_str(6)}},
                    {"match_phrase": {"title":
                                      rand_str(3) + " " + rand_str(3)}},
                ],
                "minimum_should_match": 1,
            }},
            {"bool": {
                "must": [
                    {"range": {"price": {"gte": random.randint(50, 300),
                                          "lte": random.randint(400, 999)}}},
                    {"term": {"category": rand_category()}},
                ],
                "should": [
                    {"term": {"color": rand_color()}},
                    {"range": {"rating": {
                        "gte": round(random.uniform(2, 3.5), 1)}}},
                ],
            }},
        ],
        "filter": [
            {"range": {"quantity": {"gte": random.randint(10, 50),
                                     "lte": random.randint(100, 500)}}},
            {"term": {"tags": random.choice(_TAGS)}},
        ],
    }}, "size": 100})


def _multi_match_search(gw, tr):
    """multi_match across fields + 5 filters = 7 clauses."""
    return _search(gw, {"query": {"bool": {
        "must": [
            {"multi_match": {
                "query": rand_str(5) + " " + rand_str(4),
                "fields": ["title^2", "description"],
                "type": "best_fields",
            }},
            {"match": {"description": rand_str(6)}},
        ],
        "filter": [
            {"term": {"category": rand_category()}},
            {"term": {"color": rand_color()}},
            {"range": {"price": {"gte": random.randint(1, 200),
                                  "lte": random.randint(300, 999)}}},
            {"range": {"rating": {"gte": round(random.uniform(1, 3), 1),
                                   "lte": round(random.uniform(3.5, 5), 1)}}},
            {"term": {"tags": random.choice(_TAGS)}},
        ],
    }}, "size": 100})


# ---------------------------------------------------------------------------
# Warmup targets — only red herring scripts need compilation
# ---------------------------------------------------------------------------

SCRIPT_BUILDERS = (_ubq_narrow, _script_score_search)


# ---------------------------------------------------------------------------
# Task configurations: (name, workers, think_ms, [(op_fn, weight), ...])
#
# CPU profile:
#   All 8 running: ~80-85%
#   After stopping recommendation: ~35-40% (the real drop)
#   Stopping any red herring: ~5-8% drop each (convincing but not enough)
#
# Why it's hard:
#   1. Cost indicator panels point to etl-worker, search-ranker, report-builder
#   2. Culprit triggers ZERO cost indicators — invisible in that panel
#   3. Per-request stress is lower than red herring templates (no multiplier)
#   4. Multiple tasks use bool queries (light/medium), diluting the pattern
#   5. inventory-sync has similar volume to the culprit (both ~30 req/s)
#   6. Culprit's stress is split across 3 different templates
# ---------------------------------------------------------------------------

TASK_CONFIGS = [
    ("auth-service", 2, 150, [
        (_simple_search, 50), (_light_bool_search, 30), (_match_all, 20),
    ]),
    ("report-builder", 3, 80, [
        (_deep_agg_v2, 45), (_medium_bool_search, 35), (_simple_search, 20),
    ]),
    ("etl-worker", 3, 100, [
        (_ubq_narrow, 40), (_script_score_search, 30), (_simple_search, 30),
    ]),
    ("inventory-sync", 3, 30, [
        (lambda gw, tr: _bulk_index(gw, tr, 10, 30), 55),
        (_single_index, 30), (_match_all, 15),
    ]),
    ("search-ranker", 3, 100, [
        (_wildcard_search, 40), (_medium_bool_search, 35),
        (_simple_search, 25),
    ]),
    ("recommendation", 3, 25, [
        (_fat_bool_search, 35), (_nested_bool_search, 30),
        (_multi_match_search, 20), (_simple_search, 15),
    ]),
    ("cache-refresh", 2, 150, [
        (_match_all, 50), (_simple_search, 30), (_light_bool_search, 20),
    ]),
    ("metrics-collector", 1, 250, [
        (_simple_search, 50), (_single_index, 50),
    ]),
]
