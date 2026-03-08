"""Task definitions and query builders for the ops forensics challenge."""

import json
import random

from helpers import rand_category, rand_doc, rand_str, http_request

INDEX = "challenge-ops"
APP_NAME = "backend-v2"
CULPRIT = "prefetch"


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


def _bool_search(gw, tr):
    return _search(gw, {"query": {"bool": {
        "must": [{"match": {"description": rand_str(6)}}],
        "filter": [{"term": {"category": rand_category()}},
                   {"range": {"price": {"gte": random.randint(1, 100),
                                         "lte": random.randint(200, 999)}}}],
    }}, "size": 25})


def _wildcard_search(gw, tr):
    return _search(gw, {"query": {"bool": {"should": [
        {"wildcard": {"title": {"value": f"*{rand_str(2)}*"}}},
        {"wildcard": {"description": {"value": f"*{rand_str(3)}*"}}},
    ], "minimum_should_match": 1}}, "size": 20})


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


def _match_all(gw, tr):
    return _search(gw, {"query": {"match_all": {}}, "size": 20})


def _combo_search(gw, tr):
    return _search(gw, {
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
        "size": 50})


# ---------------------------------------------------------------------------
# New query builders
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


def _runtime_2_search(gw, tr):
    """2 runtime mappings, no script_score — data-pipeline decoy."""
    return _search(gw, {
        "runtime_mappings": {
            "price_tier": {"type": "keyword", "script": {"source":
                "emit(doc['price'].value > 500 ? 'premium'"
                " : doc['price'].value > 100 ? 'mid' : 'budget')"}},
            "discounted": {"type": "double", "script": {"source":
                "emit(doc['price'].value * 0.85)"}},
        },
        "query": {"match_all": {}},
        "fields": ["price_tier", "discounted"],
        "size": 50})


def _script_fields_2_search(gw, tr):
    """2 script_fields, no script_score — data-pipeline decoy."""
    return _search(gw, {
        "query": {"match_all": {}},
        "script_fields": {
            "tax_price": {"script": {"source": "doc['price'].value * 1.17"}},
            "margin": {"script": {"source":
                "doc['price'].value * 0.3 - doc['quantity'].value * 0.01"}},
        },
        "size": 50})


def _runtime_4_score_search(gw, tr):
    """4 runtime mappings + script_score — culprit heavy query."""
    return _search(gw, {
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
        "query": {"script_score": {"query": {"match_all": {}},
            "script": {"source":
                "Math.log(2 + doc['price'].value) * doc['rating'].value"
                " + doc['quantity'].value * 0.01"}}},
        "fields": ["price_tier", "discounted", "score_label", "qty_flag"],
        "size": 50})


def _script_fields_4_score_search(gw, tr):
    """4 script_fields + script_score — culprit heavy query."""
    return _search(gw, {
        "query": {"script_score": {"query": {"match_all": {}},
            "script": {"source":
                "Math.log(2 + doc['price'].value) * doc['rating'].value"
                " + doc['quantity'].value * 0.01"}}},
        "script_fields": {
            "tax_price": {"script": {"source": "doc['price'].value * 1.17"}},
            "margin": {"script": {"source":
                "doc['price'].value * 0.3 - doc['quantity'].value * 0.01"}},
            "label": {"script": {"source":
                "'[' + doc['category'].value + '] ' + doc['color'].value"}},
            "value_score": {"script": {"source":
                "doc['rating'].value * Math.sqrt(doc['price'].value)"}}},
        "size": 50})


def _ubq_narrow(gw, tr):
    """update_by_query with script, narrow range + max_docs=10."""
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
    """Simple script_score, no script_fields/runtime — price-engine."""
    return _search(gw, {
        "query": {"script_score": {"query": {"match_all": {}},
            "script": {"source":
                "Math.log(2 + doc['price'].value) * doc['rating'].value"}}},
        "size": 50})


# ---------------------------------------------------------------------------
# Warmup targets — every builder that uses Painless
# ---------------------------------------------------------------------------

SCRIPT_BUILDERS = (
    _deep_agg_v2, _runtime_2_search, _script_fields_2_search,
    _runtime_4_score_search, _script_fields_4_score_search,
    _ubq_narrow, _script_score_search, _combo_search,
)


# ---------------------------------------------------------------------------
# Task configurations: (name, workers, think_ms, [(op_fn, weight), ...])
# ---------------------------------------------------------------------------

TASK_CONFIGS = [
    ("sync-external", 2, 150, [
        (lambda gw, tr: _bulk_index(gw, tr, 10, 30), 60),
        (_match_all, 40),
    ]),
    ("daily-digest", 2, 120, [
        (_deep_agg_v2, 50), (_bool_search, 30), (_simple_search, 20),
    ]),
    ("data-pipeline", 2, 150, [
        (_ubq_narrow, 30), (_runtime_2_search, 30),
        (_script_fields_2_search, 30), (_simple_search, 10),
    ]),
    ("catalog-rebuild", 2, 100, [
        (lambda gw, tr: _bulk_index(gw, tr, 20, 50), 60),
        (_single_index, 30), (_match_all, 10),
    ]),
    ("health-check", 2, 200, [
        (_simple_search, 40), (_wildcard_search, 40), (_bool_search, 20),
    ]),
    ("prefetch", 8, 0, [
        (_runtime_4_score_search, 25), (_script_fields_4_score_search, 25),
        (_combo_search, 20), (_simple_search, 15), (_bool_search, 15),
    ]),
    ("price-engine", 2, 200, [
        (_ubq_narrow, 40), (_script_score_search, 40), (_simple_search, 20),
    ]),
    ("compliance-log", 1, 300, [
        (_match_all, 50), (_single_index, 50),
    ]),
]
