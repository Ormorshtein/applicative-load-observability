"""Unit tests for stress score formulas in analyzer/stress.py."""

import math

import pytest

from stress import normalize, calc_stress, StressContext, _ALL_COUNT_FIELDS


def _counts(**overrides) -> dict:
    counts = {k: 0 for k in _ALL_COUNT_FIELDS}
    counts["geo_area_km2"] = 0.0
    counts.update(overrides)
    return counts


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
        defaults = dict(es_took_ms=100, gateway_took_ms=100, hits=500, shards_total=5, docs_affected=500)
        defaults.update(kw)
        return StressContext(**defaults)

    def test_search_at_baseline(self):
        """All values at baseline -> base = 0.50+0.15+0.35 = 1.0"""
        score, _, _ = calc_stress("_search", self._ctx())
        assert score == pytest.approx(1.0)

    def test_search_with_multiplier(self):
        score, _, _ = calc_stress("_search", self._ctx(), stress_multiplier=1.5)
        assert score == pytest.approx(1.5)

    def test_search_double_took(self):
        score, _, _ = calc_stress("_search", self._ctx(es_took_ms=200))
        expected = 0.50 * 2.0 + 0.15 * 1.0 + 0.35 * 1.0
        assert score == pytest.approx(expected)

    def test_search_zero_values(self):
        score, _, _ = calc_stress("_search", self._ctx(es_took_ms=0, hits=0, shards_total=0))
        assert score == pytest.approx(0.0)

    def test_bulk_at_baseline(self):
        score, _, _ = calc_stress("_bulk", self._ctx())
        expected = 0.45 * 1.0 + 0.55 * 1.0
        assert score == pytest.approx(expected)

    def test_bulk_ignores_multiplier(self):
        score_no, _, _ = calc_stress("_bulk", self._ctx())
        score_with, _, _ = calc_stress("_bulk", self._ctx(), stress_multiplier=2.0)
        assert score_no == score_with

    def test_update_by_query_at_baseline(self):
        score, _, _ = calc_stress("_update_by_query", self._ctx())
        expected = 0.40 * 1.0 + 0.35 * 1.0 + 0.25 * 1.0
        assert score == pytest.approx(expected)

    def test_delete_by_query_same_formula(self):
        ctx = self._ctx()
        score_del, _, _ = calc_stress("_delete_by_query", ctx)
        score_upd, _, _ = calc_stress("_update_by_query", ctx)
        assert score_del == score_upd

    def test_update_at_baseline(self):
        score, _, _ = calc_stress("_update", self._ctx())
        expected = 0.60 * 1.0 + 0.40 * 1.0
        assert score == pytest.approx(expected)

    def test_update_applies_multiplier(self):
        score, _, _ = calc_stress("_update", self._ctx(), stress_multiplier=1.5)
        expected = (0.60 * 1.0 + 0.40 * 1.0) * 1.5
        assert score == pytest.approx(expected)

    def test_create_at_baseline(self):
        score, _, _ = calc_stress("_create", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_create_ignores_multiplier(self):
        score_no, _, _ = calc_stress("_create", self._ctx())
        score_with, _, _ = calc_stress("_create", self._ctx(), stress_multiplier=2.0)
        assert score_no == score_with

    def test_index_at_baseline(self):
        score, _, _ = calc_stress("index", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_index_ignores_multiplier(self):
        score_no, _, _ = calc_stress("index", self._ctx())
        score_with, _, _ = calc_stress("index", self._ctx(), stress_multiplier=2.0)
        assert score_no == score_with

    def test_delete_at_baseline(self):
        score, _, _ = calc_stress("delete", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_delete_ignores_multiplier(self):
        score_no, _, _ = calc_stress("delete", self._ctx())
        score_with, _, _ = calc_stress("delete", self._ctx(), stress_multiplier=2.0)
        assert score_no == score_with

    def test_get_uses_doc_write(self):
        score, _, _ = calc_stress("get", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_get_applies_multiplier(self):
        score, _, _ = calc_stress("get", self._ctx(), stress_multiplier=1.5)
        expected = (0.70 * 1.0 + 0.30 * 1.0) * 1.5
        assert score == pytest.approx(expected)

    def test_unknown_operation_uses_doc_write(self):
        score, _, _ = calc_stress("_unknown", self._ctx())
        expected = 0.70 * 1.0 + 0.30 * 1.0
        assert score == pytest.approx(expected)

    def test_stress_unbounded(self):
        """Score should exceed 1.0 for extreme values."""
        ctx = self._ctx(es_took_ms=10000, hits=1000000, shards_total=100)
        score, _, _ = calc_stress("_search", ctx)
        assert score > 10.0

    def test_search_high_multiplier(self):
        """Extreme multiplier compounds stress."""
        ctx = self._ctx(es_took_ms=500)
        score, _, _ = calc_stress("_search", ctx, stress_multiplier=3.0)
        base = 0.50 * 5.0 + 0.15 * 1.0 + 0.35 * 1.0
        assert score == pytest.approx(base * 3.0)

    # -- bool clause bonus ------------------------------------------------

    def test_search_with_clause_bonus(self):
        """10 bool clauses (threshold=4) adds logarithmic bonus."""
        ctx = self._ctx()
        score_no, _, _ = calc_stress("_search", ctx)
        score_with, bonuses, _ = calc_stress("_search", ctx, clause_counts=_counts(bool_must_count=10))
        expected_bonus = min(0.10 * math.log(1 + 6), 0.50)
        assert score_with == pytest.approx(score_no + expected_bonus)
        assert "bool_total" in bonuses

    def test_clause_bonus_below_threshold(self):
        """3 clauses (below threshold=4) produces no bonus."""
        ctx = self._ctx()
        score_base, _, _ = calc_stress("_search", ctx)
        score_with, bonuses, _ = calc_stress("_search", ctx, clause_counts=_counts(bool_must_count=3))
        assert score_with == pytest.approx(score_base)
        assert "bool_total" not in bonuses

    def test_clause_bonus_capped(self):
        """Extreme clause count — bonus must not exceed CAP (0.50)."""
        ctx = self._ctx()
        score_base, _, _ = calc_stress("_search", ctx)
        score_with, _, _ = calc_stress("_search", ctx, clause_counts=_counts(bool_must_count=1000))
        assert score_with == pytest.approx(score_base + 0.50)

    def test_clause_bonus_ignored_for_bulk(self):
        """Bulk operations get no clause bonus."""
        ctx = self._ctx()
        score_no, _, _ = calc_stress("_bulk", ctx)
        score_with, bonuses, _ = calc_stress("_bulk", ctx, clause_counts=_counts(bool_must_count=20))
        assert score_no == score_with
        assert bonuses == {}

    def test_clause_bonus_multiplied_by_indicator(self):
        """Clause bonus is included in base before multiplier is applied."""
        ctx = self._ctx()
        base = 0.50 * 1.0 + 0.15 * 1.0 + 0.35 * 1.0
        bonus = min(0.10 * math.log(1 + 6), 0.50)
        expected = (base + bonus) * 1.5
        score, _, _ = calc_stress("_search", ctx, stress_multiplier=1.5, clause_counts=_counts(bool_must_count=10))
        assert score == pytest.approx(expected)

    # -- continuous bonuses per clause type --------------------------------

    @pytest.mark.parametrize("key,count,threshold", [
        ("agg_clause_count",      7, 3),
        ("wildcard_clause_count", 4, 1),
        ("nested_clause_count",   3, 1),
        ("fuzzy_clause_count",    3, 1),
        ("knn_clause_count",      3, 1),
        ("script_clause_count",   3, 1),
    ])
    def test_continuous_bonus(self, key, count, threshold):
        """Each clause type above its threshold adds a logarithmic bonus."""
        ctx = self._ctx()
        score_base, _, _ = calc_stress("_search", ctx)
        score_with, bonuses, _ = calc_stress("_search", ctx, clause_counts=_counts(**{key: count}))
        expected_bonus = min(0.10 * math.log(1 + count - threshold), 0.50)
        assert score_with == pytest.approx(score_base + expected_bonus)
        assert key in bonuses

    def test_geo_area_bonus(self):
        """Geo area bonus scales with search area in km²."""
        ctx = self._ctx()
        score_base, _, _ = calc_stress("_search", ctx)
        # 500 km² geo area (above 1 km² threshold)
        score_with, bonuses, _ = calc_stress("_search", ctx,
            clause_counts=_counts(geo_area_km2=500.0))
        expected_bonus = min(0.12 * math.log(1 + 500.0 - 1), 0.60)
        assert score_with == pytest.approx(score_base + expected_bonus)
        assert "geo_area_km2" in bonuses

    def test_geo_area_below_threshold_no_bonus(self):
        """Geo area below threshold adds no bonus."""
        ctx = self._ctx()
        score_base, _, _ = calc_stress("_search", ctx)
        score_with, _, _ = calc_stress("_search", ctx,
            clause_counts=_counts(geo_area_km2=0.5))
        assert score_with == pytest.approx(score_base)

    def test_terms_values_bonus(self):
        """Terms values above threshold 50 adds bonus."""
        ctx = self._ctx()
        score_base, _, _ = calc_stress("_search", ctx)
        score_with, bonuses, _ = calc_stress("_search", ctx, clause_counts=_counts(terms_values_count=150))
        expected_bonus = min(0.10 * math.log(1 + 100), 0.50)  # threshold 50, excess 100
        assert score_with == pytest.approx(score_base + expected_bonus)
        assert "terms_values_count" in bonuses

    @pytest.mark.parametrize("key,at_threshold", [
        ("agg_clause_count",      3),
        ("wildcard_clause_count", 1),
        ("nested_clause_count",   1),
        ("fuzzy_clause_count",    1),
        ("knn_clause_count",      1),
        ("script_clause_count",   1),
        ("terms_values_count",    50),
    ])
    def test_at_threshold_no_bonus(self, key, at_threshold):
        """Count exactly at the threshold produces no bonus."""
        ctx = self._ctx()
        score_base, _, _ = calc_stress("_search", ctx)
        score_with, _, _ = calc_stress("_search", ctx, clause_counts=_counts(**{key: at_threshold}))
        assert score_with == pytest.approx(score_base)

    def test_continuous_bonus_capped(self):
        """Extreme count on any clause type caps at 0.50."""
        ctx = self._ctx()
        score_base, _, _ = calc_stress("_search", ctx)
        score_with, _, _ = calc_stress("_search", ctx, clause_counts=_counts(agg_clause_count=10000))
        assert score_with == pytest.approx(score_base + 0.50)

    def test_continuous_bonuses_ignored_for_bulk(self):
        """Bulk operations skip all continuous bonuses."""
        ctx = self._ctx()
        score_no, _, _ = calc_stress("_bulk", ctx)
        score_with, bonuses, _ = calc_stress("_bulk", ctx, clause_counts=_counts(
            agg_clause_count=20, wildcard_clause_count=10, nested_clause_count=5))
        assert score_no == score_with
        assert bonuses == {}

    def test_multiple_bonuses_additive(self):
        """Multiple clause types compound additively, then multiplier applies."""
        ctx = self._ctx()
        base = 0.50 * 1.0 + 0.15 * 1.0 + 0.35 * 1.0
        clause_bonus = min(0.10 * math.log(1 + 6), 0.50)   # bool 10, threshold 4
        agg_bonus = min(0.10 * math.log(1 + 4), 0.50)      # agg 7, threshold 3
        wildcard_bonus = min(0.10 * math.log(1 + 3), 0.50)  # wildcard 4, threshold 1
        expected = (base + clause_bonus + agg_bonus + wildcard_bonus) * 1.5
        score, bonuses, _ = calc_stress("_search", ctx, stress_multiplier=1.5, clause_counts=_counts(
            bool_must_count=10, agg_clause_count=7, wildcard_clause_count=4))
        assert score == pytest.approx(expected)
        assert len(bonuses) == 3

    def test_bonuses_dict_empty_when_no_counts(self):
        """No clause counts produces empty bonuses dict."""
        _, bonuses, _ = calc_stress("_search", self._ctx())
        assert bonuses == {}
