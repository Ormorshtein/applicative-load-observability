#!/usr/bin/env python3
"""
Challenge mode: detect the stress source among 4 simulated applications.

Four apps hit a shared index simultaneously — most doing normal work, one
hiding expensive query patterns in its traffic. Monitor Kibana dashboards
to identify and kill the culprit.

Usage:
    python tests/challenges/challenge.py
    python tests/challenges/challenge.py --gateway http://host:9200
    python tests/challenges/challenge.py --seed 20000 --max-docs 100000
"""

import argparse
import json
import os
import random
import select
import sys
import threading
import time

from helpers import (
    LOADTEST_MAPPING, Stats, http_request,
    rand_category, rand_doc, rand_str,
)

INDEX = "challenge"
_DEFAULT_GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:9200")


# ---------------------------------------------------------------------------
# Document ID tracker (thread-safe)
# ---------------------------------------------------------------------------

class DocIdTracker:
    def __init__(self, max_docs: int = 50000) -> None:
        self._ids: list[str] = []
        self._lock = threading.Lock()
        self._doc_count: int = 0
        self._max_docs = max_docs

    def remember(self, doc_id: str) -> None:
        with self._lock:
            self._ids.append(doc_id)
            self._doc_count += 1
            if len(self._ids) > 5000:
                self._ids[:] = self._ids[-2000:]

    def pick(self) -> str | None:
        with self._lock:
            return random.choice(self._ids) if self._ids else None

    @property
    def writes_allowed(self) -> bool:
        return self._doc_count < self._max_docs


# ---------------------------------------------------------------------------
# Cluster health monitor — throttles workers when heap gets dangerously high
# ---------------------------------------------------------------------------

class HealthMonitor:
    HEAP_THROTTLE_PCT = 82
    HEAP_RESUME_PCT = 70

    def __init__(self, gateway: str) -> None:
        self._gateway = gateway
        self.throttle = threading.Event()  # set = workers must pause
        self.heap_pct: int = 0
        self.cpu_pct: int = 0
        self._stop = threading.Event()

    def start(self) -> None:
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()

    def stop(self) -> None:
        self._stop.set()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self._check()
            self._stop.wait(4)

    def _check(self) -> None:
        try:
            s, body = http_request(
                self._gateway, "GET", "/_nodes/stats/jvm,os", timeout=5)
            if s != 200:
                return
            data = json.loads(body)
            for node in data.get("nodes", {}).values():
                jvm = node.get("jvm", {}).get("mem", {})
                self.heap_pct = jvm.get("heap_used_percent", 0)
                os_cpu = node.get("os", {}).get("cpu", {})
                self.cpu_pct = os_cpu.get("percent", 0)
        except Exception:
            return

        if self.heap_pct >= self.HEAP_THROTTLE_PCT:
            if not self.throttle.is_set():
                print(f"\n  [MONITOR] Heap {self.heap_pct}% — throttling workers")
            self.throttle.set()
        elif self.heap_pct <= self.HEAP_RESUME_PCT and self.throttle.is_set():
            print(f"\n  [MONITOR] Heap {self.heap_pct}% — resuming")
            self.throttle.clear()


# ---------------------------------------------------------------------------
# Query operations — uniform signature: (gw, app, tracker) -> (op, status)
# ---------------------------------------------------------------------------

def _send(gw, app, method, path, body=None, **kw):
    return http_request(gw, method, path, body,
                        headers={"X-App-Name": app}, **kw)


def _search(gw, app, body):
    s, _ = _send(gw, app, "POST", f"/{INDEX}/_search", body)
    return "_search", s


def _simple_search(gw, app, _tr):
    q = random.choice([
        {"query": {"match": {"title": rand_str(5)}}, "size": 50},
        {"query": {"term": {"category": rand_category()}}, "size": 50},
        {"query": {"range": {"price": {"gte": random.randint(1, 200),
                                        "lte": random.randint(300, 999)}}}, "size": 50},
        {"query": {"wildcard": {"title": {"value": f"*{rand_str(2)}*"}}}, "size": 30},
    ])
    return _search(gw, app, q)


