"""Single-dimension stress workload profiles.

Each profile hammers ONE specific ES stress dimension as hard as possible.
Each profile targets a specific clause type or volume pattern.
"""

import json
import random

from _helpers import http_request, rand_doc, rand_str
from _workloads import Workload, workload


# ---------------------------------------------------------------------------
# Script-heavy
# ---------------------------------------------------------------------------

@workload("script", "Script-heavy: script_fields + script_score (clause weight 6)")
class ScriptStress(Workload):
    def weighted_operations(self):
        return [(self._op, 1)]

    def _op(self):
        return self._post_search({
            "query": {"script_score": {
                "query": {"match_all": {}},
                "script": {"source": "doc['price'].value * doc['rating'].value"}}},
            "script_fields": {
                "discount": {"script": {"source": "doc['price'].value * 0.9"}},
                "tax":      {"script": {"source": "doc['price'].value * 1.15"}},
                "label":    {"script": {"source": "'item-' + doc['category'].value"}},
            },
            "size": 5,
        })


# ---------------------------------------------------------------------------
# Nested-deep
# ---------------------------------------------------------------------------

@workload("nested", "Nested clauses: 4-5 stacked nested queries (clause weight 5)")
class NestedStress(Workload):
    def weighted_operations(self):
        return [(self._op, 1)]

    def _op(self):
        return self._post_search({
            "query": {"bool": {"must": [
                {"nested": {"path": "comments", "query": {"bool": {"must": [
                    {"nested": {"path": "comments.replies", "query": {
                        "nested": {"path": "comments.replies.reactions",
                                   "query": {"match_all": {}}}}}},
                    {"match": {"title": "test"}}]}}}},
                {"nested": {"path": "tags", "query": {"term": {"category": "sale"}}}},
                {"nested": {"path": "meta", "query": {"match_all": {}}}},
            ]}},
            "size": 5,
        })


# ---------------------------------------------------------------------------
# Wildcard swarm
# ---------------------------------------------------------------------------

@workload("wildcard", "Wildcard/regexp/prefix swarm: 6-7 clauses (clause weight 4)")
class WildcardStress(Workload):
    def weighted_operations(self):
        return [(self._op, 1)]

    def _op(self):
        return self._post_search({
            "query": {"bool": {"should": [
                {"wildcard": {"title": {"value": "*a*b*"}}},
                {"wildcard": {"description": {"value": "?e*t*"}}},
                {"regexp": {"category": {"value": "elec.*"}}},
                {"prefix": {"color": {"value": "b"}}},
                {"wildcard": {"tags": {"value": "*le"}}},
                {"regexp": {"title": {"value": "[a-z]{3,}.*ing"}}},
                {"prefix": {"description": {"value": "the"}}},
            ], "minimum_should_match": 1}},
            "size": 5,
        })


# ---------------------------------------------------------------------------
# Aggregation explosion
# ---------------------------------------------------------------------------

@workload("agg", "Deep aggregations: 3-level nested aggs (clause weight 3)")
class AggStress(Workload):
    def weighted_operations(self):
        return [(self._op, 1)]

    def _op(self):
        return self._post_search({
            "size": 0,
            "aggs": {
                "by_cat": {"terms": {"field": "category.keyword", "size": 50}, "aggs": {
                    "by_color": {"terms": {"field": "color.keyword", "size": 20}, "aggs": {
                        "price_stats": {"stats": {"field": "price"}},
                        "rating_hist": {"histogram": {"field": "rating",
                                                      "interval": 0.5}},
                        "qty_pct": {"percentiles": {"field": "quantity"}}}},
                    "avg_price": {"avg": {"field": "price"}},
                    "max_rating": {"max": {"field": "rating"}},
                    "price_range": {"range": {"field": "price", "ranges": [
                        {"to": 100}, {"from": 100, "to": 500}, {"from": 500}]}}}},
                "global_stats": {"global": {}, "aggs": {
                    "total_avg": {"avg": {"field": "price"}},
                    "total_count": {"value_count": {"field": "price"}}}},
            },
        })


# ---------------------------------------------------------------------------
# Runtime mappings abuse
# ---------------------------------------------------------------------------

@workload("runtime", "Runtime mappings + scripts (clause weight 5+6)")
class RuntimeStress(Workload):
    def weighted_operations(self):
        return [(self._op, 1)]

    def _op(self):
        return self._post_search({
            "runtime_mappings": {
                "price_bucket": {"type": "keyword",
                    "script": {"source":
                        "emit(doc['price'].value > 100 ? 'expensive' : 'cheap')"}},
                "discounted": {"type": "double",
                    "script": {"source": "emit(doc['price'].value * 0.85)"}},
                "rating_label": {"type": "keyword",
                    "script": {"source":
                        "emit(doc['rating'].value > 4 ? 'top' : 'normal')"}},
            },
            "query": {"match_all": {}},
            "fields": ["price_bucket", "discounted", "rating_label"],
            "size": 10,
        })


# ---------------------------------------------------------------------------
# Geo-complex
# ---------------------------------------------------------------------------

@workload("geo", "Geo queries: geo_distance + geo_bounding_box")
class GeoStress(Workload):
    def weighted_operations(self):
        return [(self._op, 1)]

    def _op(self):
        return self._post_search({
            "query": {"bool": {"must": [
                {"geo_distance": {"distance": "50km",
                    "location": {"lat": 40.0, "lon": -100.0}}},
                {"geo_distance": {"distance": "100km",
                    "location": {"lat": 35.0, "lon": -90.0}}},
            ], "filter": [
                {"geo_bounding_box": {"location": {
                    "top_left": {"lat": 48, "lon": -125},
                    "bottom_right": {"lat": 25, "lon": -65}}}},
                {"geo_bounding_box": {"location": {
                    "top_left": {"lat": 42, "lon": -110},
                    "bottom_right": {"lat": 35, "lon": -90}}}},
            ]}},
            "size": 10,
        })


# ---------------------------------------------------------------------------
# Bulk massive
# ---------------------------------------------------------------------------

@workload("bulk", "Bulk write flood: 300-500 docs per _bulk batch")
class BulkStress(Workload):
    def weighted_operations(self):
        return [(self._op, 1)]

    def _op(self):
        batch = random.randint(300, 500)
        actions = []
        for _ in range(batch):
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


# ---------------------------------------------------------------------------
# Update-by-query carpet bomb
# ---------------------------------------------------------------------------

@workload("ubq", "Update-by-query carpet bomb: script + match_all on all docs")
class UbqStress(Workload):
    def weighted_operations(self):
        return [(self._op, 1)]

    def _op(self):
        body = {
            "query": {"bool": {"must": [
                {"wildcard": {"title": {"value": "*"}}},
                {"wildcard": {"description": {"value": "*"}}},
            ], "should": [
                {"fuzzy": {"category": {"value": "elctroncs", "fuzziness": "AUTO"}}},
            ]}},
            "script": {
                "source": "ctx._source.quantity = ctx._source.quantity + params.v",
                "params": {"v": 1},
            },
        }
        s, resp = http_request(
            self.gateway, "POST",
            f"/{self.index}/_update_by_query?conflicts=proceed",
            body, headers=self._h())
        return "_update_by_query", s, resp
