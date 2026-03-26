"""Unit tests for challenge infrastructure components."""

import json
import threading
from unittest.mock import patch

import pytest

import sys
from pathlib import Path

# Add challenges dir to path so we can import _challenge_infra
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "challenges"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "integration"))

from _challenge_infra import DocIdTracker, HealthMonitor, _progress_bar


# ---------------------------------------------------------------------------
# DocIdTracker
# ---------------------------------------------------------------------------

class TestDocIdTracker:
    def test_remember_and_pick(self):
        tr = DocIdTracker()
        tr.remember("doc-1")
        tr.remember("doc-2")
        assert tr.pick() in ("doc-1", "doc-2")

    def test_pick_empty_returns_none(self):
        tr = DocIdTracker()
        assert tr.pick() is None

    def test_writes_allowed_respects_max(self):
        tr = DocIdTracker(max_docs=3)
        assert tr.writes_allowed
        tr.remember("a")
        tr.remember("b")
        tr.remember("c")
        assert not tr.writes_allowed

    def test_buffer_trims_at_threshold(self):
        tr = DocIdTracker(max_docs=100_000)
        for i in range(5001):
            tr.remember(f"doc-{i}")
        # After 5001 inserts, buffer should have trimmed to 2000
        with tr._lock:
            assert len(tr._ids) == 2000

    def test_trimmed_buffer_keeps_recent_ids(self):
        tr = DocIdTracker(max_docs=100_000)
        for i in range(5001):
            tr.remember(f"doc-{i}")
        with tr._lock:
            # Last ID should be the most recent
            assert tr._ids[-1] == "doc-5000"


# ---------------------------------------------------------------------------
# HealthMonitor — multi-node max logic
# ---------------------------------------------------------------------------

class TestHealthMonitor:
    def _make_monitor(self) -> HealthMonitor:
        return HealthMonitor("http://localhost:9200")

    def test_heap_pct_empty_nodes(self):
        m = self._make_monitor()
        assert m.heap_pct == 0
        assert m.cpu_pct == 0

    def test_heap_pct_takes_max_across_nodes(self):
        m = self._make_monitor()
        nodes_response = {
            "nodes": {
                "node1": {
                    "name": "data-0",
                    "jvm": {"mem": {"heap_used_percent": 45}},
                    "os": {"cpu": {"percent": 20}},
                },
                "node2": {
                    "name": "data-1",
                    "jvm": {"mem": {"heap_used_percent": 82}},
                    "os": {"cpu": {"percent": 67}},
                },
                "node3": {
                    "name": "data-2",
                    "jvm": {"mem": {"heap_used_percent": 31}},
                    "os": {"cpu": {"percent": 12}},
                },
            }
        }
        with patch("_challenge_infra.http_request") as mock_req:
            mock_req.return_value = (200, json.dumps(nodes_response).encode())
            m._check()

        assert m.heap_pct == 82
        assert m.cpu_pct == 67
        assert len(m._nodes) == 3

    def test_throttle_set_when_heap_exceeds_threshold(self):
        m = self._make_monitor()
        nodes_response = {
            "nodes": {
                "node1": {
                    "name": "hot-node",
                    "jvm": {"mem": {"heap_used_percent": 85}},
                    "os": {"cpu": {"percent": 50}},
                },
            }
        }
        with patch("_challenge_infra.http_request") as mock_req:
            mock_req.return_value = (200, json.dumps(nodes_response).encode())
            m._check()

        assert m.throttle.is_set()

    def test_throttle_cleared_when_heap_drops(self):
        m = self._make_monitor()
        m.throttle.set()  # simulate already throttled

        nodes_response = {
            "nodes": {
                "node1": {
                    "name": "recovered",
                    "jvm": {"mem": {"heap_used_percent": 50}},
                    "os": {"cpu": {"percent": 10}},
                },
            }
        }
        with patch("_challenge_infra.http_request") as mock_req:
            mock_req.return_value = (200, json.dumps(nodes_response).encode())
            m._check()

        assert not m.throttle.is_set()

    def test_consecutive_failures_increment_on_error(self):
        m = self._make_monitor()
        with patch("_challenge_infra.http_request") as mock_req:
            mock_req.return_value = (0, b"")
            m._check()
            m._check()

        assert m._consecutive_failures == 2

    def test_consecutive_failures_reset_on_success(self):
        m = self._make_monitor()
        m._consecutive_failures = 5
        nodes_response = {"nodes": {}}
        with patch("_challenge_infra.http_request") as mock_req:
            mock_req.return_value = (200, json.dumps(nodes_response).encode())
            m._check()

        assert m._consecutive_failures == 0

    def test_format_status_no_nodes(self):
        m = self._make_monitor()
        assert "No node data yet" in m.format_status()


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------

class TestProgressBar:
    @pytest.mark.parametrize("pct, expected_filled", [
        (0, 0),
        (50, 5),
        (100, 10),
    ])
    def test_bar_fill_levels(self, pct, expected_filled):
        bar = _progress_bar(pct, width=10)
        assert len(bar) == 10
        assert bar.count("\u2588") == expected_filled
