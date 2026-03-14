"""Unit tests for stress score formulas in analyzer/stress.py."""

import math

import pytest

from stress import normalize, calc_stress, StressContext


class TestNormalize:
    def test_at_baseline(self):
        assert normalize(100, 100) == 1.0

    def test_below_baseline(self):
        assert normalize(50, 100) == 0.5

    def test_above_baseline(self):
        assert normalize(200, 100) == 2.0

    def test_zero_value(self):
        assert normalize(0, 100) == 0.0


class TestCalcStress:
    def _ctx(self, **kw) -> StressContext:
        defaults = dict(es_took_ms=100, hits=10000, size=100, shards_total=5, docs_affected=500)
        defaults.update(kw)
        return StressContext(**defaults)

    def test_search_at_baseline(self):
        """All values at baseline -> base = 0.55+0.20+0.15+0.10 = 1.0"""
        score = calc_stress("_search", self._ctx())
        assert score == pytest.approx(1.0)

    def test_search_with_multiplier(self):
        score = calc_stress("_search", self._ctx(), stress_multiplier=1.5)
        assert score == pytest.approx(1.5)

    def test_search_double_took(self):
        score = calc_stress("_search", self._ctx(es_took_ms=200))
        expected = 0.55 * 2.0 + 0.20 * 1.0 + 0.15 * 1.0 + 0.10 * 1.0
        assert score == pytest.approx(expected)

    def test_search_zero_values(self):
        score = calc_stress("_search", self._ctx(es_took_ms=0, hits=0, size=0, shards_total=0))
        assert score == pytest.approx(0.0)

    def test_bulk_at_baseline(self):
        score = calc_stress("_bulk", self._ctx())
        expected = 0.45 * 1.0 + 0.55 * 1.0
        assert score == pytest.approx(expected)

    def test_bulk_ignores_multiplier(self):
        score_no_mult = calc_stress("_bulk", self._ctx())
        score_with_mult = calc_stress("_bulk", self._ctx(), stress_multiplier=2.0)
        assert score_no_mult == score_with_mult

    def test_update_by_query_at_baseline(self):
        score = calc_stress("_update_by_query", self._ctx())
        expected = 0.40 * 1.0 + 0.35 * 1.0 + 0.25 * 1.0
        assert score == pytest.approx(expected)

    def test_delete_by_query_same_formula(self):
        ctx = self._ctx()
        assert calc_stress("_delete_by_query", ctx) == calc_stress("_update_by_query", ctx)

    def test_update_at_baseline(self):
        score = calc_stress("_update", self._ctx())
        expected = 0.60 * 1.0 + 0.40 * 1.0
        assert score == pytest.approx(expected)

    def test_update_applies_multiplier(self):
        score = calc_stress("_update", self._ctx(), stress_multiplier=1.5)
        expected = (0.60 * 1.0 + 0.40 * 1.0) * 1.5
        assert score == pytest.approx(expected)

    def test_create_at_baseline(self):
        score = calc_stress("_create", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_create_ignores_multiplier(self):
        score_no = calc_stress("_create", self._ctx())
        score_with = calc_stress("_create", self._ctx(), stress_multiplier=2.0)
        assert score_no == score_with

    def test_index_at_baseline(self):
        score = calc_stress("index", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_index_ignores_multiplier(self):
        score_no = calc_stress("index", self._ctx())
        score_with = calc_stress("index", self._ctx(), stress_multiplier=2.0)
        assert score_no == score_with

    def test_delete_at_baseline(self):
        score = calc_stress("delete", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_delete_ignores_multiplier(self):
        score_no = calc_stress("delete", self._ctx())
        score_with = calc_stress("delete", self._ctx(), stress_multiplier=2.0)
        assert score_no == score_with

    def test_get_uses_doc_write(self):
        score = calc_stress("get", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_get_applies_multiplier(self):
        score = calc_stress("get", self._ctx(), stress_multiplier=1.5)
        expected = (0.70 * 1.0 + 0.30 * 1.0) * 1.5
        assert score == pytest.approx(expected)

    def test_unknown_operation_uses_doc_write(self):
        score = calc_stress("_unknown", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_stress_unbounded(self):
        """Score should exceed 1.0 for extreme values."""
        ctx = self._ctx(es_took_ms=10000, hits=1000000, shards_total=100, size=10000)
        score = calc_stress("_search", ctx)
        assert score > 10.0

    def test_search_high_multiplier(self):
        """Extreme multiplier compounds stress."""
        ctx = self._ctx(es_took_ms=500)
        score = calc_stress("_search", ctx, stress_multiplier=3.0)
        base = 0.55 * 5.0 + 0.20 * 1.0 + 0.15 * 1.0 + 0.10 * 1.0
        assert score == pytest.approx(base * 3.0)

    def test_search_with_clause_bonus(self):
        """10 bool clauses (threshold=4) adds logarithmic bonus."""
        ctx = self._ctx()
        score_no_clauses = calc_stress("_search", ctx)
        score_with = calc_stress("_search", ctx, bool_clause_total=10)
        expected_bonus = min(0.10 * math.log(1 + 6), 0.50)
        assert score_with == pytest.approx(score_no_clauses + expected_bonus)

    def test_clause_bonus_below_threshold(self):
        """3 clauses (below threshold=4) produces no bonus."""
        ctx = self._ctx()
        score_base = calc_stress("_search", ctx)
        score_with = calc_stress("_search", ctx, bool_clause_total=3)
        assert score_with == pytest.approx(score_base)

    def test_clause_bonus_capped(self):
        """Extreme clause count — bonus must not exceed CAP (0.50)."""
        ctx = self._ctx()
        score_base = calc_stress("_search", ctx)
        score_with = calc_stress("_search", ctx, bool_clause_total=1000)
        assert score_with == pytest.approx(score_base + 0.50)

    def test_clause_bonus_ignored_for_bulk(self):
        """Bulk operations get no clause bonus."""
        ctx = self._ctx()
        score_no = calc_stress("_bulk", ctx)
        score_with = calc_stress("_bulk", ctx, bool_clause_total=20)
        assert score_no == score_with

    def test_clause_bonus_multiplied_by_indicator(self):
        """Clause bonus is included in base before multiplier is applied."""
        ctx = self._ctx()
        base = 0.55 * 1.0 + 0.20 * 1.0 + 0.15 * 1.0 + 0.10 * 1.0
        bonus = min(0.10 * math.log(1 + 6), 0.50)
        expected = (base + bonus) * 1.5
        score = calc_stress("_search", ctx, stress_multiplier=1.5, bool_clause_total=10)
        assert score == pytest.approx(expected)
