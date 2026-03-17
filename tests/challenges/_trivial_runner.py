"""Shared runner for trivial load challenges.

Provides the interactive challenge loop, cluster health monitoring,
document tracking, and CLI entry point shared by all trivial challenges.
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
    LOADTEST_MAPPING, Stats, add_auth_args, apply_auth_args, http_request,
    rand_doc, rand_str,
)


_DEFAULT_GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:9200")


# ---------------------------------------------------------------------------
# Document ID tracker (thread-safe, with write cap)
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
# Cluster health monitor
# ---------------------------------------------------------------------------

class HealthMonitor:
    HEAP_THROTTLE_PCT = 82
    HEAP_RESUME_PCT = 70

    def __init__(self, gateway: str) -> None:
        self._gateway = gateway
        self.throttle = threading.Event()
        self.heap_pct: int = 0
        self.cpu_pct: int = 0
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._check()
            self._stop.wait(4)

    def _check(self) -> None:
        try:
            s, body = http_request(
                self._gateway, "GET", "/_nodes/stats/jvm,os", timeout=5)
            if s != 200:
                return
            for node in json.loads(body).get("nodes", {}).values():
                self.heap_pct = node.get("jvm", {}).get(
                    "mem", {}).get("heap_used_percent", 0)
                self.cpu_pct = node.get("os", {}).get(
                    "cpu", {}).get("percent", 0)
        except Exception:
            return
        if self.heap_pct >= self.HEAP_THROTTLE_PCT:
            if not self.throttle.is_set():
                print(f"\n  [MONITOR] Heap {self.heap_pct}% — throttling")
            self.throttle.set()
        elif self.heap_pct <= self.HEAP_RESUME_PCT and self.throttle.is_set():
            print(f"\n  [MONITOR] Heap {self.heap_pct}% — resuming")
            self.throttle.clear()


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _run_worker(
    ops: list, weights: list[float], think_ms: int,
    gw: str, tracker: DocIdTracker, stats: Stats,
    stop: threading.Event, monitor: HealthMonitor,
) -> None:
    while not stop.is_set():
        if monitor.throttle.is_set():
            time.sleep(0.5)
            continue
        try:
            fn = random.choices(ops, weights=weights, k=1)[0]
            op, status = fn(gw, tracker)
            stats.record(op, status)
            if status == 0 or status >= 429:
                time.sleep(0.2)
            elif think_ms > 0:
                time.sleep(think_ms / 1000.0)
        except Exception:
            stats.record("_error", 0)
            time.sleep(0.1)


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def _seed_data(
    gateway: str, index: str, tracker: DocIdTracker,
    count: int, doc_fn: callable = None,
) -> None:
    doc_fn = doc_fn or rand_doc
    print(f"  Seeding {count} documents ...", flush=True)
    for start in range(0, count, 500):
        end = min(start + 500, count)
        actions = []
        for _ in range(end - start):
            did = rand_str(12)
            actions.append(json.dumps(
                {"index": {"_index": index, "_id": did}}))
            actions.append(json.dumps(doc_fn()))
            tracker.remember(did)
        s, _ = http_request(gateway, "POST", "/_bulk",
                            "\n".join(actions) + "\n",
                            content_type="application/x-ndjson", timeout=30)
        print(f"    batch {start}-{end}: {s}", flush=True)
    http_request(gateway, "POST", f"/{index}/_refresh")
    print("  Seeding complete.")


def _warmup_scripts(gateway: str, script_builders: list | None) -> None:
    if not script_builders:
        return
    print("  Warming up Painless scripts ...", end=" ", flush=True)
    tr = DocIdTracker()
    for fn in script_builders:
        fn(gateway, tr)
    print("done.")


def _stdin_ready() -> bool:
    if sys.platform == "win32":
        import msvcrt
        return msvcrt.kbhit()
    return bool(select.select([sys.stdin], [], [], 0)[0])


# ---------------------------------------------------------------------------
# Interactive challenge
# ---------------------------------------------------------------------------

def _setup_challenge(
    gateway: str, seed_count: int, max_docs: int, config, scale: int,
) -> tuple[DocIdTracker, HealthMonitor, list[str], dict[str, Stats],
           dict[str, threading.Event], dict[str, list[threading.Thread]]]:
    """Create index, seed data, and build worker threads.

    Returns tracker, monitor, task_names, stats, stops, threads.
    """
    index = config.INDEX
    task_configs = config.TASK_CONFIGS
    max_docs = getattr(config, "MAX_DOCS", None) or max_docs
    tracker = DocIdTracker(max_docs=max_docs)
    monitor = HealthMonitor(gateway)

    print(f"\n  Gateway:   {gateway}")
    print(f"  Index:     {index}    Max docs: {max_docs}"
          f"    Scale: {scale}x\n")

    status, _ = http_request(gateway, "GET", "/")
    if status == 0:
        print(f"  ERROR: Cannot reach gateway at {gateway}", file=sys.stderr)
        sys.exit(1)
    print(f"  Gateway reachable (HTTP {status})")

    mapping = getattr(config, "MAPPING", LOADTEST_MAPPING)
    http_request(gateway, "PUT", f"/{index}", mapping)
    doc_fn = getattr(config, "SEED_DOC_FN", None)
    _seed_data(gateway, index, tracker, seed_count, doc_fn)
    _warmup_scripts(gateway, config.SCRIPT_BUILDERS)

    task_names = [name for name, *_ in task_configs]
    stats = {n: Stats() for n in task_names}
    stops = {n: threading.Event() for n in task_names}
    threads: dict[str, list[threading.Thread]] = {}

    total_w = 0
    for name, workers, think_ms, op_defs in task_configs:
        scaled_workers = workers * scale
        ops = [fn for fn, _ in op_defs]
        wts = [w for _, w in op_defs]
        ts = [threading.Thread(target=_run_worker, daemon=True,
              args=(ops, wts, think_ms, gateway, tracker,
                    stats[name], stops[name], monitor))
              for _ in range(scaled_workers)]
        threads[name] = ts
        total_w += scaled_workers

    print(f"\n  Starting {len(task_configs)} services ({total_w} workers) "
          f"under app '{config.APP_NAME}' ...")
    for name, workers, _, _ in task_configs:
        print(f"    {name:<25} {workers * scale} workers")

    return tracker, monitor, task_names, stats, stops, threads


def _run_interactive_loop(
    task_names: list[str], stats: dict[str, Stats],
    stops: dict[str, threading.Event],
    threads: dict[str, list[threading.Thread]],
    tracker: DocIdTracker, monitor: HealthMonitor, culprit: str,
    hint: str | None,
) -> tuple[set[str], list[str], bool, float]:
    """Run the interactive input loop. Returns stopped, guesses, found, start_time."""
    n_tasks = len(task_names)
    print(f"\n  Something is killing your cluster. Find the bad service.")
    if hint:
        print(f"  {hint}")
    print(f"  Commands: <service-name> to stop | status | quit")
    print(f"  Runs until you type 'quit' or press Ctrl+C\n")

    monitor.start()
    for ts in threads.values():
        for t in ts:
            t.start()

    stopped: set[str] = set()
    guesses: list[str] = []
    found = False
    start_time = time.time()
    task_name_set = set(task_names)

    try:
        while True:
            el = time.time() - start_time
            tot = sum(s.total for s in stats.values())
            throttled = " [THROTTLED]" if monitor.throttle.is_set() else ""
            cap = " [WRITES CAPPED]" if not tracker.writes_allowed else ""
            running = n_tasks - len(stopped)
            sys.stdout.write(
                f"\r  [{el:.0f}s] reqs:{tot} "
                f"({tot/max(el,.1):.0f} r/s) "
                f"cpu:{monitor.cpu_pct}% heap:{monitor.heap_pct}% "
                f"running:{running}/{n_tasks}"
                f"{throttled}{cap}  ")
            sys.stdout.flush()

            if not _stdin_ready():
                time.sleep(0.5)
                continue

            line = sys.stdin.readline().strip().lower()
            if line == "quit":
                print("\n  Quitting...")
                break
            elif line == "status":
                _print_status(task_names, stopped, monitor)
            elif line in task_name_set:
                found = _handle_stop_command(
                    line, culprit, stops, threads, stopped, guesses, found)
            elif line:
                print(f"\n  Unknown: '{line}'.")
                print(f"  Services: {', '.join(task_names)}\n")
    except KeyboardInterrupt:
        print("\n\n  Interrupted.")

    return stopped, guesses, found, start_time


def _print_status(
    task_names: list[str], stopped: set[str], monitor: HealthMonitor,
) -> None:
    print()
    for name in task_names:
        state = "STOPPED" if name in stopped else "running"
        print(f"    {name:<25} [{state}]")
    print(f"  ES cpu: {monitor.cpu_pct}%  heap: {monitor.heap_pct}%")
    print()


def _handle_stop_command(
    name: str, culprit: str,
    stops: dict[str, threading.Event],
    threads: dict[str, list[threading.Thread]],
    stopped: set[str], guesses: list[str], found: bool,
) -> bool:
    """Stop a service and check if it's the culprit. Returns updated `found`."""
    if name in stopped:
        print(f"\n  '{name}' already stopped.\n")
        return found
    stops[name].set()
    for t in threads[name]:
        t.join(timeout=5)
    stopped.add(name)
    if name == culprit:
        print(f"\n  Stopped '{name}'. Watch the CPU — did it drop?\n")
        return True
    guesses.append(name)
    print(f"\n  Stopped '{name}'. CPU unchanged? Try another.\n")
    return found


