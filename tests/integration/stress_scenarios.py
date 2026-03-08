#!/usr/bin/env python3
"""
Focused stress-test scenarios for the applicative-load-observability gateway.

Each scenario pushes ONE specific stress dimension to the extreme while running
low-stress "noise" traffic alongside it. This lets you verify in Kibana that
the observability pipeline correctly highlights the stress source.

Usage:
    python tests/stress_scenarios.py --list
    python tests/stress_scenarios.py --scenario script-heavy --duration 30
    python tests/stress_scenarios.py --scenario all --duration 30 --pause 10
    python tests/stress_scenarios.py --scenario script-heavy,agg-explosion
    python tests/stress_scenarios.py --cleanup --scenario nested-deep
"""

import argparse
import json
import random
import string
import sys
import threading
import time
from collections import defaultdict
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ---------------------------------------------------------------------------
# Helpers (mirrored from load_test.py)
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

# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def http(gateway, method, path, body=None, headers=None, content_type="application/json", timeout=15):
    url = f"{gateway}{path}"
    hdrs = {"Content-Type": content_type}
    if headers:
        hdrs.update(headers)
    if isinstance(body, str):
        data = body.encode()
    elif body is not None:
        data = json.dumps(body).encode()
    else:
        data = None
    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        resp = urlopen(req, timeout=timeout)
        return resp.status, resp.read()
    except HTTPError as e:
        return e.code, e.read()
    except (URLError, OSError):
        return 0, b""

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

    def report(self, label=""):
        elapsed = time.time() - self.start
        title = f"  {label}  ({elapsed:.1f}s)" if label else f"  Results  ({elapsed:.1f}s)"
        print(f"\n{'='*60}")
        print(title)
        print(f"{'='*60}")
        print(f"  Total requests:  {self.total}")
        print(f"  Throughput:      {self.total / max(elapsed, 0.1):.1f} req/s")
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
# Scenario registry
# ---------------------------------------------------------------------------

_SCENARIOS = {}

def scenario(name, description):
    """Decorator to register a scenario class."""
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
    name = "base"
    description = "base scenario"

    def __init__(self, gateway):
        self.gateway = gateway
        self.index = f"stress-{self.name}"

    def stress_op(self):
        """Override: execute one stressful operation. Return (op_label, status)."""
        raise NotImplementedError

    def noise_op(self):
        """Execute one low-stress operation. Return (op_label, status)."""
        ops = [self._noise_match_all, self._noise_single_put, self._noise_term]
        return random.choice(ops)()

    def _noise_match_all(self):
        status, _ = http(self.gateway, "POST", f"/{self.index}/_search",
                         {"query": {"match_all": {}}, "size": 5},
                         headers={"X-App-Name": f"noise-{self.name}"})
        return "noise:match_all", status

    def _noise_single_put(self):
        doc_id = rand_str(12)
        status, _ = http(self.gateway, "PUT", f"/{self.index}/_doc/{doc_id}",
                         rand_doc(),
                         headers={"X-App-Name": f"noise-{self.name}"})
        return "noise:put", status

    def _noise_term(self):
        status, _ = http(self.gateway, "POST", f"/{self.index}/_search",
                         {"query": {"term": {"category": rand_category()}}, "size": 3},
                         headers={"X-App-Name": f"noise-{self.name}"})
        return "noise:term", status

    def stress_headers(self):
        return {"X-App-Name": f"stress-{self.name}"}

    def ensure_index(self):
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
        http(self.gateway, "PUT", f"/{self.index}", mapping)

    def seed_data(self, n=500):
        print(f"  Seeding {n} documents into {self.index} ...", end=" ", flush=True)
        actions = []
        for _ in range(n):
            doc_id = rand_str(12)
            actions.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}))
            actions.append(json.dumps(rand_doc()))
        body = "\n".join(actions) + "\n"
        status, _ = http(self.gateway, "POST", "/_bulk", body,
                         headers={"X-App-Name": f"seed-{self.name}"},
                         content_type="application/x-ndjson", timeout=30)
        print(f"done ({status})")
        http(self.gateway, "POST", f"/{self.index}/_refresh")

    def delete_index(self):
        status, _ = http(self.gateway, "DELETE", f"/{self.index}")
        print(f"  Deleted index {self.index} ({status})")

