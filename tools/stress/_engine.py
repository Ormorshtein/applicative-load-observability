"""Core primitives — rate limiter, document tracker, seeder, worker loop."""

import json
import random
import threading
import time

from _helpers import LOADTEST_MAPPING, http_request, rand_doc, rand_str
from _metrics import LatencyTracker


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Token-bucket rate limiter.  rate <= 0 means unlimited."""

    def __init__(self, rate: float) -> None:
        self.rate = rate
        self._tokens = 0.0
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        if self.rate <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens += (now - self._last) * self.rate
                self._last = now
                self._tokens = min(self._tokens, self.rate)   # cap burst
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            time.sleep(0.0005)


# ---------------------------------------------------------------------------
# Document ID tracker
# ---------------------------------------------------------------------------

class DocIdTracker:
    """Thread-safe rolling buffer of recent document IDs."""

    def __init__(self, max_size: int = 5000) -> None:
        self._ids: list[str] = []
        self._lock = threading.Lock()
        self._max = max_size

    def remember(self, doc_id: str) -> None:
        with self._lock:
            self._ids.append(doc_id)
            if len(self._ids) > self._max:
                self._ids[:] = self._ids[-2000:]

    def pick(self) -> str | None:
        with self._lock:
            return random.choice(self._ids) if self._ids else None


# ---------------------------------------------------------------------------
# Index management & seeding
# ---------------------------------------------------------------------------

def ensure_index(gateway: str, index: str) -> None:
    http_request(gateway, "PUT", f"/{index}", LOADTEST_MAPPING)


def seed_data(gateway: str, index: str, tracker: DocIdTracker,
              count: int, app_name: str) -> None:
    print(f"  Seeding {count} documents into {index} ...", end=" ", flush=True)
    batch_size = 500
    for start in range(0, count, batch_size):
        end = min(start + batch_size, count)
        actions = []
        for _ in range(end - start):
            doc_id = rand_str(12)
            actions.append(json.dumps({"index": {"_index": index, "_id": doc_id}}))
            actions.append(json.dumps(rand_doc()))
            tracker.remember(doc_id)
        body = "\n".join(actions) + "\n"
        http_request(gateway, "POST", "/_bulk", body,
                     headers={"X-App-Name": app_name},
                     content_type="application/x-ndjson", timeout=60)
    http_request(gateway, "POST", f"/{index}/_refresh")
    print("done")


def delete_index(gateway: str, index: str) -> None:
    status, _ = http_request(gateway, "DELETE", f"/{index}")
    print(f"  Deleted index {index} ({status})")


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

def worker_loop(workload, metrics: LatencyTracker, limiter: RateLimiter,
                stop: threading.Event) -> None:
    """Pick a weighted operation, execute, record latency.  Repeat until stop."""
    ops = workload.weighted_operations()
    funcs = [fn for fn, _ in ops]
    weights = [w for _, w in ops]
    while not stop.is_set():
        limiter.acquire()
        if stop.is_set():
            break
        t0 = time.monotonic()
        try:
            op, status = random.choices(funcs, weights=weights, k=1)[0]()
        except Exception:
            op, status = "_error", 0
        latency_ms = (time.monotonic() - t0) * 1000
        metrics.record(op, latency_ms, status)
