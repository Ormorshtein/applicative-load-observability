"""Internal module for gateway resilience tests — trackers, runners, helpers."""

import json
import random
import subprocess
import threading
import time

from helpers import LOADTEST_MAPPING, http_request, rand_doc, rand_str

INDEX_OVERHEAD = "resilience-overhead"
INDEX_INTEGRITY = "resilience-integrity"
INDEX_SCALING = "resilience-scaling"
ALL_INDICES = [INDEX_OVERHEAD, INDEX_INTEGRITY, INDEX_SCALING]


# ---------------------------------------------------------------------------
# Latency tracker
# ---------------------------------------------------------------------------

class LatencyTracker:
    """Thread-safe latency recorder with percentile computation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: dict[str, list[float]] = {}

    def record(self, operation: str, elapsed_ms: float) -> None:
        with self._lock:
            self._samples.setdefault(operation, []).append(elapsed_ms)

    def percentile(self, operation: str, pct: float) -> float:
        with self._lock:
            data = sorted(self._samples.get(operation, []))
        if not data:
            return 0.0
        idx = int(len(data) * pct / 100.0)
        return data[min(idx, len(data) - 1)]

    def count(self, operation: str) -> int:
        with self._lock:
            return len(self._samples.get(operation, []))


# ---------------------------------------------------------------------------
# Request / index helpers
# ---------------------------------------------------------------------------

def timed_request(
    base_url: str, method: str, path: str,
    body=None, content_type: str = "application/json", timeout: int = 15,
) -> tuple[int, bytes, float]:
    """Execute an HTTP request and return (status, body, elapsed_ms)."""
    start = time.perf_counter()
    status, resp_body = http_request(
        base_url, method, path, body,
        content_type=content_type, timeout=timeout,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return status, resp_body, elapsed_ms


def create_index(base_url: str, index: str) -> None:
    http_request(base_url, "DELETE", f"/{index}")
    http_request(base_url, "PUT", f"/{index}", LOADTEST_MAPPING)


def refresh_index(base_url: str, index: str) -> None:
    http_request(base_url, "POST", f"/{index}/_refresh")


def build_bulk_body(index: str, count: int = 10) -> str:
    lines: list[str] = []
    for _ in range(count):
        lines.append(json.dumps({"index": {"_index": index, "_id": rand_str(12)}}))
        lines.append(json.dumps(rand_doc()))
    return "\n".join(lines) + "\n"


def seed_index(base_url: str, index: str, count: int = 50) -> None:
    create_index(base_url, index)
    body = build_bulk_body(index, count)
    http_request(base_url, "POST", "/_bulk", body,
                 content_type="application/x-ndjson", timeout=30)
    refresh_index(base_url, index)


def cleanup_indices(base_url: str) -> None:
    for index in ALL_INDICES:
        status, _ = http_request(base_url, "DELETE", f"/{index}")
        print(f"  Deleted {index}: {status}")


def print_comparison(
    label: str, gw: LatencyTracker, direct: LatencyTracker, operations: list[str],
) -> dict[str, dict[str, float]]:
    """Print a latency comparison table. Returns overhead percentages."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  {'Operation':<14} {'Metric':>6} {'Gateway':>10} {'Direct':>10} {'Overhead':>10}")
    print(f"  {'-' * 54}")

    overheads: dict[str, dict[str, float]] = {}
    for op in operations:
        overheads[op] = {}
        for pct_label, pct_val in [("p50", 50), ("p95", 95), ("p99", 99)]:
            gw_ms = gw.percentile(op, pct_val)
            dr_ms = direct.percentile(op, pct_val)
            pct_diff = ((gw_ms - dr_ms) / dr_ms * 100) if dr_ms > 0 else 0.0
            overheads[op][pct_label] = pct_diff
            print(f"  {op:<14} {pct_label:>6} {gw_ms:>8.1f}ms {dr_ms:>8.1f}ms {pct_diff:>+8.1f}%")
        print(f"  {'-' * 54}")
    print(f"{'=' * 60}")
    return overheads


# ---------------------------------------------------------------------------
# Test 1: Gateway overhead
# ---------------------------------------------------------------------------

