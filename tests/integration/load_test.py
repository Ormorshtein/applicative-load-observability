#!/usr/bin/env python3
"""
Load-test script for the applicative-load-observability gateway.

Sends a variety of Elasticsearch operations (index, bulk, search, update,
delete, update_by_query, delete_by_query) through the gateway on port 9200,
which proxies them to ES while capturing observability data.

Usage:
    python tests/load_test.py                      # defaults: 60s, 10 workers
    python tests/load_test.py --duration 120 --workers 20
    python tests/load_test.py --gateway http://my-host:9200
"""

import argparse
import json
import os
import random
import sys
import threading
import time

from helpers import (
    Stats,
    LOADTEST_MAPPING,
    http_request,
    rand_doc,
    rand_category,
    rand_color,
    rand_int,
    rand_price,
    rand_str,
)

INDEX = "loadtest"

_DEFAULT_GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:9200")
_DEFAULT_DURATION = 60
_DEFAULT_WORKERS = 10


# ---------------------------------------------------------------------------
# Document ID tracker (thread-safe)
# ---------------------------------------------------------------------------

class DocIdTracker:
    def __init__(self, max_size: int = 5000) -> None:
        self._ids: list[str] = []
        self._lock = threading.Lock()
        self._max_size = max_size

    def remember(self, doc_id: str) -> None:
        with self._lock:
            self._ids.append(doc_id)
            if len(self._ids) > self._max_size:
                self._ids[:] = self._ids[-2000:]

    def pick(self) -> str | None:
        with self._lock:
            return random.choice(self._ids) if self._ids else None


# ---------------------------------------------------------------------------
# Operation generators
# ---------------------------------------------------------------------------

