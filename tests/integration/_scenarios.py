"""
Stress scenario definitions for the observability gateway.

Each scenario pushes ONE specific stress dimension to the extreme.
The @scenario decorator registers classes in the _SCENARIOS registry.
"""

import json
import random

from helpers import (
    LOADTEST_MAPPING,
    http_request,
    rand_category,
    rand_doc,
    rand_str,
)


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

_SCENARIOS: dict[str, type] = {}


def scenario(name: str, description: str):
    def decorator(cls):
        cls.name = name
        cls.description = description
        _SCENARIOS[name] = cls
        return cls
    return decorator


# ---------------------------------------------------------------------------
# Base scenario
# ---------------------------------------------------------------------------

class BaseScenario:
    name: str = "base"
    description: str = "base scenario"

    def __init__(self, gateway: str) -> None:
        self.gateway = gateway
        self.index = f"stress-{self.name}"

    def stress_op(self) -> tuple[str, int]:
        raise NotImplementedError

    def noise_op(self) -> tuple[str, int]:
        ops = [self._noise_match_all, self._noise_single_put, self._noise_term]
        return random.choice(ops)()

    def _noise_match_all(self) -> tuple[str, int]:
        status, _ = http_request(
            self.gateway, "POST", f"/{self.index}/_search",
            {"query": {"match_all": {}}, "size": 5},
            headers={"X-App-Name": f"noise-{self.name}"})
        return "noise:match_all", status

    def _noise_single_put(self) -> tuple[str, int]:
        doc_id = rand_str(12)
        status, _ = http_request(
            self.gateway, "PUT", f"/{self.index}/_doc/{doc_id}",
            rand_doc(),
            headers={"X-App-Name": f"noise-{self.name}"})
        return "noise:put", status

    def _noise_term(self) -> tuple[str, int]:
        status, _ = http_request(
            self.gateway, "POST", f"/{self.index}/_search",
            {"query": {"term": {"category": rand_category()}}, "size": 3},
            headers={"X-App-Name": f"noise-{self.name}"})
        return "noise:term", status

    def stress_headers(self) -> dict[str, str]:
        return {"X-App-Name": f"stress-{self.name}"}

    def ensure_index(self) -> None:
        http_request(self.gateway, "PUT", f"/{self.index}", LOADTEST_MAPPING)

    def seed_data(self, count: int = 500) -> None:
        print(f"  Seeding {count} documents into {self.index} ...", end=" ", flush=True)
        actions = []
        for _ in range(count):
            doc_id = rand_str(12)
            actions.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}))
            actions.append(json.dumps(rand_doc()))
        body = "\n".join(actions) + "\n"
        status, _ = http_request(
            self.gateway, "POST", "/_bulk", body,
            headers={"X-App-Name": f"seed-{self.name}"},
            content_type="application/x-ndjson", timeout=30)
        print(f"done ({status})")
        http_request(self.gateway, "POST", f"/{self.index}/_refresh")

    def delete_index(self) -> None:
        status, _ = http_request(self.gateway, "DELETE", f"/{self.index}")
        print(f"  Deleted index {self.index} ({status})")


# ---------------------------------------------------------------------------
# The 8 scenarios
# ---------------------------------------------------------------------------

@scenario("script-heavy", "Scripts (clause weight=6): 3-4 script_fields + script_score")
class ScriptHeavyScenario(BaseScenario):
    def stress_op(self) -> tuple[str, int]:
        body = {
            "query": {"script_score": {"query": {"match_all": {}},
                       "script": {"source": "doc['price'].value * doc['rating'].value"}}},
            "script_fields": {
                "discount": {"script": {"source": "doc['price'].value * 0.9"}},
                "tax":      {"script": {"source": "doc['price'].value * 1.15"}},
                "label":    {"script": {"source": "'item-' + doc['category'].value"}},
            },
            "size": 5,
        }
        status, _ = http_request(self.gateway, "POST", f"/{self.index}/_search",
                                 body, headers=self.stress_headers())
        return "stress:script_search", status


@scenario("nested-deep", "Nested clauses (clause weight=5): 4-5 nested queries stacked")
class NestedDeepScenario(BaseScenario):
    def stress_op(self) -> tuple[str, int]:
        body = {
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
        }
        status, _ = http_request(self.gateway, "POST", f"/{self.index}/_search",
                                 body, headers=self.stress_headers())
        return "stress:nested_search", status


@scenario("wildcard-swarm", "Wildcards/Regexp/Prefix (clause weight=4): 6-7 clauses")
class WildcardSwarmScenario(BaseScenario):
    def stress_op(self) -> tuple[str, int]:
        body = {
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
        }
        status, _ = http_request(self.gateway, "POST", f"/{self.index}/_search",
                                 body, headers=self.stress_headers())
        return "stress:wildcard_search", status


