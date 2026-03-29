"""Latency tracking and live reporting for the stress engine."""

import time
from collections import defaultdict

from _helpers import LatencyTracker as _BaseTracker
from _helpers import _percentile


def _fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.2f}s"
    return f"{ms:.1f}ms"


# ---------------------------------------------------------------------------
# Extended tracker with error tracking and snapshots
# ---------------------------------------------------------------------------

class LatencyTracker(_BaseTracker):
    """Thread-safe per-operation latency and error tracker."""

    MAX_ERROR_SAMPLES = 10

    def __init__(self) -> None:
        super().__init__()
        self._counts: dict[str, int] = defaultdict(int)
        self._errors: dict[str, int] = defaultdict(int)
        self._error_samples: list[tuple[str, int, str]] = []
        self._total = 0
        self._total_errors = 0
        self.start = time.monotonic()

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._counts.clear()
            self._errors.clear()
            self._error_samples.clear()
            self._total = 0
            self._total_errors = 0
            self.start = time.monotonic()

    @property
    def total(self) -> int:
        return self._total

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start

    @property
    def rate(self) -> float:
        e = self.elapsed
        return self._total / e if e > 0.01 else 0.0

    def record_with_status(
        self, op: str, latency_ms: float, status: int, body: bytes = b"",
    ) -> None:
        """Record latency plus status/error tracking."""
        is_err = status == 0 or status >= 400
        with self._lock:
            self._samples[op].append(latency_ms)
            self._counts[op] += 1
            self._total += 1
            if is_err:
                self._errors[op] += 1
                self._total_errors += 1
                if len(self._error_samples) < self.MAX_ERROR_SAMPLES:
                    snippet = body.decode("utf-8", errors="replace")[:512] if body else ""
                    self._error_samples.append((op, status, snippet))

    def snapshot(self) -> dict:
        with self._lock:
            ops = {}
            for op in sorted(self._counts):
                lats = sorted(self._samples.get(op, []))
                ops[op] = {
                    "count": self._counts[op],
                    "errors": self._errors[op],
                    "p50": _percentile(lats, 50),
                    "p95": _percentile(lats, 95),
                    "p99": _percentile(lats, 99),
                    "max": lats[-1] if lats else 0.0,
                }
            elapsed = time.monotonic() - self.start
            return {
                "ops": ops,
                "total": self._total,
                "errors": self._total_errors,
                "error_samples": list(self._error_samples),
                "elapsed": elapsed,
                "rate": self._total / max(elapsed, 0.01),
            }


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def format_live(snap: dict, duration: int, target_rate: int, threads: int) -> str:
    """Single-line live progress for terminal overwrite."""
    e, r, t = snap["elapsed"], snap["rate"], snap["total"]
    err = snap["errors"]
    err_pct = (err / t * 100) if t else 0.0
    rate_part = f"{r:,.0f} ops/s"
    if target_rate > 0:
        rate_part += f" (target: {target_rate:,})"
    return (f"  [{e:.0f}s / {duration}s]  threads: {threads}  |  "
            f"{rate_part}  |  total: {t:,}  |  errors: {err_pct:.1f}%")


def format_report(snap: dict, label: str = "") -> str:
    """Detailed final report with per-operation latency percentiles."""
    e = snap["elapsed"]
    title = f"  {label}  ({e:.1f}s)" if label else f"  Results  ({e:.1f}s)"
    w = 80
    sep = "=" * w
    lines = [
        f"\n{sep}", title, sep,
        f"  Total ops:    {snap['total']:>12,}",
        f"  Throughput:   {snap['rate']:>12,.1f} ops/s",
        f"  Errors:       {snap['errors']:>12,}",
        sep,
        f"  {'Operation':<24} {'Count':>9} {'Err':>6}"
        f"  {'p50':>8} {'p95':>8} {'p99':>8} {'Max':>8}",
        f"  {'-' * (w - 4)}",
    ]
    for op, s in snap["ops"].items():
        lines.append(
            f"  {op:<24} {s['count']:>9,} {s['errors']:>6}"
            f"  {_fmt_ms(s['p50']):>8} {_fmt_ms(s['p95']):>8}"
            f"  {_fmt_ms(s['p99']):>8} {_fmt_ms(s['max']):>8}"
        )
    lines.extend([
        f"  {'-' * (w - 4)}",
        f"  {'TOTAL':<24} {snap['total']:>9,} {snap['errors']:>6}",
        sep,
    ])
    if snap.get("error_samples"):
        lines.append(f"\n  Error samples (first {len(snap['error_samples'])}):")
        lines.append(f"  {'-' * (w - 4)}")
        for op, status, snippet in snap["error_samples"]:
            status_label = f"HTTP {status}" if status else "connection error"
            lines.append(f"  [{op}] {status_label}: {snippet}")
        lines.append(sep)
    lines.append("")
    return "\n".join(lines)
