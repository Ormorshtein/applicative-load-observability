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
import string
import sys
import threading
import time
from collections import defaultdict
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:9200")
INDEX = "loadtest"
DURATION = 60
WORKERS = 10

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rand_str(n=8):
    return "".join(random.choices(string.ascii_lowercase, k=n))

def rand_text(words=10):
    return " ".join(rand_str(random.randint(3, 10)) for _ in range(words))

def rand_int(lo=1, hi=10000):
    return random.randint(lo, hi)

def rand_price():
    return round(random.uniform(1.0, 999.99), 2)

def rand_category():
    return random.choice(["electronics", "clothing", "food", "books",
                          "sports", "home", "toys", "automotive"])

def rand_color():
    return random.choice(["red", "blue", "green", "black", "white",
                          "yellow", "orange", "purple"])

def rand_doc():
    return {
        "title": rand_text(random.randint(2, 6)),
        "description": rand_text(random.randint(10, 30)),
        "category": rand_category(),
        "price": rand_price(),
        "quantity": rand_int(0, 500),
        "color": rand_color(),
        "tags": random.sample(["sale", "new", "popular", "limited",
                                "exclusive", "clearance", "premium"], k=random.randint(1, 4)),
        "rating": round(random.uniform(1.0, 5.0), 1),
        "location": {"lat": round(random.uniform(29.0, 47.0), 4),
                      "lon": round(random.uniform(-124.0, -71.0), 4)},
        "created_at": f"2025-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
    }

def http(method, path, body=None, headers=None):
    url = f"{GATEWAY}{path}"
    hdrs = {"Content-Type": "application/json",
            "User-Agent": f"load-test/{random.choice(['search-svc','ingest-svc','admin-cli','dashboard'])}"}
    if random.random() < 0.3:
        hdrs["X-App-Name"] = random.choice(["search-api", "catalog-sync",
                                             "analytics", "reindex-job"])
    if headers:
        hdrs.update(headers)
    data = json.dumps(body).encode() if body else None
    if method == "GET" and data:
        # ES accepts body on GET for _search
        pass
    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        resp = urlopen(req, timeout=15)
        return resp.status, resp.read()
    except HTTPError as e:
        return e.code, e.read()
    except (URLError, OSError):
        return 0, b""

# ---------------------------------------------------------------------------
# Operation generators
# ---------------------------------------------------------------------------

_doc_ids = []
_id_lock = threading.Lock()

def remember_id(doc_id):
    with _id_lock:
        _doc_ids.append(doc_id)
        if len(_doc_ids) > 5000:
            _doc_ids[:] = _doc_ids[-2000:]

def pick_id():
    with _id_lock:
        return random.choice(_doc_ids) if _doc_ids else None


def op_index():
    """PUT a single document."""
    doc_id = rand_str(12)
    status, _ = http("PUT", f"/{INDEX}/_doc/{doc_id}", rand_doc())
    if 200 <= status < 300:
        remember_id(doc_id)
    return "index", status

def op_create():
    """PUT _create a single document."""
    doc_id = rand_str(12)
    status, _ = http("PUT", f"/{INDEX}/_create/{doc_id}", rand_doc())
    if 200 <= status < 300:
        remember_id(doc_id)
    return "_create", status

def op_bulk():
    """POST _bulk with a mix of index/create/delete actions."""
    actions = []
    batch = random.randint(5, 50)
    for _ in range(batch):
        doc_id = rand_str(12)
        actions.append(json.dumps({"index": {"_index": INDEX, "_id": doc_id}}))
        actions.append(json.dumps(rand_doc()))
        remember_id(doc_id)
    body = "\n".join(actions) + "\n"
    req = Request(f"{GATEWAY}/_bulk",
                  data=body.encode(),
                  headers={"Content-Type": "application/x-ndjson",
                           "User-Agent": "load-test/ingest-svc"},
                  method="POST")
    try:
        resp = urlopen(req, timeout=30)
        return "_bulk", resp.status
    except HTTPError as e:
        return "_bulk", e.code
    except (URLError, OSError):
        return "_bulk", 0

def op_search_simple():
    """Simple match_all or match search."""
    queries = [
        {"query": {"match_all": {}}, "size": random.choice([10, 20, 50, 100])},
        {"query": {"match": {"title": rand_str(5)}}, "size": 10},
        {"query": {"term": {"category": rand_category()}}, "size": 20},
        {"query": {"range": {"price": {"gte": rand_int(1, 200), "lte": rand_int(300, 999)}}}, "size": 15},
    ]
    q = random.choice(queries)
    status, _ = http("POST", f"/{INDEX}/_search", q)
    return "_search", status

