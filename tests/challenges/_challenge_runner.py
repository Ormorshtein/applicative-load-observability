"""Unified runner for all ALO interactive challenges.

Orchestrates challenge setup, interactive loop, and summary.
Infrastructure (DocIdTracker, HealthMonitor, worker) lives in _challenge_infra.

Config module protocol
----------------------
Required attributes:
    INDEX              (str)   — Elasticsearch index name
    CULPRIT            (str)   — task/app name that is the stress source
    TASK_CONFIGS       (list)  — [(name, workers, think_ms, [(op_fn, weight), ...])]
    SCRIPT_BUILDERS    (tuple) — functions to call for Painless warmup
    DESCRIPTION        (str)   — CLI help text
    HINT               (str)   — hint shown at challenge start
    CULPRIT_EXPLANATION (str)  — shown when user finds culprit
    MISS_EXPLANATION   (str)   — shown when user quits without finding culprit

Optional attributes:
    APP_NAME           (str)   — single app name (omit for multi-app challenges)
    MAPPING            (dict)  — override LOADTEST_MAPPING
    SEED_DOC_FN        (callable) — override rand_doc for seeding
    MAX_DOCS           (int)   — override CLI --max-docs

Operation signature: ``fn(gw, tracker) -> (op_name, status)``
"""

import argparse
import os
import sys
import threading
import time

from _challenge_infra import (
    DocIdTracker,
    HealthMonitor,
    run_worker,
    seed_data,
    stdin_ready,
    warmup_scripts,
)
from helpers import LOADTEST_MAPPING, Stats, add_auth_args, apply_auth_args, http_request

_DEFAULT_GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:9200")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def _setup_challenge(
    gateway: str, seed_count: int, max_docs: int, config: object, scale: int,
) -> tuple:
    """Create index, seed data, and build worker threads."""
    index = config.INDEX
    task_configs = config.TASK_CONFIGS
    max_docs = getattr(config, "MAX_DOCS", None) or max_docs
    tracker = DocIdTracker(max_docs=max_docs)
    monitor = HealthMonitor(gateway)

    print(f"\n  Gateway:   {gateway}")
    print(f"  Index:     {index}    Max docs: {max_docs}    Scale: {scale}x\n")

    status, _ = http_request(gateway, "GET", "/")
    if status == 0:
        print(f"  ERROR: Cannot reach gateway at {gateway}", file=sys.stderr)
        sys.exit(1)
    print(f"  Gateway reachable (HTTP {status})")

    mapping = getattr(config, "MAPPING", LOADTEST_MAPPING)
    http_request(gateway, "PUT", f"/{index}", mapping)
    doc_fn = getattr(config, "SEED_DOC_FN", None)
    seed_data(gateway, index, tracker, seed_count, doc_fn)
    warmup_scripts(gateway, config.SCRIPT_BUILDERS)

    task_names = [name for name, *_ in task_configs]
    stats = {n: Stats() for n in task_names}
    stops = {n: threading.Event() for n in task_names}
    threads: dict[str, list[threading.Thread]] = {}

    total_w = 0
    for name, workers, think_ms, op_defs in task_configs:
        scaled = workers * scale
        ops = [fn for fn, _ in op_defs]
        wts = [w for _, w in op_defs]
        ts = [
            threading.Thread(
                target=run_worker, daemon=True,
                args=(ops, wts, think_ms, gateway, tracker,
                      stats[name], stops[name], monitor),
            )
            for _ in range(scaled)
        ]
        threads[name] = ts
        total_w += scaled

    app_name = getattr(config, "APP_NAME", None)
    app_label = f" under app '{app_name}'" if app_name else ""
    print(f"\n  Starting {len(task_configs)} services ({total_w} workers){app_label} ...")
    for name, workers, _, _ in task_configs:
        print(f"    {name:<25} {workers * scale} workers")

    return tracker, monitor, task_names, stats, stops, threads


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------

