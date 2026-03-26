"""Unit tests for the shared LatencyTracker base class."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "integration"))

from helpers import LatencyTracker, _percentile


class TestPercentile:
    def test_empty_list(self):
        assert _percentile([], 50) == 0.0

    def test_single_element(self):
        assert _percentile([5.0], 50) == 5.0
        assert _percentile([5.0], 99) == 5.0

    def test_two_elements_interpolation(self):
        # p50 of [1, 3] = 1 + 0.5*(3-1) = 2.0
        assert _percentile([1.0, 3.0], 50) == pytest.approx(2.0)

    def test_p0_returns_first(self):
        assert _percentile([1.0, 2.0, 3.0], 0) == 1.0

    def test_p100_returns_last(self):
        assert _percentile([1.0, 2.0, 3.0], 100) == 3.0

    @pytest.mark.parametrize("pct, expected", [
        (0,   0.0),
        (50,  50.0),
        (95,  95.0),
        (100, 100.0),
    ])
    def test_linear_sequence(self, pct, expected):
        data = [float(i) for i in range(101)]  # 0..100
        assert _percentile(data, pct) == pytest.approx(expected)


class TestLatencyTracker:
    def test_record_and_count(self):
        lt = LatencyTracker()
        lt.record("_search", 5.0)
        lt.record("_search", 10.0)
        lt.record("_bulk", 3.0)
        assert lt.count("_search") == 2
        assert lt.count("_bulk") == 1
        assert lt.count("nonexistent") == 0

    def test_percentile(self):
        lt = LatencyTracker()
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            lt.record("op", v)
        assert lt.percentile("op", 50) == pytest.approx(3.0)

    def test_percentile_empty_operation(self):
        lt = LatencyTracker()
        assert lt.percentile("nonexistent", 50) == 0.0

    def test_sorted_samples(self):
        lt = LatencyTracker()
        lt.record("op", 5.0)
        lt.record("op", 1.0)
        lt.record("op", 3.0)
        assert lt.sorted_samples("op") == [1.0, 3.0, 5.0]

    def test_sorted_samples_empty(self):
        lt = LatencyTracker()
        assert lt.sorted_samples("nonexistent") == []