def run_challenge(
    gateway: str, seed_count: int, max_docs: int, config, scale: int = 1,
) -> None:
    """Run the interactive challenge loop.

    *config* is a module exposing: INDEX, APP_NAME, CULPRIT, TASK_CONFIGS,
    SCRIPT_BUILDERS, DESCRIPTION, HINT, CULPRIT_EXPLANATION, MISS_EXPLANATION.
    Optional: MAPPING (overrides LOADTEST_MAPPING), SEED_DOC_FN (overrides rand_doc),
    MAX_DOCS (overrides CLI --max-docs).
    """
    tracker, monitor, task_names, stats, stops, threads = _setup_challenge(
        gateway, seed_count, max_docs, config, scale)

    stopped, guesses, found, start_time = _run_interactive_loop(
        task_names, stats, stops, threads, tracker, monitor,
        config.CULPRIT, config.HINT)

    monitor.stop()
    for e in stops.values():
        e.set()
    for ts in threads.values():
        for t in ts:
            t.join(timeout=5)

    _print_summary(task_names, stats, stopped, guesses, found,
                   start_time, config.CULPRIT,
                   config.CULPRIT_EXPLANATION, config.MISS_EXPLANATION)

    print(f"\n  Cleaning up '{config.INDEX}' ...", end=" ", flush=True)
    s, _ = http_request(gateway, "DELETE", f"/{config.INDEX}")
    print(f"done ({s})\n")