@scenario("agg-explosion", "Deep aggregations (clause weight=3): 3-level nested aggs")
class AggExplosionScenario(BaseScenario):
    def stress_op(self) -> tuple[str, int]:
        body = {
            "size": 0,
            "aggs": {
                "by_category": {"terms": {"field": "category.keyword", "size": 50}, "aggs": {
                    "by_color": {"terms": {"field": "color.keyword", "size": 20}, "aggs": {
                        "price_stats": {"stats": {"field": "price"}},
                        "rating_hist": {"histogram": {"field": "rating", "interval": 0.5}},
                        "qty_pct": {"percentiles": {"field": "quantity"}}}},
                    "avg_price": {"avg": {"field": "price"}},
                    "max_rating": {"max": {"field": "rating"}},
                    "price_range": {"range": {"field": "price", "ranges": [
                        {"to": 100}, {"from": 100, "to": 500}, {"from": 500}]}}}},
                "global_stats": {"global": {}, "aggs": {
                    "total_avg": {"avg": {"field": "price"}},
                    "total_count": {"value_count": {"field": "price"}}}},
            },
        }
        status, _ = http_request(self.gateway, "POST", f"/{self.index}/_search",
                                 body, headers=self.stress_headers())
        return "stress:agg_search", status


@scenario("runtime-abuse", "Runtime mappings (weight=5) + Scripts (weight=6)")
class RuntimeAbuseScenario(BaseScenario):
    def stress_op(self) -> tuple[str, int]:
        body = {
            "runtime_mappings": {
                "price_bucket": {"type": "keyword",
                    "script": {"source": "emit(doc['price'].value > 100 ? 'expensive' : 'cheap')"}},
                "discounted": {"type": "double",
                    "script": {"source": "emit(doc['price'].value * 0.85)"}},
                "rating_label": {"type": "keyword",
                    "script": {"source": "emit(doc['rating'].value > 4 ? 'top' : 'normal')"}},
            },
            "query": {"match_all": {}},
            "fields": ["price_bucket", "discounted", "rating_label"],
            "size": 10,
        }
        status, _ = http_request(self.gateway, "POST", f"/{self.index}/_search",
                                 body, headers=self.stress_headers())
        return "stress:runtime_search", status


@scenario("geo-complex", "Geo queries: geo_distance + geo_bounding_box")
class GeoComplexScenario(BaseScenario):
    def stress_op(self) -> tuple[str, int]:
        body = {
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
        }
        status, _ = http_request(self.gateway, "POST", f"/{self.index}/_search",
                                 body, headers=self.stress_headers())
        return "stress:geo_search", status


@scenario("bulk-massive", "Bulk write volume: 300-500 docs per _bulk batch")
class BulkMassiveScenario(BaseScenario):
    def stress_op(self) -> tuple[str, int]:
        batch = random.randint(300, 500)
        actions = []
        for _ in range(batch):
            doc_id = rand_str(12)
            actions.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}))
            actions.append(json.dumps(rand_doc()))
        body = "\n".join(actions) + "\n"
        status, _ = http_request(
            self.gateway, "POST", "/_bulk", body,
            headers={**self.stress_headers(), "Content-Type": "application/x-ndjson"},
            content_type="application/x-ndjson", timeout=30)
        return "stress:bulk", status

    def noise_op(self) -> tuple[str, int]:
        if random.random() < 0.5:
            return self._noise_single_put()
        batch = random.randint(2, 3)
        actions = []
        for _ in range(batch):
            doc_id = rand_str(12)
            actions.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}))
            actions.append(json.dumps(rand_doc()))
        body = "\n".join(actions) + "\n"
        status, _ = http_request(
            self.gateway, "POST", "/_bulk", body,
            headers={"X-App-Name": f"noise-{self.name}",
                     "Content-Type": "application/x-ndjson"},
            content_type="application/x-ndjson", timeout=15)
        return "noise:bulk_small", status


@scenario("ubq-carpet-bomb", "Update-by-query with script + wide match on all docs")
class UbqCarpetBombScenario(BaseScenario):
    def stress_op(self) -> tuple[str, int]:
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
        status, _ = http_request(
            self.gateway, "POST",
            f"/{self.index}/_update_by_query?conflicts=proceed",
            body, headers=self.stress_headers())
        return "stress:ubq", status

    def noise_op(self) -> tuple[str, int]:
        if random.random() < 0.5:
            doc_id = rand_str(12)
            http_request(self.gateway, "PUT", f"/{self.index}/_doc/{doc_id}",
                         rand_doc(), headers={"X-App-Name": f"noise-{self.name}"})
            status, _ = http_request(
                self.gateway, "POST", f"/{self.index}/_update/{doc_id}",
                {"doc": {"price": 9.99}},
                headers={"X-App-Name": f"noise-{self.name}"})
            return "noise:update", status
        return self._noise_match_all()