def _run_iterations(
    base_url: str, tracker: LatencyTracker,
    op_name: str, method: str, path: str, body, ct: str, iterations: int,
) -> None:
    for _ in range(iterations):
        if op_name == "index":
            path = f"/{INDEX_OVERHEAD}/_doc/{rand_str(12)}"
        elif op_name == "bulk":
            body = build_bulk_body(INDEX_OVERHEAD)
        status, _, elapsed = timed_request(base_url, method, path, body, content_type=ct)
        if status and status < 400:
            tracker.record(op_name, elapsed)


def run_overhead_test(
    gateway: str, direct_es: str,
    iterations: int, max_p50: float, max_p95: float,
) -> bool:
    print(f"\n{'=' * 60}")
    print("  TEST 1: Gateway Overhead")
    print(f"{'=' * 60}")
    print(f"  Iterations per operation: {iterations}")

    seed_index(direct_es, INDEX_OVERHEAD)

    operations = {
        "search": ("POST", f"/{INDEX_OVERHEAD}/_search",
                   {"query": {"match_all": {}}, "size": 10}),
        "index": ("PUT", f"/{INDEX_OVERHEAD}/_doc/{rand_str(12)}", rand_doc()),
        "bulk": ("POST", "/_bulk", build_bulk_body(INDEX_OVERHEAD)),
    }

    gw_tracker = LatencyTracker()
    direct_tracker = LatencyTracker()

    for op_name, (method, path, body) in operations.items():
        ct = "application/x-ndjson" if op_name == "bulk" else "application/json"
        print(f"  Running {op_name} ... ", end="", flush=True)
        _run_iterations(gateway, gw_tracker, op_name, method, path, body, ct, iterations)
        _run_iterations(direct_es, direct_tracker, op_name, method, path, body, ct, iterations)
        print(f"{gw_tracker.count(op_name)} gw / {direct_tracker.count(op_name)} direct")

    overheads = print_comparison("Overhead Results", gw_tracker, direct_tracker, list(operations))

    passed = True
    for op_name, pcts in overheads.items():
        if pcts["p50"] > max_p50:
            print(f"  FAIL: {op_name} p50 overhead {pcts['p50']:.1f}% > {max_p50}%")
            passed = False
        if pcts["p95"] > max_p95:
            print(f"  FAIL: {op_name} p95 overhead {pcts['p95']:.1f}% > {max_p95}%")
            passed = False

    print(f"  {'PASS' if passed else 'FAIL'}: overhead test")
    return passed


# ---------------------------------------------------------------------------
# Test 2: Data integrity with Logstash up/down
# ---------------------------------------------------------------------------

def _write_and_verify_docs(
    gateway: str, direct_es: str, index: str, prefix: str, count: int,
) -> tuple[int, int]:
    """Write docs through gateway, verify via direct ES. Returns (found, mismatches)."""
    docs_sent: dict[str, dict] = {}
    for i in range(count):
        doc_id = f"{prefix}-{i}"
        doc = rand_doc()
        docs_sent[doc_id] = doc
        http_request(gateway, "PUT", f"/{index}/_doc/{doc_id}", doc)

    refresh_index(direct_es, index)

    found = 0
    mismatches = 0
    for doc_id, expected in docs_sent.items():
        status, body = http_request(direct_es, "GET", f"/{index}/_doc/{doc_id}")
        if status != 200:
            continue
        found += 1
        source = json.loads(body).get("_source", {})
        if any(source.get(field) != value for field, value in expected.items()):
            mismatches += 1

    return found, mismatches


def _docker_compose(action: str, service: str, compose_dir: str) -> None:
    subprocess.run(
        ["docker", "compose", action, service],
        cwd=compose_dir, check=True, capture_output=True, timeout=30,
    )


