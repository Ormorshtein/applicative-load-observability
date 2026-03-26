"""Infrastructure components for the challenge runner.

DocIdTracker, HealthMonitor, worker loop, seeding, and warmup helpers.
These are used by _challenge_runner.py and should not be imported directly
by challenge config modules.
"""

import json
import random
import select
import sys
import threading
import time

from helpers import Stats, http_request, ndjson, rand_doc, rand_str

_DOC_ID_BUFFER_MAX = 5000
_DOC_ID_TRIM_SIZE = 2000
_SEED_BATCH_SIZE = 500
_HEAP_THROTTLE_PCT = 82
_HEAP_RESUME_PCT = 70
_HEALTH_POLL_INTERVAL = 4
_BACKOFF_BASE = 0.5
_BACKOFF_CAP = 5.0


# ---------------------------------------------------------------------------
# Document ID tracker (thread-safe, with write cap)
# ---------------------------------------------------------------------------

class DocIdTracker:
    def __init__(self, max_docs: int = 50_000) -> None:
        self._ids: list[str] = []
        self._lock = threading.Lock()
        self._doc_count = 0
        self._max_docs = max_docs

    def remember(self, doc_id: str) -> None:
        with self._lock:
            self._ids.append(doc_id)
            self._doc_count += 1
            if len(self._ids) > _DOC_ID_BUFFER_MAX:
                self._ids[:] = self._ids[-_DOC_ID_TRIM_SIZE:]

    def pick(self) -> str | None:
        with self._lock:
            return random.choice(self._ids) if self._ids else None

    @property
    def writes_allowed(self) -> bool:
        return self._doc_count < self._max_docs


# ---------------------------------------------------------------------------
# Cluster health monitor — multi-node aware with TUI display
# ---------------------------------------------------------------------------

class NodeHealth:
    __slots__ = ("name", "heap_pct", "cpu_pct")

    def __init__(self, name: str) -> None:
        self.name = name
        self.heap_pct = 0
        self.cpu_pct = 0


class HealthMonitor:
    def __init__(self, gateway: str) -> None:
        self._gateway = gateway
        self.throttle = threading.Event()
        self._nodes: dict[str, NodeHealth] = {}
        self._stop = threading.Event()
        self._consecutive_failures = 0

    @property
    def heap_pct(self) -> int:
        return max((n.heap_pct for n in self._nodes.values()), default=0)

    @property
    def cpu_pct(self) -> int:
        return max((n.cpu_pct for n in self._nodes.values()), default=0)

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._check()
            wait = min(
                _BACKOFF_BASE * (2 ** self._consecutive_failures),
                _BACKOFF_CAP,
            ) if self._consecutive_failures else _HEALTH_POLL_INTERVAL
            self._stop.wait(wait)

    def _check(self) -> None:
        try:
            status, body = http_request(
                self._gateway, "GET", "/_nodes/stats/jvm,os", timeout=5,
            )
            if status != 200:
                self._consecutive_failures += 1
                return
        except Exception:
            self._consecutive_failures += 1
            return

        self._consecutive_failures = 0
        data = json.loads(body)
        for node_id, node in data.get("nodes", {}).items():
            name = node.get("name", node_id[:8])
            jvm = node.get("jvm", {}).get("mem", {})
            os_cpu = node.get("os", {}).get("cpu", {})
            if name not in self._nodes:
                self._nodes[name] = NodeHealth(name)
            self._nodes[name].heap_pct = jvm.get("heap_used_percent", 0)
            self._nodes[name].cpu_pct = os_cpu.get("percent", 0)

        heap_max = self.heap_pct
        if heap_max >= _HEAP_THROTTLE_PCT:
            if not self.throttle.is_set():
                self._print_health("THROTTLING")
            self.throttle.set()
        elif heap_max <= _HEAP_RESUME_PCT and self.throttle.is_set():
            self._print_health("RESUMING")
            self.throttle.clear()

    def _print_health(self, event: str) -> None:
        print(f"\n  [HEALTH] {event}")
        for node in sorted(self._nodes.values(), key=lambda n: n.name):
            heap_bar = _progress_bar(node.heap_pct)
            cpu_bar = _progress_bar(node.cpu_pct)
            print(
                f"    {node.name:<20} "
                f"heap {heap_bar} {node.heap_pct:>3}%  "
                f"cpu {cpu_bar} {node.cpu_pct:>3}%"
            )

    def format_status(self) -> str:
        """Return a multi-line health display for the status command."""
        if not self._nodes:
            return "  [HEALTH] No node data yet"
        lines = ["  [HEALTH] Cluster nodes:"]
        for node in sorted(self._nodes.values(), key=lambda n: n.name):
            heap_bar = _progress_bar(node.heap_pct)
            cpu_bar = _progress_bar(node.cpu_pct)
            lines.append(
                f"    {node.name:<20} "
                f"heap {heap_bar} {node.heap_pct:>3}%  "
                f"cpu {cpu_bar} {node.cpu_pct:>3}%"
            )
        return "\n".join(lines)


def _progress_bar(pct: int, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def run_worker(
    ops: list,
    weights: list[float],
    think_ms: int,
    gw: str,
    tracker: DocIdTracker,
    stats: Stats,
    stop: threading.Event,
    monitor: HealthMonitor,
) -> None:
    """Execute weighted operations in a loop until stopped."""
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

def seed_data(
    gateway: str,
    index: str,
    tracker: DocIdTracker,
    count: int,
    doc_fn: callable = None,
) -> None:
    """Seed the index with random documents."""
    doc_fn = doc_fn or rand_doc
    print(f"  Seeding {count} documents ...", flush=True)
    for start in range(0, count, _SEED_BATCH_SIZE):
        end = min(start + _SEED_BATCH_SIZE, count)
        actions: list[str] = []
        for _ in range(end - start):
            did = rand_str(12)
            actions.append(json.dumps({"index": {"_index": index, "_id": did}}))
            actions.append(json.dumps(doc_fn()))
            tracker.remember(did)
        s, _ = http_request(
            gateway, "POST", "/_bulk",
            ndjson(actions),
            content_type="application/x-ndjson", timeout=30,
        )
        print(f"    batch {start}-{end}: {s}", flush=True)
    http_request(gateway, "POST", f"/{index}/_refresh")
    print("  Seeding complete.")


def warmup_scripts(gateway: str, script_builders: tuple | list | None) -> None:
    """Run each script query once to force Painless compilation."""
    if not script_builders:
        return
    print("  Warming up Painless scripts ...", end=" ", flush=True)
    tr = DocIdTracker()
    for fn in script_builders:
        fn(gateway, tr)
    print("done.")


def stdin_ready() -> bool:
    """Check if stdin has input waiting (cross-platform)."""
    if sys.platform == "win32":
        import msvcrt
        return msvcrt.kbhit()
    return bool(select.select([sys.stdin], [], [], 0)[0])