def _bool_search(gw, app, _tr):
    return _search(gw, app, {"query": {"bool": {
        "must": [{"match": {"description": rand_str(6)}}],
        "filter": [{"term": {"category": rand_category()}},
                   {"range": {"price": {"gte": random.randint(1, 100),
                                         "lte": random.randint(200, 999)}}}],
    }}, "size": 100})


def _single_index(gw, app, tr):
    if not tr.writes_allowed:
        return _simple_search(gw, app, tr)
    doc_id = rand_str(12)
    s, _ = _send(gw, app, "PUT", f"/{INDEX}/_doc/{doc_id}", rand_doc())
    if 200 <= s < 300:
        tr.remember(doc_id)
    return "index", s


def _bulk_index(gw, app, tr, lo=5, hi=20):
    if not tr.writes_allowed:
        return _simple_search(gw, app, tr)
    actions = []
    for _ in range(random.randint(lo, hi)):
        did = rand_str(12)
        actions.append(json.dumps({"index": {"_index": INDEX, "_id": did}}))
        actions.append(json.dumps(rand_doc()))
        tr.remember(did)
    s, _ = _send(gw, app, "POST", "/_bulk", "\n".join(actions) + "\n",
                 content_type="application/x-ndjson", timeout=30)
    return "_bulk", s


def _match_all(gw, app, _tr):
    return _search(gw, app, {"query": {"match_all": {}}, "size": 50})


def _light_agg(gw, app, _tr):
    return _search(gw, app, {"size": 0, "aggs": {"by_cat": {
        "terms": {"field": "category", "size": 10},
        "aggs": {"avg_price": {"avg": {"field": "price"}}}}}})


def _geo_search(gw, app, _tr):
    lat = round(random.uniform(30, 45), 4)
    lon = round(random.uniform(-120, -75), 4)
    return _search(gw, app, {"query": {"geo_distance": {
        "distance": f"{random.randint(50, 500)}km",
        "location": {"lat": lat, "lon": lon}}},
        "sort": [{"_geo_distance": {"location": {"lat": lat, "lon": lon},
                                     "order": "asc"}}],
        "size": 100})


def _runtime_mapping_search(gw, app, _tr):
    """4 runtime fields evaluated per doc — heavy CPU on match_all."""
    return _search(gw, app, {
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
        "size": 50})


