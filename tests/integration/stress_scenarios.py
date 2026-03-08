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
import os
import sys
import threading
import time

from helpers import Stats, http_request
from _scenarios import _SCENARIOS


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------

class ScenarioRunner:
    def __init__(self, gateway: str, duration: int,
                 stress_workers: int, noise_workers: int,
                 cleanup: bool) -> None:
        self.gateway = gateway
        self.duration = duration
        self.stress_workers = stress_workers
        self.noise_workers = noise_workers
        self.cleanup = cleanup

    def run(self, scenario_cls: type) -> None:
        sc = scenario_cls(self.gateway)
        print(f"\n{'#' * 60}")
        print(f"  Scenario: {sc.name}")
        print(f"  {sc.description}")
        print(f"  Index: {sc.index}")
        print(f"  Stress workers: {self.stress_workers}  |  Noise workers: {self.noise_workers}")
        print(f"  Duration: {self.duration}s")
        print(f"{'#' * 60}\n")

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

    def run_mix(self, scenario_classes: list[type]) -> None:
        scenarios = [cls(self.gateway) for cls in scenario_classes]
        names = ", ".join(sc.name for sc in scenarios)

        print(f"\n{'#' * 60}")
        print(f"  MIX MODE — {len(scenarios)} scenarios in parallel")
        print(f"  Scenarios: {names}")
        print(f"  Stress workers per scenario: {self.stress_workers}")
        print(f"  Noise workers per scenario: {self.noise_workers}")
        print(f"  Duration: {self.duration}s")
        print(f"  Total threads: {len(scenarios) * (self.stress_workers + self.noise_workers)}")
        print(f"{'#' * 60}\n")

        sc_stats = {sc.name: Stats() for sc in scenarios}

        for sc in scenarios:
            sc.ensure_index()
            sc.seed_data(500)

        stop = threading.Event()
        threads = []

        for sc in scenarios:
            stats = sc_stats[sc.name]

            def make_stress(s=sc, st=stats):
                def _worker():
                    while not stop.is_set():
                        try:
                            op, status = s.stress_op()
                            st.record(op, status)
                        except Exception:
                            st.record("stress:error", 0)
                return _worker

            def make_noise(s=sc, st=stats):
                def _worker():
                    while not stop.is_set():
                        try:
                            op, status = s.noise_op()
                            st.record(op, status)
                        except Exception:
                            st.record("noise:error", 0)
                        time.sleep(0.05)
                return _worker

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

def main() -> None:
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
    parser.add_argument("--gateway",
                        default=os.getenv("GATEWAY_URL", "http://localhost:9200"),
                        help="Gateway base URL (default: %(default)s)")
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
    status, _ = http_request(args.gateway, "GET", "/")
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
