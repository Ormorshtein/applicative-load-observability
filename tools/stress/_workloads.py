"""Workload profiles — composite operation mixes for the stress engine."""

import json
import random

from _engine import DocIdTracker
from _helpers import (
    http_request,
    rand_category,
    rand_color,
    rand_doc,
    rand_int,
    rand_price,
    rand_str,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

WORKLOADS: dict[str, type] = {}


def workload(name: str, description: str):
    """Class decorator that registers a workload profile."""
    def decorator(cls):
        cls.name = name
        cls.description = description
        WORKLOADS[name] = cls
        return cls
    return decorator


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Workload:
    """Base workload — gateway context, HTTP helpers, doc tracker."""

    name: str = ""
    description: str = ""

    def __init__(self, gateway: str, index: str, app_name: str) -> None:
        self.gateway = gateway
        self.index = index
        self.app_name = app_name
        self.tracker = DocIdTracker()

    def weighted_operations(self) -> list[tuple]:
        raise NotImplementedError

    def _h(self) -> dict:
        """Default headers with X-App-Name."""
        return {"X-App-Name": self.app_name}

    def _post_search(self, body) -> tuple[str, int, bytes]:
        s, resp = http_request(self.gateway, "POST", f"/{self.index}/_search",
                               body, headers=self._h())
        return "_search", s, resp


class SingleOpWorkload(Workload):
    """Workload that runs a single operation — subclass and define ``_op``."""

    def weighted_operations(self) -> list[tuple]:
        return [(self._op, 1)]

    def _op(self) -> tuple[str, int, bytes]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Mixed workload — realistic production traffic
# ---------------------------------------------------------------------------

@workload("mixed", "Balanced mix of search, write, and admin operations")
class MixedWorkload(Workload):

    def weighted_operations(self):
        return [
            (self._simple_search,     20), (self._bool_search,    15),
            (self._agg_search,        10), (self._wildcard_search, 5),
            (self._nested_search,      5), (self._geo_search,      3),
            (self._script_search,      2), (self._index,          15),
            (self._create,             5), (self._bulk,            8),
            (self._update,             5), (self._ubq,             2),
            (self._delete,             3), (self._dbq,             2),
        ]

    # ---- searches ----

    def _simple_search(self):
        return self._post_search(random.choice([
            {"query": {"match_all": {}}, "size": random.choice([10, 20, 50, 100])},
            {"query": {"match": {"title": rand_str(5)}}, "size": 10},
            {"query": {"term": {"category": rand_category()}}, "size": 20},
            {"query": {"range": {"price": {"gte": rand_int(1, 200),
                                           "lte": rand_int(300, 999)}}}, "size": 15},
        ]))

    def _bool_search(self):
        return self._post_search({
            "query": {"bool": {
                "must": [{"match": {"description": rand_str(6)}}],
                "filter": [{"term": {"category": rand_category()}},
                           {"range": {"price": {"gte": rand_int(1, 100),
                                                "lte": rand_int(200, 999)}}}],
                "should": [{"term": {"color": rand_color()}}],
            }},
            "size": random.choice([10, 25, 50]),
            "sort": [{"price": "asc"}],
        })

    def _agg_search(self):
        return self._post_search({
            "size": 0,
            "aggs": {
                "by_cat": {"terms": {"field": "category.keyword", "size": 10}, "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "ranges": {"range": {"field": "price",
                               "ranges": [{"to": 50}, {"from": 50, "to": 200},
                                          {"from": 200}]}},
                }},
                "stats": {"stats": {"field": "price"}},
            },
        })

    def _wildcard_search(self):
        return self._post_search(random.choice([
            {"query": {"wildcard": {"title": {"value": f"{rand_str(2)}*{rand_str(1)}"}}},
             "size": 10},
            {"query": {"fuzzy": {"title": {"value": rand_str(5), "fuzziness": "AUTO"}}},
             "size": 10},
        ]))

    def _nested_search(self):
        return self._post_search({
            "query": {"bool": {
                "must": [
                    {"bool": {"should": [
                        {"match": {"title": rand_str(4)}},
                        {"match": {"description": rand_str(6)}},
                    ]}},
                    {"terms": {"color": random.sample(
                        ["red", "blue", "green", "black", "white"], k=3)}},
                ],
                "must_not": [{"range": {"quantity": {"lt": 1}}}],
            }},
            "size": random.choice([10, 20]),
        })

    def _geo_search(self):
        return self._post_search({
            "query": {"geo_distance": {
                "distance": f"{random.randint(10, 500)}km",
                "location": {"lat": round(random.uniform(30, 45), 4),
                             "lon": round(random.uniform(-120, -75), 4)},
            }},
            "size": 20,
            "sort": [{"_geo_distance": {"location": {"lat": 40.0, "lon": -100.0},
                                         "order": "asc", "unit": "km"}}],
        })

    def _script_search(self):
        return self._post_search({
            "query": {"match_all": {}}, "size": 10,
            "script_fields": {
                "discounted": {"script": {"source": "doc['price'].value * 0.9"}}},
        })

    # ---- writes ----

    def _index(self):
        doc_id = rand_str(12)
        s, body = http_request(self.gateway, "PUT",
                               f"/{self.index}/_doc/{doc_id}",
                               rand_doc(), headers=self._h())
        if 200 <= s < 300:
            self.tracker.remember(doc_id)
        return "index", s, body

    def _create(self):
        doc_id = rand_str(12)
        s, body = http_request(self.gateway, "PUT",
                               f"/{self.index}/_create/{doc_id}",
                               rand_doc(), headers=self._h())
        if 200 <= s < 300:
            self.tracker.remember(doc_id)
        return "_create", s, body

    def _bulk(self):
        actions = []
        for _ in range(random.randint(5, 50)):
            doc_id = rand_str(12)
            actions.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}))
            actions.append(json.dumps(rand_doc()))
            self.tracker.remember(doc_id)
        body = "\n".join(actions) + "\n"
        s, resp = http_request(
            self.gateway, "POST", "/_bulk", body,
            headers={**self._h(), "Content-Type": "application/x-ndjson"},
            content_type="application/x-ndjson", timeout=30)
        return "_bulk", s, resp

    def _update(self):
        doc_id = self.tracker.pick()
        if not doc_id:
            return self._index()
        payload = {"doc": {"price": rand_price(), "quantity": rand_int(0, 500)}}
        s, body = http_request(self.gateway, "POST",
                               f"/{self.index}/_update/{doc_id}",
                               payload, headers=self._h())
        return "_update", s, body

    def _ubq(self):
        body = {
            "query": {"term": {"category": rand_category()}},
            "script": {"source": "ctx._source.quantity += params.n",
                       "params": {"n": random.randint(1, 10)}},
        }
        s, resp = http_request(
            self.gateway, "POST",
            f"/{self.index}/_update_by_query?conflicts=proceed",
            body, headers=self._h())
        return "_update_by_query", s, resp

    def _delete(self):
        doc_id = self.tracker.pick()
        if not doc_id:
            return self._index()
        s, body = http_request(self.gateway, "DELETE",
                               f"/{self.index}/_doc/{doc_id}",
                               headers=self._h())
        return "delete", s, body

    def _dbq(self):
        body = {"query": {"range": {"price": {"lt": rand_int(1, 20)}}}}
        s, resp = http_request(
            self.gateway, "POST",
            f"/{self.index}/_delete_by_query?conflicts=proceed",
            body, headers=self._h())
        return "_delete_by_query", s, resp


# ---------------------------------------------------------------------------
# Filtered workloads — reuse MixedWorkload operations with different weights
# ---------------------------------------------------------------------------

@workload("search", "Search-only traffic — all search variants")
class SearchWorkload(MixedWorkload):
    def weighted_operations(self):
        return [
            (self._simple_search,     25), (self._bool_search,       20),
            (self._agg_search,        15), (self._wildcard_search,   10),
            (self._nested_search,     10), (self._geo_search,        10),
            (self._script_search,     10),
        ]


@workload("write", "Write-only traffic — index, bulk, update, delete")
class WriteWorkload(MixedWorkload):
    def weighted_operations(self):
        return [
            (self._index,    25), (self._create,   10), (self._bulk,   25),
            (self._update,   15), (self._ubq,       5), (self._delete, 15),
            (self._dbq,       5),
        ]