def op_search_bool():
    """Bool query with multiple clauses."""
    q = {
        "query": {
            "bool": {
                "must": [{"match": {"description": rand_str(6)}}],
                "filter": [
                    {"term": {"category": rand_category()}},
                    {"range": {"price": {"gte": rand_int(1, 100), "lte": rand_int(200, 999)}}},
                ],
                "should": [
                    {"term": {"color": rand_color()}},
                ],
            }
        },
        "size": random.choice([10, 25, 50]),
        "sort": [{"price": "asc"}],
    }
    status, _ = http("POST", f"/{INDEX}/_search", q)
    return "_search", status

def op_search_agg():
    """Search with aggregations."""
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
                            "ranges": [
                                {"to": 50},
                                {"from": 50, "to": 200},
                                {"from": 200},
                            ],
                        }
                    },
                },
            },
            "price_stats": {"stats": {"field": "price"}},
        },
    }
    status, _ = http("POST", f"/{INDEX}/_search", q)
    return "_search", status

def op_search_wildcard():
    """Wildcard / fuzzy search."""
    variants = [
        {"query": {"wildcard": {"title": {"value": f"{rand_str(2)}*{rand_str(1)}"}}}},
        {"query": {"fuzzy": {"title": {"value": rand_str(5), "fuzziness": "AUTO"}}}},
    ]
    q = random.choice(variants)
    q["size"] = 10
    status, _ = http("POST", f"/{INDEX}/_search", q)
    return "_search", status

def op_search_nested_bool():
    """Deeply nested bool query."""
    q = {
        "query": {
            "bool": {
                "must": [
                    {"bool": {
                        "should": [
                            {"match": {"title": rand_str(4)}},
                            {"match": {"description": rand_str(6)}},
                        ]
                    }},
                    {"terms": {"color": random.sample(
                        ["red", "blue", "green", "black", "white"], k=3)}},
                ],
                "must_not": [{"range": {"quantity": {"lt": 1}}}],
            }
        },
        "size": random.choice([10, 20]),
    }
    status, _ = http("POST", f"/{INDEX}/_search", q)
    return "_search", status

def op_search_geo():
    """Geo-distance search."""
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
    status, _ = http("POST", f"/{INDEX}/_search", q)
    return "_search", status

def op_search_script():
    """Search with a script field."""
    q = {
        "query": {"match_all": {}},
        "size": 10,
        "script_fields": {
            "discounted_price": {
                "script": {
                    "source": "doc['price'].value * 0.9"
                }
            }
        },
    }
    status, _ = http("POST", f"/{INDEX}/_search", q)
    return "_search", status

def op_update():
    """Update a single document."""
    doc_id = pick_id()
    if not doc_id:
        return op_index()
    body = {"doc": {"price": rand_price(), "quantity": rand_int(0, 500)}}
    status, _ = http("POST", f"/{INDEX}/_update/{doc_id}", body)
    return "_update", status

def op_update_by_query():
    """Update by query."""
    body = {
        "query": {"term": {"category": rand_category()}},
        "script": {
            "source": "ctx._source.quantity += params.amount",
            "params": {"amount": random.randint(1, 10)},
        },
    }
    status, _ = http("POST", f"/{INDEX}/_update_by_query?conflicts=proceed", body)
    return "_update_by_query", status

def op_delete():
    """Delete a single document."""
    doc_id = pick_id()
    if not doc_id:
        return op_index()
    status, _ = http("DELETE", f"/{INDEX}/_doc/{doc_id}")
    return "delete", status

def op_delete_by_query():
    """Delete by query."""
    body = {
        "query": {"range": {"price": {"lt": rand_int(1, 20)}}},
    }
    status, _ = http("POST", f"/{INDEX}/_delete_by_query?conflicts=proceed", body)
    return "_delete_by_query", status

# ---------------------------------------------------------------------------
# Weighted operation mix
# ---------------------------------------------------------------------------

OPERATIONS = [
    (op_search_simple,       20),
    (op_search_bool,         15),
    (op_search_agg,          10),
    (op_search_wildcard,      5),
    (op_search_nested_bool,   5),
    (op_search_geo,           3),
    (op_search_script,        2),
    (op_index,               15),
    (op_create,               5),
    (op_bulk,                 8),
    (op_update,               5),
    (op_update_by_query,      2),
    (op_delete,               3),
    (op_delete_by_query,      2),
]

_op_funcs = []
_op_weights = []
for fn, w in OPERATIONS:
    _op_funcs.append(fn)
    _op_weights.append(w)

def pick_op():
    return random.choices(_op_funcs, weights=_op_weights, k=1)[0]

# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.counts = defaultdict(int)
        self.errors = defaultdict(int)
        self.total = 0
        self.start = time.time()

    def record(self, op, status):
        with self.lock:
            self.total += 1
            self.counts[op] += 1
            if status == 0 or status >= 400:
                self.errors[op] += 1

    def report(self):
        elapsed = time.time() - self.start
        print(f"\n{'='*60}")
        print(f"  Load Test Results  ({elapsed:.1f}s)")
        print(f"{'='*60}")
        print(f"  Total requests:  {self.total}")
        print(f"  Throughput:      {self.total / elapsed:.1f} req/s")
        print(f"{'='*60}")
        print(f"  {'Operation':<25} {'Count':>8} {'Errors':>8}")
        print(f"  {'-'*41}")
        for op in sorted(self.counts):
            print(f"  {op:<25} {self.counts[op]:>8} {self.errors.get(op, 0):>8}")
        total_errors = sum(self.errors.values())
        print(f"  {'-'*41}")
        print(f"  {'TOTAL':<25} {self.total:>8} {total_errors:>8}")
        print(f"{'='*60}\n")

# ---------------------------------------------------------------------------
# Seed & worker
# ---------------------------------------------------------------------------

def ensure_index():
    """Create the index with a mapping that supports geo_point."""
    mapping = {
        "mappings": {
            "properties": {
                "title":       {"type": "text"},
                "description": {"type": "text"},
                "category":    {"type": "keyword"},
                "price":       {"type": "float"},
                "quantity":    {"type": "integer"},
                "color":       {"type": "keyword"},
                "tags":        {"type": "keyword"},
                "rating":      {"type": "float"},
                "location":    {"type": "geo_point"},
                "created_at":  {"type": "date", "format": "yyyy-MM-dd"},
            }
        }
    }
    http("PUT", f"/{INDEX}", mapping)

def seed_data(n=200):
    """Bulk-insert seed documents so searches have something to hit."""
    print(f"  Seeding {n} documents ...", end=" ", flush=True)
    actions = []
    for _ in range(n):
        doc_id = rand_str(12)
        actions.append(json.dumps({"index": {"_index": INDEX, "_id": doc_id}}))
        actions.append(json.dumps(rand_doc()))
        remember_id(doc_id)
    body = "\n".join(actions) + "\n"
    req = Request(f"{GATEWAY}/_bulk",
                  data=body.encode(),
                  headers={"Content-Type": "application/x-ndjson"},
                  method="POST")
    try:
        resp = urlopen(req, timeout=30)
        print(f"done ({resp.status})")
    except Exception as e:
        print(f"failed ({e})")

    # Refresh so seeded docs are searchable
    http("POST", f"/{INDEX}/_refresh")

def worker(stats, stop_event):
    while not stop_event.is_set():
        fn = pick_op()
        try:
            op, status = fn()
            stats.record(op, status)
        except Exception:
            stats.record("_error", 0)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global GATEWAY, DURATION, WORKERS

    parser = argparse.ArgumentParser(description="Load-test the observability gateway")
    parser.add_argument("--gateway", default=GATEWAY, help="Gateway base URL (default: %(default)s)")
    parser.add_argument("--duration", type=int, default=DURATION, help="Test duration in seconds (default: %(default)s)")
    parser.add_argument("--workers", type=int, default=WORKERS, help="Concurrent workers (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=200, help="Number of seed documents (default: %(default)s)")
    args = parser.parse_args()

    GATEWAY = args.gateway
    DURATION = args.duration
    WORKERS = args.workers

    print(f"\n  Gateway:   {GATEWAY}")
    print(f"  Duration:  {DURATION}s")
    print(f"  Workers:   {WORKERS}")
    print(f"  Index:     {INDEX}\n")

    # Verify gateway is reachable
    try:
        status, _ = http("GET", "/")
        if status == 0:
            raise ConnectionError
        print(f"  Gateway reachable (HTTP {status})")
    except Exception:
        print(f"  ERROR: Cannot reach gateway at {GATEWAY}", file=sys.stderr)
        sys.exit(1)

    ensure_index()
    seed_data(args.seed)

    print(f"\n  Starting {WORKERS} workers for {DURATION}s ...\n")

    stats = Stats()
    stop = threading.Event()
    threads = [threading.Thread(target=worker, args=(stats, stop), daemon=True)
               for _ in range(WORKERS)]

    for t in threads:
        t.start()

    try:
        deadline = time.time() + DURATION
        while time.time() < deadline:
            remaining = deadline - time.time()
            elapsed = time.time() - stats.start
            print(f"\r  [{elapsed:.0f}s / {DURATION}s]  requests: {stats.total}  "
                  f"({stats.total / max(elapsed, 0.1):.0f} req/s)  ", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n  Interrupted.")

    stop.set()
    for t in threads:
        t.join(timeout=5)

    stats.report()

    # Cleanup: delete test index
    print(f"  Cleaning up index '{INDEX}' ...", end=" ", flush=True)
    status, _ = http("DELETE", f"/{INDEX}")
    print(f"done ({status})\n")


if __name__ == "__main__":
    main()