class OperationMix:
    def __init__(self, gateway: str) -> None:
        self.gateway = gateway
        self.tracker = DocIdTracker()

    def _http(self, method: str, path: str, body=None,
              headers: dict | None = None) -> tuple[int, bytes]:
        hdrs = {
            "Content-Type": "application/json",
            "User-Agent": f"load-test/{random.choice(['search-svc', 'ingest-svc', 'admin-cli', 'dashboard'])}",
        }
        if random.random() < 0.3:
            hdrs["X-App-Name"] = random.choice(["search-api", "catalog-sync",
                                                 "analytics", "reindex-job"])
        if headers:
            hdrs.update(headers)
        return http_request(self.gateway, method, path, body, headers=hdrs)

    def op_index(self) -> tuple[str, int]:
        doc_id = rand_str(12)
        status, _ = self._http("PUT", f"/{INDEX}/_doc/{doc_id}", rand_doc())
        if 200 <= status < 300:
            self.tracker.remember(doc_id)
        return "index", status

    def op_create(self) -> tuple[str, int]:
        doc_id = rand_str(12)
        status, _ = self._http("PUT", f"/{INDEX}/_create/{doc_id}", rand_doc())
        if 200 <= status < 300:
            self.tracker.remember(doc_id)
        return "_create", status

    def op_bulk(self) -> tuple[str, int]:
        actions = []
        batch = random.randint(5, 50)
        for _ in range(batch):
            doc_id = rand_str(12)
            actions.append(json.dumps({"index": {"_index": INDEX, "_id": doc_id}}))
            actions.append(json.dumps(rand_doc()))
            self.tracker.remember(doc_id)
        body = "\n".join(actions) + "\n"
        status, _ = http_request(
            self.gateway, "POST", "/_bulk", body,
            headers={"Content-Type": "application/x-ndjson",
                     "User-Agent": "load-test/ingest-svc"},
            content_type="application/x-ndjson", timeout=30)
        return "_bulk", status

    def op_search_simple(self) -> tuple[str, int]:
        queries = [
            {"query": {"match_all": {}}, "size": random.choice([10, 20, 50, 100])},
            {"query": {"match": {"title": rand_str(5)}}, "size": 10},
            {"query": {"term": {"category": rand_category()}}, "size": 20},
            {"query": {"range": {"price": {"gte": rand_int(1, 200), "lte": rand_int(300, 999)}}}, "size": 15},
        ]
        status, _ = self._http("POST", f"/{INDEX}/_search", random.choice(queries))
        return "_search", status

    def op_search_bool(self) -> tuple[str, int]:
        q = {
            "query": {
                "bool": {
                    "must": [{"match": {"description": rand_str(6)}}],
                    "filter": [
                        {"term": {"category": rand_category()}},
                        {"range": {"price": {"gte": rand_int(1, 100), "lte": rand_int(200, 999)}}},
                    ],
                    "should": [{"term": {"color": rand_color()}}],
                }
            },
            "size": random.choice([10, 25, 50]),
            "sort": [{"price": "asc"}],
        }
        status, _ = self._http("POST", f"/{INDEX}/_search", q)
        return "_search", status

    def op_search_agg(self) -> tuple[str, int]:
        q = {
            "size": 0,
            "aggs": {
                "by_category": {
                    "terms": {"field": "category.keyword", "size": 10},
                    "aggs": {
                        "avg_price": {"avg": {"field": "price"}},
                        "price_ranges": {
                            "range": {
                                "field": "price",
                                "ranges": [{"to": 50}, {"from": 50, "to": 200}, {"from": 200}],
                            }
                        },
                    },
                },
                "price_stats": {"stats": {"field": "price"}},
            },
        }
        status, _ = self._http("POST", f"/{INDEX}/_search", q)
        return "_search", status

    def op_search_wildcard(self) -> tuple[str, int]:
        variants = [
            {"query": {"wildcard": {"title": {"value": f"{rand_str(2)}*{rand_str(1)}"}}}},
            {"query": {"fuzzy": {"title": {"value": rand_str(5), "fuzziness": "AUTO"}}}},
        ]
        q = random.choice(variants)
        q["size"] = 10
        status, _ = self._http("POST", f"/{INDEX}/_search", q)
        return "_search", status

    def op_search_nested_bool(self) -> tuple[str, int]:
        q = {
            "query": {
                "bool": {
                    "must": [
                        {"bool": {"should": [
                            {"match": {"title": rand_str(4)}},
                            {"match": {"description": rand_str(6)}},
                        ]}},
                        {"terms": {"color": random.sample(
                            ["red", "blue", "green", "black", "white"], k=3)}},
                    ],
                    "must_not": [{"range": {"quantity": {"lt": 1}}}],
                }
            },
            "size": random.choice([10, 20]),
        }
        status, _ = self._http("POST", f"/{INDEX}/_search", q)
        return "_search", status

    def op_search_geo(self) -> tuple[str, int]:
        q = {
            "query": {
                "geo_distance": {
                    "distance": f"{random.randint(10, 500)}km",
                    "location": {"lat": round(random.uniform(30, 45), 4),
                                 "lon": round(random.uniform(-120, -75), 4)},
                }
            },
            "size": 20,
            "sort": [{"_geo_distance": {"location": {"lat": 40.0, "lon": -100.0},
                                         "order": "asc", "unit": "km"}}],
        }
        status, _ = self._http("POST", f"/{INDEX}/_search", q)
        return "_search", status

    def op_search_script(self) -> tuple[str, int]:
        q = {
            "query": {"match_all": {}},
            "size": 10,
            "script_fields": {
                "discounted_price": {"script": {"source": "doc['price'].value * 0.9"}}
            },
        }
        status, _ = self._http("POST", f"/{INDEX}/_search", q)
        return "_search", status

    def op_update(self) -> tuple[str, int]:
        doc_id = self.tracker.pick()
        if not doc_id:
            return self.op_index()
        body = {"doc": {"price": rand_price(), "quantity": rand_int(0, 500)}}
        status, _ = self._http("POST", f"/{INDEX}/_update/{doc_id}", body)
        return "_update", status

    def op_update_by_query(self) -> tuple[str, int]:
        body = {
            "query": {"term": {"category": rand_category()}},
            "script": {
                "source": "ctx._source.quantity += params.amount",
                "params": {"amount": random.randint(1, 10)},
            },
        }
        status, _ = self._http("POST", f"/{INDEX}/_update_by_query?conflicts=proceed", body)
        return "_update_by_query", status

    def op_delete(self) -> tuple[str, int]:
        doc_id = self.tracker.pick()
        if not doc_id:
            return self.op_index()
        status, _ = self._http("DELETE", f"/{INDEX}/_doc/{doc_id}")
        return "delete", status

    def op_delete_by_query(self) -> tuple[str, int]:
        body = {"query": {"range": {"price": {"lt": rand_int(1, 20)}}}}
        status, _ = self._http("POST", f"/{INDEX}/_delete_by_query?conflicts=proceed", body)
        return "_delete_by_query", status

    def weighted_operations(self) -> list[tuple]:
        return [
            (self.op_search_simple,       20),
            (self.op_search_bool,         15),
            (self.op_search_agg,          10),
            (self.op_search_wildcard,      5),
            (self.op_search_nested_bool,   5),
            (self.op_search_geo,           3),
            (self.op_search_script,        2),
            (self.op_index,               15),
            (self.op_create,               5),
            (self.op_bulk,                 8),
            (self.op_update,               5),
            (self.op_update_by_query,      2),
            (self.op_delete,               3),
            (self.op_delete_by_query,      2),
        ]


