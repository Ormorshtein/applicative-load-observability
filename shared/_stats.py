"""Thread-safe stats and latency tracking utilities."""

import threading
import time
from collections import defaultdict


def percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile on a pre-sorted list."""
    if not sorted_vals:
        return 0.0
    k = (pct / 100) * (len(sorted_vals) - 1)
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (k - lo) * (sorted_vals[hi] - sorted_vals[lo])


class LatencyTracker:
    """Thread-safe per-operation latency recorder with percentile computation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: dict[str, list[float]] = defaultdict(list)

    def record(self, operation: str, elapsed_ms: float) -> None:
        with self._lock:
            self._samples[operation].append(elapsed_ms)

    def percentile(self, operation: str, pct: float) -> float:
        with self._lock:
            data = sorted(self._samples.get(operation, []))
        return percentile(data, pct)

    def count(self, operation: str) -> int:
        with self._lock:
            return len(self._samples.get(operation, []))

    def sorted_samples(self, operation: str) -> list[float]:
        """Return a sorted copy of samples for an operation."""
        with self._lock:
            return sorted(self._samples.get(operation, []))


class Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counts: dict[str, int] = defaultdict(int)
        self.errors: dict[str, int] = defaultdict(int)
        self.total: int = 0
        self.start: float = time.time()

    def record(self, operation: str, status: int) -> None:
        with self._lock:
            self.total += 1
            self.counts[operation] += 1
            if status == 0 or status >= 400:
                self.errors[operation] += 1

    def report(self, label: str = "") -> None:
        elapsed = time.time() - self.start
        title = f"  {label}  ({elapsed:.1f}s)" if label else f"  Results  ({elapsed:.1f}s)"
        print(f"\n{'=' * 60}")
        print(title)
        print(f"{'=' * 60}")
        print(f"  Total requests:  {self.total}")
        print(f"  Throughput:      {self.total / max(elapsed, 0.1):.1f} req/s")
        print(f"{'=' * 60}")
        print(f"  {'Operation':<25} {'Count':>8} {'Errors':>8}")
        print(f"  {'-' * 41}")
        for op in sorted(self.counts):
            print(f"  {op:<25} {self.counts[op]:>8} {self.errors.get(op, 0):>8}")
        total_errors = sum(self.errors.values())
        print(f"  {'-' * 41}")
        print(f"  {'TOTAL':<25} {self.total:>8} {total_errors:>8}")
        print(f"{'=' * 60}\n")
