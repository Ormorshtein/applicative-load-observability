"""Shared noise task definitions for trivial load challenges.

Call ``make_noise(index, app_name)`` to get a namespace of operation
functions bound to a specific index and application name.  Every function
follows the ``(gw, tracker) -> (op_name, status)`` signature expected by
the task config system.
"""

import json
import random
import types

from helpers import (
    http_request, rand_category, rand_color, rand_doc, rand_str,
)


def make_noise(index, app_name):
    """Return a namespace of noise operation functions for *index*."""

    def send(gw, method, path, body=None, **kw):
        return http_request(gw, method, path, body,
                            headers={"X-App-Name": app_name}, **kw)

    def search(gw, body):
        s, _ = send(gw, "POST", f"/{index}/_search", body)
        return "_search", s

    # -- read operations ---------------------------------------------------

    def simple_search(gw, tr):
        q = random.choice([
            {"query": {"match": {"title": rand_str(5)}}, "size": 20},
            {"query": {"term": {"category": rand_category()}}, "size": 20},
            {"query": {"range": {"price": {"gte": random.randint(1, 300),
                                            "lte": random.randint(400, 999)}}},
             "size": 20}])
        return search(gw, q)

    def match_all(gw, tr):
        return search(gw, {"query": {"match_all": {}}, "size": 20})

    def light_bool(gw, tr):
        return search(gw, {"query": {"bool": {
            "must": [{"match": {"title": rand_str(5)}}],
            "filter": [
                {"term": {"category": rand_category()}},
                {"range": {"price": {"gte": random.randint(1, 300),
                                      "lte": random.randint(400, 999)}}},
            ],
        }}, "size": 25})

    def light_agg(gw, tr):
        """2-3 aggregations — well below the deep_aggs threshold of 10."""
        return search(gw, {"size": 0, "aggs": {
            "avg_price": {"avg": {"field": "price"}},
            "by_cat": {"terms": {"field": "category", "size": 10}},
            "price_range": {"range": {"field": "price",
                                       "ranges": [{"to": 100},
                                                   {"from": 100, "to": 500},
                                                   {"from": 500}]}},
        }})

    def light_geo(gw, tr):
        """Tight-radius geo_distance (5-20km) — minimal result set."""
        lat = round(random.uniform(33.0, 42.0), 4)
        lon = round(random.uniform(-118.0, -74.0), 4)
        return search(gw, {"query": {"bool": {
            "filter": [{"geo_distance": {
                "distance": f"{random.randint(5, 20)}km",
                "location": {"lat": lat, "lon": lon},
            }}],
        }}, "size": 20})

    def geo_bbox(gw, tr):
        """geo_bounding_box filter — distinct template from geo_distance."""
        lat = round(random.uniform(34.0, 41.0), 4)
        lon = round(random.uniform(-117.0, -75.0), 4)
        return search(gw, {"query": {"bool": {
            "filter": [{"geo_bounding_box": {
                "location": {
                    "top_left": {"lat": lat + 0.5, "lon": lon - 0.5},
                    "bottom_right": {"lat": lat - 0.5, "lon": lon + 0.5},
                },
            }}],
        }}, "size": 20})

    def geo_cat_filter(gw, tr):
        """geo_distance + category filter — distinct combined template."""
        lat = round(random.uniform(33.0, 42.0), 4)
        lon = round(random.uniform(-118.0, -74.0), 4)
        return search(gw, {"query": {"bool": {
            "filter": [
                {"geo_distance": {
                    "distance": f"{random.randint(5, 20)}km",
                    "location": {"lat": lat, "lon": lon},
                }},
                {"term": {"category": rand_category()}},
            ],
        }}, "size": 20})

    def geo_sort_small(gw, tr):
        """geo_distance sort with small fetch — distinct from bare geo."""
        lat = round(random.uniform(33.0, 42.0), 4)
        lon = round(random.uniform(-118.0, -74.0), 4)
        return search(gw, {"query": {"bool": {
            "filter": [{"geo_distance": {
                "distance": f"{random.randint(10, 30)}km",
                "location": {"lat": lat, "lon": lon},
            }}],
        }}, "sort": [{"_geo_distance": {
            "location": {"lat": lat, "lon": lon},
            "order": "asc", "unit": "km",
        }}], "size": 10})

    # -- write operations --------------------------------------------------

    def single_index(gw, tr):
        doc_id = tr.pick() if not tr.writes_allowed else rand_str(12)
        s, _ = send(gw, "PUT", f"/{index}/_doc/{doc_id}", rand_doc())
        if 200 <= s < 300 and tr.writes_allowed:
            tr.remember(doc_id)
        return "index", s

    def bulk_index(gw, tr, lo=5, hi=15):
        capped = not tr.writes_allowed
        actions = []
        for _ in range(random.randint(lo, hi)):
            did = tr.pick() if capped else rand_str(12)
            if did is None:
                did = rand_str(12)
            actions.append(json.dumps({"index": {"_index": index, "_id": did}}))
            actions.append(json.dumps(rand_doc()))
            if not capped:
                tr.remember(did)
        s, _ = send(gw, "POST", "/_bulk", "\n".join(actions) + "\n",
                     content_type="application/x-ndjson", timeout=30)
        return "_bulk", s

    return types.SimpleNamespace(
        send=send,
        search=search,
        simple_search=simple_search,
        match_all=match_all,
        light_bool=light_bool,
        light_agg=light_agg,
        light_geo=light_geo,
        geo_bbox=geo_bbox,
        geo_cat_filter=geo_cat_filter,
        geo_sort_small=geo_sort_small,
        single_index=single_index,
        bulk_index=bulk_index,
    )