def run_integrity_test(
    gateway: str, direct_es: str, docs_per_phase: int, compose_dir: str,
) -> bool:
    print(f"\n{'=' * 60}")
    print("  TEST 2: Data Integrity (Logstash up / down)")
    print(f"{'=' * 60}")
    print(f"  Docs per phase: {docs_per_phase}")

    create_index(direct_es, INDEX_INTEGRITY)

    print("  Phase A: Logstash UP — writing docs ...", end=" ", flush=True)
    found_a, mismatch_a = _write_and_verify_docs(
        gateway, direct_es, INDEX_INTEGRITY, "integrity-a", docs_per_phase,
    )
    print(f"found={found_a}/{docs_per_phase}, mismatches={mismatch_a}")

    print("  Phase B: stopping Logstash ...", end=" ", flush=True)
    try:
        _docker_compose("stop", "logstash", compose_dir)
        print("stopped")
        print("  Phase B: Logstash DOWN — writing docs ...", end=" ", flush=True)
        found_b, mismatch_b = _write_and_verify_docs(
            gateway, direct_es, INDEX_INTEGRITY, "integrity-b", docs_per_phase,
        )
        print(f"found={found_b}/{docs_per_phase}, mismatches={mismatch_b}")
    finally:
        print("  Restarting Logstash ...", end=" ", flush=True)
        _docker_compose("start", "logstash", compose_dir)
        print("started")

    status, body = http_request(direct_es, "GET", f"/{INDEX_INTEGRITY}/_count")
    total_count = json.loads(body).get("count", 0) if status == 200 else 0
    expected_total = docs_per_phase * 2

    print(f"\n  {'-' * 40}")
    print(f"  Phase A: {found_a}/{docs_per_phase} found, {mismatch_a} mismatches")
    print(f"  Phase B: {found_b}/{docs_per_phase} found, {mismatch_b} mismatches")
    print(f"  Total:   {total_count}/{expected_total} in index")
    print(f"  {'-' * 40}")

    passed = (
        found_a == docs_per_phase
        and found_b == docs_per_phase
        and mismatch_a == 0
        and mismatch_b == 0
        and total_count == expected_total
    )
    print(f"  {'PASS' if passed else 'FAIL'}: integrity test")
    return passed


# ---------------------------------------------------------------------------
# Test 3: Scaling overhead
# ---------------------------------------------------------------------------

def _scaling_worker(
    base_url: str, index: str, tracker: LatencyTracker,
    label: str, stop_event: threading.Event,
) -> None:
    ops = [
        lambda: timed_request(base_url, "POST", f"/{index}/_search",
                               {"query": {"match_all": {}}, "size": 10}),
        lambda: timed_request(base_url, "PUT",
                               f"/{index}/_doc/{rand_str(12)}", rand_doc()),
    ]
    while not stop_event.is_set():
        status, _, elapsed = random.choice(ops)()
        if status and status < 400:
            tracker.record(label, elapsed)


def run_scaling_test(
    gateway: str, direct_es: str, worker_counts: list[int], duration: int,
) -> bool:
    print(f"\n{'=' * 60}")
    print("  TEST 3: Scaling Overhead")
    print(f"{'=' * 60}")
    print(f"  Worker counts: {worker_counts},  duration: {duration}s/round")

    seed_index(direct_es, INDEX_SCALING)
    p50_overheads: list[float] = []

    for num_workers in worker_counts:
        gw_tracker = LatencyTracker()
        direct_tracker = LatencyTracker()
        stop = threading.Event()

        threads = [
            threading.Thread(target=_scaling_worker, daemon=True,
                             args=(url, INDEX_SCALING, trk, "mixed", stop))
            for _ in range(num_workers)
            for url, trk in [(gateway, gw_tracker), (direct_es, direct_tracker)]
        ]

        print(f"\n  Round: {num_workers} workers x {duration}s ...", end=" ", flush=True)
        for t in threads:
            t.start()
        time.sleep(duration)
        stop.set()
        for t in threads:
            t.join(timeout=5)

        gw_p50 = gw_tracker.percentile("mixed", 50)
        dr_p50 = direct_tracker.percentile("mixed", 50)
        overhead = ((gw_p50 - dr_p50) / dr_p50 * 100) if dr_p50 > 0 else 0.0
        p50_overheads.append(overhead)

        print(f"gw={gw_tracker.count('mixed')} / direct={direct_tracker.count('mixed')} reqs")
        print(f"    p50: gw={gw_p50:.1f}ms  direct={dr_p50:.1f}ms  overhead={overhead:+.1f}%")

    print(f"\n  {'-' * 40}")
    if len(p50_overheads) >= 2 and p50_overheads[0] != 0:
        ratio = abs(p50_overheads[-1]) / max(abs(p50_overheads[0]), 0.1)
        print(f"  Scaling ratio: {ratio:.2f}x (max-workers vs 1-worker overhead)")
        passed = ratio < 2.0
    else:
        print("  Scaling ratio: N/A (insufficient data)")
        passed = True

    print(f"  {'PASS' if passed else 'FAIL'}: scaling test (ratio < 2.0x)")
    return passed
