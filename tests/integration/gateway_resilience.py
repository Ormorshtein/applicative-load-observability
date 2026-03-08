#!/usr/bin/env python3
"""
Gateway resilience tests for the applicative-load-observability stack.

Proves empirically that:
  1. The OpenResty gateway adds negligible latency vs direct ES access
  2. Logstash failures never block data reaching Elasticsearch
  3. Gateway overhead scales linearly under concurrent load

Usage:
    python tests/integration/gateway_resilience.py
    python tests/integration/gateway_resilience.py --skip scaling
    python tests/integration/gateway_resilience.py --cleanup
"""

import argparse
import os
import sys
from pathlib import Path

from helpers import http_request
from _resilience import (
    cleanup_indices,
    run_integrity_test,
    run_overhead_test,
    run_scaling_test,
)

_DEFAULT_GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:9200")
_DEFAULT_DIRECT_ES = os.getenv("DIRECT_ES_URL", "http://127.0.0.1:9201")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gateway resilience tests")
    parser.add_argument(
        "--gateway", default=_DEFAULT_GATEWAY,
        help="Gateway URL (default: %(default)s)",
    )
    parser.add_argument(
        "--direct-es", default=_DEFAULT_DIRECT_ES,
        help="Direct ES URL (default: %(default)s)",
    )
    parser.add_argument(
        "--iterations", type=int, default=50,
        help="Iterations per operation for overhead test (default: %(default)s)",
    )
    parser.add_argument(
        "--integrity-docs", type=int, default=50,
        help="Docs per phase for integrity test (default: %(default)s)",
    )
    parser.add_argument(
        "--scale-workers", default="1,4,8",
        help="Comma-separated worker counts (default: %(default)s)",
    )
    parser.add_argument(
        "--scale-duration", type=int, default=15,
        help="Seconds per scaling round (default: %(default)s)",
    )
    parser.add_argument(
        "--max-overhead-p50", type=float, default=15.0,
        help="Max acceptable p50 overhead %% (default: %(default)s)",
    )
    parser.add_argument(
        "--max-overhead-p95", type=float, default=25.0,
        help="Max acceptable p95 overhead %% (default: %(default)s)",
    )
    parser.add_argument(
        "--compose-dir", default=str(_PROJECT_ROOT),
        help="Docker compose project dir (default: %(default)s)",
    )
    parser.add_argument(
        "--skip", default="",
        help="Comma-separated tests to skip: overhead,integrity,scaling",
    )
    parser.add_argument(
        "--cleanup", action="store_true",
        help="Delete test indices after run",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    worker_counts = [int(x) for x in args.scale_workers.split(",")]

    print(f"\n  Gateway:    {args.gateway}")
    print(f"  Direct ES:  {args.direct_es}")
    print(f"  Compose:    {args.compose_dir}")

    for label, url in [("Gateway", args.gateway), ("Direct ES", args.direct_es)]:
        status, _ = http_request(url, "GET", "/")
        if status == 0:
            print(f"\n  ERROR: Cannot reach {label} at {url}", file=sys.stderr)
            sys.exit(1)
        print(f"  {label} reachable (HTTP {status})")

    results: dict[str, bool] = {}

    if "overhead" not in skip:
        results["overhead"] = run_overhead_test(
            args.gateway, args.direct_es,
            args.iterations, args.max_overhead_p50, args.max_overhead_p95,
        )

    if "integrity" not in skip:
        results["integrity"] = run_integrity_test(
            args.gateway, args.direct_es,
            args.integrity_docs, args.compose_dir,
        )

    if "scaling" not in skip:
        results["scaling"] = run_scaling_test(
            args.gateway, args.direct_es,
            worker_counts, args.scale_duration,
        )

    if args.cleanup:
        print(f"\n{'=' * 60}")
        print("  Cleanup")
        print(f"{'=' * 60}")
        cleanup_indices(args.direct_es)

    print(f"\n{'=' * 60}")
    print("  Summary")
    print(f"{'=' * 60}")
    for name, passed in results.items():
        print(f"  {name:<15} {'PASS' if passed else 'FAIL'}")
    print(f"{'=' * 60}\n")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