def _script_fields_search(gw, app, _tr):
    """script_score forces per-doc scoring + script_fields on results."""
    return _search(gw, app, {
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


def _deep_agg_search(gw, app, _tr):
    """3-level nested aggregation with stats + histogram."""
    return _search(gw, app, {"size": 0, "aggs": {"by_cat": {
        "terms": {"field": "category", "size": 50}, "aggs": {
            "by_color": {"terms": {"field": "color", "size": 20}, "aggs": {
                "price_stats": {"stats": {"field": "price"}},
                "price_hist": {"histogram": {"field": "price", "interval": 50}},
                "rating_pct": {"percentiles": {"field": "rating"}}}},
            "avg_price": {"avg": {"field": "price"}},
            "max_rating": {"max": {"field": "rating"}}}}}})


def _combo_search(gw, app, _tr):
    """Stacks runtime_mappings + script_score + script_fields — peak CPU."""
    return _search(gw, app, {
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
# The 4 applications: (name, workers, role, [(op_fn, weight), ...])
# ---------------------------------------------------------------------------

APP_CONFIGS = [
    ("catalog-search", 5, "innocent", [
        (_simple_search, 40), (_bool_search, 25),
        (_single_index, 20), (_light_agg, 15)]),
    ("order-ingest", 3, "innocent", [
        (lambda gw, app, tr: _bulk_index(gw, app, tr, 5, 20), 60),
        (_single_index, 25), (_match_all, 15)]),
    ("analytics-dashboard", 5, "culprit", [
        (_simple_search, 45), (_runtime_mapping_search, 15),
        (_script_fields_search, 12), (_deep_agg_search, 10),
        (_combo_search, 10), (_single_index, 8)]),
    ("geo-locator", 3, "red-herring", [
        (_simple_search, 50), (_geo_search, 20),
        (_single_index, 15), (_bool_search, 15)]),
]


# ---------------------------------------------------------------------------
# Worker & setup
# ---------------------------------------------------------------------------

def _run_worker(name, ops, weights, gw, tracker, stats, stop, monitor):
    while not stop.is_set():
        if monitor.throttle.is_set():
            time.sleep(0.5)
            continue
        try:
            fn = random.choices(ops, weights=weights, k=1)[0]
            op, status = fn(gw, name, tracker)
            stats.record(op, status)
            if status == 0 or status >= 429:
                time.sleep(0.2)
        except Exception:
            stats.record("_error", 0)
            time.sleep(0.1)


def _seed_data(gateway, tracker, count):
    print(f"  Seeding {count} documents ...", flush=True)
    batch = 500
    for start in range(0, count, batch):
        end = min(start + batch, count)
        actions = []
        for _ in range(end - start):
            did = rand_str(12)
            actions.append(json.dumps({"index": {"_index": INDEX, "_id": did}}))
            actions.append(json.dumps(rand_doc()))
            tracker.remember(did)
        s, _ = http_request(gateway, "POST", "/_bulk", "\n".join(actions) + "\n",
                            content_type="application/x-ndjson", timeout=30)
        print(f"    batch {start}-{end}: {s}", flush=True)
    http_request(gateway, "POST", f"/{INDEX}/_refresh")
    print("  Seeding complete.")


def _warmup_scripts(gateway):
    """Run each script query once to force Painless compilation."""
    print("  Warming up Painless scripts ...", end=" ", flush=True)
    warmup_app = "warmup"
    tracker = DocIdTracker()
    for fn in (_runtime_mapping_search, _script_fields_search,
               _deep_agg_search, _combo_search, _geo_search):
        fn(gateway, warmup_app, tracker)
    print("done.")


def _stdin_ready():
    if sys.platform == "win32":
        import msvcrt
        return msvcrt.kbhit()
    return bool(select.select([sys.stdin], [], [], 0)[0])


# ---------------------------------------------------------------------------
# Interactive challenge loop
# ---------------------------------------------------------------------------

def run_challenge(gateway, seed_count, max_docs):
    tracker = DocIdTracker(max_docs=max_docs)
    monitor = HealthMonitor(gateway)

    print(f"\n  Gateway:   {gateway}")
    print(f"  Index:     {INDEX}    Max docs: {max_docs}\n")

    status, _ = http_request(gateway, "GET", "/")
    if status == 0:
        print(f"  ERROR: Cannot reach gateway at {gateway}", file=sys.stderr)
        sys.exit(1)
    print(f"  Gateway reachable (HTTP {status})")

    http_request(gateway, "PUT", f"/{INDEX}", LOADTEST_MAPPING)
    _seed_data(gateway, tracker, seed_count)
    _warmup_scripts(gateway)

    names = [n for n, *_ in APP_CONFIGS]
    roles = {n: r for n, _, r, _ in APP_CONFIGS}
    stats = {n: Stats() for n in names}
    stops = {n: threading.Event() for n in names}
    threads: dict[str, list[threading.Thread]] = {}

    total_w = 0
    for name, workers, _, op_defs in APP_CONFIGS:
        ops = [fn for fn, _ in op_defs]
        wts = [w for _, w in op_defs]
        ts = [threading.Thread(target=_run_worker, daemon=True,
              args=(name, ops, wts, gateway, tracker, stats[name], stops[name],
                    monitor))
              for _ in range(workers)]
        threads[name] = ts
        total_w += workers

    print(f"\n  Starting 4 applications ({total_w} workers)...")
    for n, w, _, _ in APP_CONFIGS:
        print(f"    {n:<25} {w} workers")
    print(f"\n  Commands: <app-name> to stop | status | quit")
    print(f"  Runs until you type 'quit' or press Ctrl+C\n")

    monitor.start()
    for ts in threads.values():
        for t in ts:
            t.start()

    stopped: set[str] = set()
    culprit_found = False
    start_time = time.time()

    try:
        while True:
            el = time.time() - start_time
            tot = sum(s.total for s in stats.values())
            throttled = " [THROTTLED]" if monitor.throttle.is_set() else ""
            cap_warn = " [WRITES CAPPED]" if not tracker.writes_allowed else ""
            sys.stdout.write(
                f"\r  [{el:.0f}s] reqs:{tot} "
                f"({tot/max(el,.1):.0f} r/s) "
                f"cpu:{monitor.cpu_pct}% heap:{monitor.heap_pct}% "
                f"running:{len(names)-len(stopped)}/4"
                f"{throttled}{cap_warn}  ")
            sys.stdout.flush()

            if not _stdin_ready():
                time.sleep(0.5)
                continue

            line = sys.stdin.readline().strip().lower()
            if line == "quit":
                print("\n  Quitting...")
                break
            elif line == "status":
                print()
                for n in names:
                    st, el2 = stats[n], time.time() - stats[n].start
                    state = "STOPPED" if n in stopped else "running"
                    print(f"  {n:<25} {st.total:>6} reqs "
                          f"({st.total/max(el2,.1):>5.0f} r/s) [{state}]")
                print(f"  ES cpu: {monitor.cpu_pct}%  heap: {monitor.heap_pct}%")
                print()
            elif line in set(names):
                if line in stopped:
                    print(f"\n  '{line}' already stopped.\n")
                else:
                    stops[line].set()
                    for t in threads[line]:
                        t.join(timeout=5)
                    stopped.add(line)
                    print(f"\n  Stopped '{line}'. Watch Kibana.\n")
                    if line == "analytics-dashboard" and not culprit_found:
                        culprit_found = True
                        print("  >>> You got the culprit! Watch stress drop. <<<\n")
            elif line:
                print(f"\n  Unknown: '{line}'. Apps: {', '.join(names)}\n")
    except KeyboardInterrupt:
        print("\n\n  Interrupted.")

    monitor.stop()
    for e in stops.values():
        e.set()
    for ts in threads.values():
        for t in ts:
            t.join(timeout=5)

    # Final summary
    print(f"\n{'='*60}\n  Challenge Results\n{'='*60}")
    for n in names:
        st, el2 = stats[n], time.time() - stats[n].start
        tag = " (CULPRIT)" if roles[n] == "culprit" else ""
        state = "STOPPED" if n in stopped else "running"
        print(f"  {n:<25} {st.total:>6} reqs "
              f"({st.total/max(el2,.1):>5.0f} r/s) [{state}]{tag}")
    print(f"{'='*60}")
    if culprit_found:
        print("\n  You found the culprit: analytics-dashboard!")
    else:
        print("\n  The culprit was: analytics-dashboard")
        print("  It mixed runtime_mappings, script_fields, and deep aggs")
        print("  into ~47% of queries, stacking multipliers up to 2.9x.")

    print(f"\n  Cleaning up '{INDEX}' ...", end=" ", flush=True)
    s, _ = http_request(gateway, "DELETE", f"/{INDEX}")
    print(f"done ({s})\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Challenge: detect the stress source among 4 applications")
    parser.add_argument("--gateway", default=_DEFAULT_GATEWAY,
                        help="Gateway base URL (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=10000,
                        help="Number of seed documents (default: %(default)s)")
    parser.add_argument("--max-docs", type=int, default=50000,
                        help="Stop writing new docs after this count (default: %(default)s)")
    args = parser.parse_args()
    run_challenge(args.gateway, args.seed, args.max_docs)


if __name__ == "__main__":
    main()