# ---------------------------------------------------------------------------
# The 8 scenarios
# ---------------------------------------------------------------------------

@scenario("script-heavy", "Scripts (clause weight=6): 3-4 script_fields + script_score")
class ScriptHeavyScenario(BaseScenario):
    def stress_op(self):
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
        status, _ = http(self.gateway, "POST", f"/{self.index}/_search",
                         body, headers=self.stress_headers())
        return "stress:script_search", status


@scenario("nested-deep", "Nested clauses (clause weight=5): 4-5 nested queries stacked")
class NestedDeepScenario(BaseScenario):
    def stress_op(self):
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
        status, _ = http(self.gateway, "POST", f"/{self.index}/_search",
                         body, headers=self.stress_headers())
        return "stress:nested_search", status


@scenario("wildcard-swarm", "Wildcards/Regexp/Prefix (clause weight=4): 6-7 clauses")
class WildcardSwarmScenario(BaseScenario):
    def stress_op(self):
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
        status, _ = http(self.gateway, "POST", f"/{self.index}/_search",
                         body, headers=self.stress_headers())
        return "stress:wildcard_search", status


@scenario("agg-explosion", "Deep aggregations (clause weight=3): 3-level nested aggs")
class AggExplosionScenario(BaseScenario):
    def stress_op(self):
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
        status, _ = http(self.gateway, "POST", f"/{self.index}/_search",
                         body, headers=self.stress_headers())
        return "stress:agg_search", status


@scenario("runtime-abuse", "Runtime mappings (weight=5) + Scripts (weight=6)")
class RuntimeAbuseScenario(BaseScenario):
    def stress_op(self):
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
        status, _ = http(self.gateway, "POST", f"/{self.index}/_search",
                         body, headers=self.stress_headers())
        return "stress:runtime_search", status


@scenario("geo-complex", "Geo queries: geo_distance + geo_bounding_box")
class GeoComplexScenario(BaseScenario):
    def stress_op(self):
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
        status, _ = http(self.gateway, "POST", f"/{self.index}/_search",
                         body, headers=self.stress_headers())
        return "stress:geo_search", status


@scenario("bulk-massive", "Bulk write volume: 300-500 docs per _bulk batch")
class BulkMassiveScenario(BaseScenario):
    def stress_op(self):
        batch = random.randint(300, 500)
        actions = []
        for _ in range(batch):
            doc_id = rand_str(12)
            actions.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}))
            actions.append(json.dumps(rand_doc()))
        body = "\n".join(actions) + "\n"
        status, _ = http(self.gateway, "POST", "/_bulk", body,
                         headers={**self.stress_headers(),
                                  "Content-Type": "application/x-ndjson"},
                         content_type="application/x-ndjson", timeout=30)
        return "stress:bulk", status

    def noise_op(self):
        """Override: mix single-doc PUTs and tiny bulk (2-3 docs)."""
        if random.random() < 0.5:
            return self._noise_single_put()
        # tiny bulk
        batch = random.randint(2, 3)
        actions = []
        for _ in range(batch):
            doc_id = rand_str(12)
            actions.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}))
            actions.append(json.dumps(rand_doc()))
        body = "\n".join(actions) + "\n"
        status, _ = http(self.gateway, "POST", "/_bulk", body,
                         headers={"X-App-Name": f"noise-{self.name}",
                                  "Content-Type": "application/x-ndjson"},
                         content_type="application/x-ndjson", timeout=15)
        return "noise:bulk_small", status


@scenario("ubq-carpet-bomb", "Update-by-query with script + wide match on all docs")
class UbqCarpetBombScenario(BaseScenario):
    def stress_op(self):
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
        status, _ = http(self.gateway, "POST",
                         f"/{self.index}/_update_by_query?conflicts=proceed",
                         body, headers=self.stress_headers())
        return "stress:ubq", status

    def noise_op(self):
        """Override: single-doc update or simple search."""
        if random.random() < 0.5:
            doc_id = rand_str(12)
            # Put a doc first so we can update it
            http(self.gateway, "PUT", f"/{self.index}/_doc/{doc_id}",
                 rand_doc(), headers={"X-App-Name": f"noise-{self.name}"})
            status, _ = http(self.gateway, "POST", f"/{self.index}/_update/{doc_id}",
                             {"doc": {"price": 9.99}},
                             headers={"X-App-Name": f"noise-{self.name}"})
            return "noise:update", status
        return self._noise_match_all()

# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------

class ScenarioRunner:
    def __init__(self, gateway, duration, stress_workers, noise_workers, cleanup):
        self.gateway = gateway
        self.duration = duration
        self.stress_workers = stress_workers
        self.noise_workers = noise_workers
        self.cleanup = cleanup

    def run(self, scenario_cls):
        sc = scenario_cls(self.gateway)
        print(f"\n{'#'*60}")
        print(f"  Scenario: {sc.name}")
        print(f"  {sc.description}")
        print(f"  Index: {sc.index}")
        print(f"  Stress workers: {self.stress_workers}  |  Noise workers: {self.noise_workers}")
        print(f"  Duration: {self.duration}s")
        print(f"{'#'*60}\n")

        sc.ensure_index()
        sc.seed_data(500)

        stats = Stats()
        stop = threading.Event()

        def stress_worker():
            while not stop.is_set():
                try:
                    op, status = sc.stress_op()
                    stats.record(op, status)
                except Exception:
                    stats.record("stress:error", 0)

        def noise_worker():
            while not stop.is_set():
                try:
                    op, status = sc.noise_op()
                    stats.record(op, status)
                except Exception:
                    stats.record("noise:error", 0)
                time.sleep(0.05)

        threads = []
        for _ in range(self.stress_workers):
            threads.append(threading.Thread(target=stress_worker, daemon=True))
        for _ in range(self.noise_workers):
            threads.append(threading.Thread(target=noise_worker, daemon=True))

        for t in threads:
            t.start()

        try:
            deadline = time.time() + self.duration
            while time.time() < deadline:
                elapsed = time.time() - stats.start
                print(f"\r  [{sc.name}] [{elapsed:.0f}s / {self.duration}s]  "
                      f"requests: {stats.total}  "
                      f"({stats.total / max(elapsed, 0.1):.0f} req/s)  ",
                      end="", flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n  Interrupted.")

        stop.set()
        for t in threads:
            t.join(timeout=5)

        stats.report(label=sc.name)

        print(f"  Kibana filter:  target: {sc.index}")
        print(f"  Stress app:     applicative_provider: stress-{sc.name}")
        print(f"  Noise app:      applicative_provider: noise-{sc.name}\n")

        if self.cleanup:
            sc.delete_index()

    def run_mix(self, scenario_classes):
        """Run multiple scenarios simultaneously — all stress+noise workers in parallel."""
        scenarios = [cls(self.gateway) for cls in scenario_classes]
        names = ", ".join(sc.name for sc in scenarios)

        print(f"\n{'#'*60}")
        print(f"  MIX MODE — {len(scenarios)} scenarios in parallel")
        print(f"  Scenarios: {names}")
        print(f"  Stress workers per scenario: {self.stress_workers}")
        print(f"  Noise workers per scenario: {self.noise_workers}")
        print(f"  Duration: {self.duration}s")
        print(f"  Total threads: {len(scenarios) * (self.stress_workers + self.noise_workers)}")
        print(f"{'#'*60}\n")

        # Per-scenario stats so we can report each one separately
        sc_stats = {sc.name: Stats() for sc in scenarios}

        for sc in scenarios:
            sc.ensure_index()
            sc.seed_data(500)

        stop = threading.Event()
        threads = []

        for sc in scenarios:
            stats = sc_stats[sc.name]

            def make_stress(s=sc, st=stats):
                def worker():
                    while not stop.is_set():
                        try:
                            op, status = s.stress_op()
                            st.record(op, status)
                        except Exception:
                            st.record("stress:error", 0)
                return worker

            def make_noise(s=sc, st=stats):
                def worker():
                    while not stop.is_set():
                        try:
                            op, status = s.noise_op()
                            st.record(op, status)
                        except Exception:
                            st.record("noise:error", 0)
                        time.sleep(0.05)
                return worker

            for _ in range(self.stress_workers):
                threads.append(threading.Thread(target=make_stress(), daemon=True))
            for _ in range(self.noise_workers):
                threads.append(threading.Thread(target=make_noise(), daemon=True))

        for t in threads:
            t.start()

        try:
            deadline = time.time() + self.duration
            while time.time() < deadline:
                elapsed = time.time() - next(iter(sc_stats.values())).start
                total = sum(s.total for s in sc_stats.values())
                per_sc = "  ".join(f"{n}:{s.total}" for n, s in sc_stats.items())
                print(f"\r  [MIX] [{elapsed:.0f}s / {self.duration}s]  "
                      f"total: {total}  ({total / max(elapsed, 0.1):.0f} req/s)  |  {per_sc}  ",
                      end="", flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n  Interrupted.")

        stop.set()
        for t in threads:
            t.join(timeout=5)

        for sc in scenarios:
            sc_stats[sc.name].report(label=f"MIX: {sc.name}")
            print(f"  Kibana filter:  target: {sc.index}")
            print(f"  Stress app:     applicative_provider: stress-{sc.name}")
            print(f"  Noise app:      applicative_provider: noise-{sc.name}\n")

        if self.cleanup:
            for sc in scenarios:
                sc.delete_index()

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Focused stress-test scenarios for the observability gateway")
    parser.add_argument("--scenario", default=None,
                        help="Scenario name, 'all', or comma-separated list")
    parser.add_argument("--list", action="store_true",
                        help="List available scenarios and exit")
    parser.add_argument("--duration", type=int, default=30,
                        help="Duration per scenario in seconds (default: 30)")
    parser.add_argument("--stress-workers", type=int, default=4,
                        help="Number of stress workers (default: 4)")
    parser.add_argument("--noise-workers", type=int, default=2,
                        help="Number of noise workers (default: 2)")
    parser.add_argument("--gateway", default="http://localhost:9200",
                        help="Gateway base URL (default: http://localhost:9200)")
    parser.add_argument("--cleanup", action="store_true",
                        help="Delete stress indices after run")
    parser.add_argument("--pause", type=int, default=10,
                        help="Pause between scenarios in 'all' mode (default: 10s)")
    parser.add_argument("--mix", action="store_true",
                        help="Run selected scenarios in parallel instead of sequentially")
    args = parser.parse_args()

    if args.list:
        print(f"\n  Available scenarios ({len(_SCENARIOS)}):\n")
        for name, cls in _SCENARIOS.items():
            print(f"    {name:<20} {cls.description}")
        print()
        sys.exit(0)

    if not args.scenario:
        parser.error("--scenario is required (use --list to see options)")

    # Verify gateway is reachable
    status, _ = http(args.gateway, "GET", "/")
    if status == 0:
        print(f"  ERROR: Cannot reach gateway at {args.gateway}", file=sys.stderr)
        sys.exit(1)
    print(f"  Gateway reachable at {args.gateway} (HTTP {status})")

    # Resolve scenario list
    if args.scenario == "all":
        to_run = list(_SCENARIOS.values())
    else:
        names = [n.strip() for n in args.scenario.split(",")]
        to_run = []
        for n in names:
            if n not in _SCENARIOS:
                print(f"  ERROR: Unknown scenario '{n}'. Use --list to see options.",
                      file=sys.stderr)
                sys.exit(1)
            to_run.append(_SCENARIOS[n])

    runner = ScenarioRunner(
        gateway=args.gateway,
        duration=args.duration,
        stress_workers=args.stress_workers,
        noise_workers=args.noise_workers,
        cleanup=args.cleanup,
    )

    if args.mix:
        if len(to_run) < 2:
            parser.error("--mix requires at least 2 scenarios")
        runner.run_mix(to_run)
    else:
        for i, cls in enumerate(to_run):
            runner.run(cls)
            if i < len(to_run) - 1 and len(to_run) > 1:
                print(f"  Pausing {args.pause}s before next scenario ...\n")
                try:
                    time.sleep(args.pause)
                except KeyboardInterrupt:
                    print("\n  Aborted.")
                    sys.exit(0)

    print("  All scenarios complete.")


if __name__ == "__main__":
    main()