def _run_interactive_loop(
    task_names: list[str],
    stats: dict[str, Stats],
    stops: dict[str, threading.Event],
    threads: dict[str, list[threading.Thread]],
    tracker: DocIdTracker,
    monitor: HealthMonitor,
    culprit: str,
    hint: str | None,
) -> tuple[set[str], list[str], bool, float]:
    """Run the interactive input loop."""
    n_tasks = len(task_names)
    print(f"\n  Something is killing your cluster. Find the bad service.")
    if hint:
        print(f"  {hint}")
    print("  Commands: <service-name> to stop | status | health | quit")
    print("  Runs until you type 'quit' or press Ctrl+C\n")

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
                f"({tot / max(el, .1):.0f} r/s) "
                f"cpu:{monitor.cpu_pct}% heap:{monitor.heap_pct}% "
                f"running:{running}/{n_tasks}"
                f"{throttled}{cap}  "
            )
            sys.stdout.flush()

            if not stdin_ready():
                time.sleep(0.5)
                continue

            line = sys.stdin.readline().strip().lower()
            if line == "quit":
                print("\n  Quitting...")
                break
            elif line == "status":
                _print_status(task_names, stopped, monitor)
            elif line == "health":
                print(f"\n{monitor.format_status()}\n")
            elif line in task_name_set:
                found = _handle_stop_command(
                    line, culprit, stops, threads, stopped, guesses, found,
                )
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
    print(f"\n{monitor.format_status()}\n")


def _handle_stop_command(
    name: str,
    culprit: str,
    stops: dict[str, threading.Event],
    threads: dict[str, list[threading.Thread]],
    stopped: set[str],
    guesses: list[str],
    found: bool,
) -> bool:
    """Stop a service and check if it's the culprit."""
    if name in stopped:
        print(f"\n  '{name}' already stopped.\n")
        return found
    stops[name].set()
    for t in threads[name]:
        t.join(timeout=5)
    stopped.add(name)
    if name == culprit:
        print(f"\n  Stopped '{name}'. Watch the CPU - did it drop?\n")
        return True
    guesses.append(name)
    print(f"\n  Stopped '{name}'. CPU unchanged? Try another.\n")
    return found


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_challenge(
    gateway: str, seed_count: int, max_docs: int, config: object, scale: int = 1,
) -> None:
    """Run the interactive challenge loop."""
    tracker, monitor, task_names, stats, stops, threads = _setup_challenge(
        gateway, seed_count, max_docs, config, scale,
    )

    stopped, guesses, found, start_time = _run_interactive_loop(
        task_names, stats, stops, threads, tracker, monitor,
        config.CULPRIT, config.HINT,
    )

    monitor.stop()
    for e in stops.values():
        e.set()
    for ts in threads.values():
        for t in ts:
            t.join(timeout=5)

    _print_summary(
        task_names, stats, stopped, guesses, found,
        start_time, config.CULPRIT,
        config.CULPRIT_EXPLANATION, config.MISS_EXPLANATION,
    )

    print(f"\n  Cleaning up '{config.INDEX}' ...", end=" ", flush=True)
    s, _ = http_request(gateway, "DELETE", f"/{config.INDEX}")
    print(f"done ({s})\n")


def _print_summary(
    task_names: list[str],
    stats: dict[str, Stats],
    stopped: set[str],
    guesses: list[str],
    found: bool,
    start_time: float,
    culprit: str,
    culprit_explanation: str,
    miss_explanation: str,
) -> None:
    print(f"\n{'=' * 60}\n  Challenge Results\n{'=' * 60}")
    for name in task_names:
        st = stats[name]
        el = time.time() - st.start
        state = "STOPPED" if name in stopped else "running"
        print(
            f"  {name:<25} {st.total:>6} reqs "
            f"({st.total / max(el, .1):>5.0f} r/s) [{state}]"
        )
    print(f"{'=' * 60}")
    if found:
        n_guesses = len(guesses)
        if n_guesses == 0:
            print(f"\n  Perfect! Found '{culprit}' on the first try!")
        else:
            wrong = ", ".join(guesses)
            print(f"\n  Correct! '{culprit}' was the stress source.")
            print(f"  Found in {n_guesses + 1} guesses (wrong: {wrong})")
        print(f"\n  {culprit_explanation}")
    else:
        print(f"\n  The stress source was: {culprit}")
        print(f"  {miss_explanation}")
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main_cli(config: object) -> None:
    """Standard CLI for any ALO challenge."""
    parser = argparse.ArgumentParser(description=config.DESCRIPTION)
    parser.add_argument(
        "--gateway", default=_DEFAULT_GATEWAY,
        help="Gateway base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--seed", type=int, default=10_000,
        help="Number of seed documents (default: %(default)s)",
    )
    parser.add_argument(
        "--max-docs", type=int, default=50_000,
        help="Stop writing after N docs (default: %(default)s)",
    )
    parser.add_argument(
        "--scale", type=int, default=1,
        help="Worker multiplier for larger clusters (default: %(default)s)",
    )
    add_auth_args(parser)
    args = parser.parse_args()
    apply_auth_args(args)
    run_challenge(
        args.gateway, args.seed * args.scale, args.max_docs * args.scale,
        config, args.scale,
    )
