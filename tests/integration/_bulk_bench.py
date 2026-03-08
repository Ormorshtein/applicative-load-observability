"""Bulk-throughput benchmark for gateway body_filter comparison.

Sends large bulk requests (configurable doc count per batch) through both
gateway and direct ES, measuring latency percentiles and throughput.
"""

import json
import threading
import time

from helpers import http_request, rand_doc, rand_str


def build_bulk_body(index: str, doc_count: int) -> str:
    lines: list[str] = []
    for _ in range(doc_count):
        lines.append(json.dumps({"index": {"_index": index, "_id": rand_str(12)}}))
        lines.append(json.dumps(rand_doc()))
    return "\n".join(lines) + "\n"


def _timed_bulk(base_url: str, body: str, timeout: int = 30) -> tuple[int, float]:
    start = time.perf_counter()
    status, _ = http_request(
        base_url, "POST", "/_bulk", body,
        content_type="application/x-ndjson", timeout=timeout,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return status, elapsed_ms


def run_bulk_bench(
    base_url: str,
    label: str,
    index: str,
    docs_per_bulk: int,
    iterations: int,
) -> list[float]:
    """Send bulk requests and return list of latencies in ms."""
    latencies: list[float] = []

    print(f"  {label}: {iterations} x {docs_per_bulk}-doc bulks ...", end=" ", flush=True)
    for i in range(iterations):
        body = build_bulk_body(index, docs_per_bulk)
        status, elapsed = _timed_bulk(base_url, body)
        if status and status < 400:
            latencies.append(elapsed)
        if (i + 1) % 10 == 0:
            print(f"{i + 1}", end=" ", flush=True)

    print()
    return latencies


def run_concurrent_bulk_bench(
    base_url: str,
    label: str,
    index: str,
    docs_per_bulk: int,
    workers: int,
    duration: int,
) -> list[float]:
    """Run concurrent bulk workers for a duration, return all latencies."""
    latencies: list[float] = []
    lock = threading.Lock()
    stop = threading.Event()
    request_count = 0

    def worker_fn() -> None:
        nonlocal request_count
        while not stop.is_set():
            body = build_bulk_body(index, docs_per_bulk)
            status, elapsed = _timed_bulk(base_url, body)
            if status and status < 400:
                with lock:
                    latencies.append(elapsed)
                    request_count += 1

    print(f"  {label}: {workers} workers x {duration}s, "
          f"{docs_per_bulk}-doc bulks ...", end=" ", flush=True)

    threads = [
        threading.Thread(target=worker_fn, daemon=True) for _ in range(workers)
    ]
    for t in threads:
        t.start()
    time.sleep(duration)
    stop.set()
    for t in threads:
        t.join(timeout=5)

    print(f"{len(latencies)} reqs")
    return latencies


def percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = int(len(s) * pct / 100.0)
    return s[min(idx, len(s) - 1)]


def print_bulk_comparison(
    gw_latencies: list[float],
    direct_latencies: list[float],
    label: str,
) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  {'Metric':<10} {'Gateway':>12} {'Direct':>12} {'Overhead':>12}")
    print(f"  {'-' * 48}")

    for pct_label, pct_val in [("p50", 50), ("p95", 95), ("p99", 99)]:
        gw = percentile(gw_latencies, pct_val)
        dr = percentile(direct_latencies, pct_val)
        overhead = ((gw - dr) / dr * 100) if dr > 0 else 0.0
        print(f"  {pct_label:<10} {gw:>10.1f}ms {dr:>10.1f}ms {overhead:>+10.1f}%")

    print(f"  {'-' * 48}")
    print(f"  {'count':<10} {len(gw_latencies):>12} {len(direct_latencies):>12}")
    print(f"{'=' * 60}")