# ---------------------------------------------------------------------------
# Seed & worker
# ---------------------------------------------------------------------------

def ensure_index(gateway: str) -> None:
    http_request(gateway, "PUT", f"/{INDEX}", LOADTEST_MAPPING)


def seed_data(gateway: str, tracker: DocIdTracker, count: int = 200) -> None:
    print(f"  Seeding {count} documents ...", end=" ", flush=True)
    actions = []
    for _ in range(count):
        doc_id = rand_str(12)
        actions.append(json.dumps({"index": {"_index": INDEX, "_id": doc_id}}))
        actions.append(json.dumps(rand_doc()))
        tracker.remember(doc_id)
    body = "\n".join(actions) + "\n"
    status, _ = http_request(gateway, "POST", "/_bulk", body,
                             content_type="application/x-ndjson", timeout=30)
    print(f"done ({status})")
    http_request(gateway, "POST", f"/{INDEX}/_refresh")


def worker(ops: OperationMix, stats: Stats, stop_event: threading.Event,
           op_funcs: list, op_weights: list[int]) -> None:
    while not stop_event.is_set():
        fn = random.choices(op_funcs, weights=op_weights, k=1)[0]
        try:
            op, status = fn()
            stats.record(op, status)
        except Exception:
            stats.record("_error", 0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Load-test the observability gateway")
    parser.add_argument("--gateway", default=_DEFAULT_GATEWAY,
                        help="Gateway base URL (default: %(default)s)")
    parser.add_argument("--duration", type=int, default=_DEFAULT_DURATION,
                        help="Test duration in seconds (default: %(default)s)")
    parser.add_argument("--workers", type=int, default=_DEFAULT_WORKERS,
                        help="Concurrent workers (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=200,
                        help="Number of seed documents (default: %(default)s)")
    args = parser.parse_args()

    gateway = args.gateway
    duration = args.duration
    num_workers = args.workers

    print(f"\n  Gateway:   {gateway}")
    print(f"  Duration:  {duration}s")
    print(f"  Workers:   {num_workers}")
    print(f"  Index:     {INDEX}\n")

    # Verify gateway is reachable
    status, _ = http_request(gateway, "GET", "/")
    if status == 0:
        print(f"  ERROR: Cannot reach gateway at {gateway}", file=sys.stderr)
        sys.exit(1)
    print(f"  Gateway reachable (HTTP {status})")

    ops = OperationMix(gateway)
    ensure_index(gateway)
    seed_data(gateway, ops.tracker, args.seed)

    weighted = ops.weighted_operations()
    op_funcs = [fn for fn, _ in weighted]
    op_weights = [w for _, w in weighted]

    print(f"\n  Starting {num_workers} workers for {duration}s ...\n")

    stats = Stats()
    stop = threading.Event()
    threads = [threading.Thread(target=worker,
                                args=(ops, stats, stop, op_funcs, op_weights),
                                daemon=True)
               for _ in range(num_workers)]

    for t in threads:
        t.start()

    try:
        deadline = time.time() + duration
        while time.time() < deadline:
            elapsed = time.time() - stats.start
            print(f"\r  [{elapsed:.0f}s / {duration}s]  requests: {stats.total}  "
                  f"({stats.total / max(elapsed, 0.1):.0f} req/s)  ", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n  Interrupted.")

    stop.set()
    for t in threads:
        t.join(timeout=5)

    stats.report(label="Load Test Results")

    # Cleanup: delete test index
    print(f"  Cleaning up index '{INDEX}' ...", end=" ", flush=True)
    status, _ = http_request(gateway, "DELETE", f"/{INDEX}")
    print(f"done ({status})\n")


if __name__ == "__main__":
    main()