def _print_summary(
    task_names: list[str], stats: dict[str, Stats],
    stopped: set[str], guesses: list[str], found: bool,
    start_time: float, culprit: str,
    culprit_explanation: str, miss_explanation: str,
) -> None:
    print(f"\n{'='*60}\n  Challenge Results\n{'='*60}")
    for name in task_names:
        st = stats[name]
        el = time.time() - st.start
        state = "STOPPED" if name in stopped else "running"
        print(f"  {name:<25} {st.total:>6} reqs "
              f"({st.total/max(el,.1):>5.0f} r/s) [{state}]")
    print(f"{'='*60}")
    if found:
        n_guesses = len(guesses)
        if n_guesses == 0:
            print(f"\n  Perfect! Found '{culprit}' on the first try!")
        else:
            wrong = ", ".join(guesses)
            print(f"\n  Correct! '{culprit}' was the stress source.")
            print(f"  Found in {n_guesses + 1} guesses "
                  f"(wrong: {wrong})")
        print(f"\n  {culprit_explanation}")
    else:
        print(f"\n  The stress source was: {culprit}")
        print(f"  {miss_explanation}")
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main_cli(config) -> None:
    """Standard CLI for a trivial load challenge."""
    parser = argparse.ArgumentParser(description=config.DESCRIPTION)
    parser.add_argument("--gateway", default=_DEFAULT_GATEWAY,
                        help="Gateway base URL (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=10000,
                        help="Number of seed documents (default: %(default)s)")
    parser.add_argument("--max-docs", type=int, default=50000,
                        help="Stop writing after N docs (default: %(default)s)")
    parser.add_argument("--scale", type=int, default=1,
                        help="Worker multiplier for larger clusters (default: %(default)s)")
    add_auth_args(parser)
    args = parser.parse_args()
    apply_auth_args(args)
    run_challenge(args.gateway, args.seed * args.scale, args.max_docs * args.scale,
                  config, args.scale)
