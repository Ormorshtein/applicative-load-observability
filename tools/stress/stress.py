#!/usr/bin/env python3
"""
Stress tool for the applicative-load-observability gateway.

Drives controllable, high-throughput Elasticsearch traffic through the
observability gateway with real-time latency percentiles and multiple
workload profiles.  Similar in spirit to cassandra-stress.

Usage:
    python tools/stress/stress.py --list
    python tools/stress/stress.py --workload mixed --threads 20 --duration 60
    python tools/stress/stress.py --workload script --rate 500 --threads 10
    python tools/stress/stress.py --workload bulk --rate 0 --threads 50 --duration 120
"""

import argparse
import os
import sys
import threading
import time

from _engine import (
    RateLimiter,
    delete_index,
    ensure_index,
    seed_data,
    worker_loop,
)
from _helpers import add_auth_args, apply_auth_args, http_request
from _metrics import LatencyTracker, format_live, format_report

import _workloads        # noqa: F401 — registers mixed/search/write
import _stress_profiles  # noqa: F401 — registers stress profiles
from _workloads import WORKLOADS

_DEFAULT_GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:9200")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Stress tool for the observability gateway")
    p.add_argument("--workload", default=None,
                   help="Workload profile (use --list to see options)")
    p.add_argument("--list", action="store_true",
                   help="List available workload profiles and exit")
    p.add_argument("--rate", type=int, default=0,
                   help="Target ops/sec; 0 = unlimited (default: 0)")
    p.add_argument("--threads", type=int, default=10,
                   help="Number of worker threads (default: 10)")
    p.add_argument("--duration", type=int, default=60,
                   help="Test duration in seconds (default: 60)")
    p.add_argument("--warmup", type=int, default=0,
                   help="Warmup seconds before measuring (default: 0)")
    p.add_argument("--seed", type=int, default=500,
                   help="Documents to seed before test (default: 500)")
    p.add_argument("--index", default=None,
                   help="Custom index name (default: stress-{workload})")
    p.add_argument("--app-name", default=None,
                   help="Custom X-App-Name header (default: stress-{workload})")
    p.add_argument("--gateway", default=_DEFAULT_GATEWAY,
                   help="Gateway base URL (default: %(default)s)")
    p.add_argument("--cleanup", action="store_true",
                   help="Delete stress index after run")
    add_auth_args(p)
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    apply_auth_args(args)

    if args.list:
        print(f"\n  Available workloads ({len(WORKLOADS)}):\n")
        for name, cls in WORKLOADS.items():
            print(f"    {name:<16} {cls.description}")
        print()
        sys.exit(0)

    if not args.workload:
        parser.error("--workload is required (use --list to see options)")
    if args.workload not in WORKLOADS:
        parser.error(f"Unknown workload '{args.workload}'. Use --list.")

    gateway = args.gateway
    index = args.index or f"stress-{args.workload}"
    app_name = args.app_name or f"stress-{args.workload}"

    status, _ = http_request(gateway, "GET", "/")
    if status == 0:
        print(f"  ERROR: Cannot reach gateway at {gateway}", file=sys.stderr)
        sys.exit(1)

    wl_cls = WORKLOADS[args.workload]
    wl = wl_cls(gateway, index, app_name)

    rate_desc = f"{args.rate:,} ops/s" if args.rate > 0 else "unlimited"
    print(f"\n  Gateway:   {gateway}")
    print(f"  Workload:  {args.workload} — {wl_cls.description}")
    print(f"  Index:     {index}")
    print(f"  App name:  {app_name}")
    print(f"  Threads:   {args.threads}")
    print(f"  Rate:      {rate_desc}")
    print(f"  Duration:  {args.duration}s")
    if args.warmup:
        print(f"  Warmup:    {args.warmup}s")
    print()

    ensure_index(gateway, index)
    if args.seed > 0:
        seed_data(gateway, index, wl.tracker, args.seed, app_name)

    metrics = LatencyTracker()
    limiter = RateLimiter(args.rate)
    stop = threading.Event()

    threads = [
        threading.Thread(target=worker_loop,
                         args=(wl, metrics, limiter, stop), daemon=True)
        for _ in range(args.threads)
    ]
    for t in threads:
        t.start()

    if args.warmup > 0:
        _run_warmup(metrics, stop, threads, args.warmup)

    _run_measurement(metrics, stop, threads, args)

    snap = metrics.snapshot()
    print(format_report(snap, label=f"Stress: {args.workload}"))

    print(f"  Kibana filters:")
    print(f"    request.target:                 {index}")
    print(f"    identity.applicative_provider:  {app_name}\n")

    if args.cleanup:
        delete_index(gateway, index)


def _run_warmup(metrics: LatencyTracker, stop: threading.Event,
                threads: list, warmup: int) -> None:
    print(f"  Warming up for {warmup}s ...")
    try:
        deadline = time.monotonic() + warmup
        while time.monotonic() < deadline:
            print(f"\r  [warmup] {metrics.rate:,.0f} ops/s  "
                  f"total: {metrics.total:,}  ", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()
        for t in threads:
            t.join(timeout=5)
        sys.exit(0)
    metrics.reset()
    print("\r  Warmup complete — measuring ...\n")


def _run_measurement(metrics: LatencyTracker, stop: threading.Event,
                     threads: list, args) -> None:
    try:
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            snap = metrics.snapshot()
            line = format_live(snap, args.duration, args.rate, args.threads)
            print(f"\r{line}  ", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n  Interrupted.")

    stop.set()
    for t in threads:
        t.join(timeout=5)


if __name__ == "__main__":
    main()
