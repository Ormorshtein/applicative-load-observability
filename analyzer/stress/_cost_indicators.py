"""Cost indicators — flag structurally expensive query patterns and compute multipliers."""

import os
from collections.abc import Callable
from typing import NamedTuple

_COST_INDICATOR_BOOL_THRESHOLD  = int(os.environ.get("COST_INDICATOR_BOOL_THRESHOLD",  50))
_COST_INDICATOR_TERMS_THRESHOLD = int(os.environ.get("COST_INDICATOR_TERMS_THRESHOLD", 500))
_COST_INDICATOR_AGGS_THRESHOLD  = int(os.environ.get("COST_INDICATOR_AGGS_THRESHOLD",  10))


class CostIndicator(NamedTuple):
    name: str
    condition: Callable[[dict[str, int]], bool]
    multiplier: float
    extractor: Callable[[dict[str, int]], int]


def _simple(
    name: str, field: str, threshold: int, multiplier: float,
) -> CostIndicator:
    """Build a cost indicator for a single-field >= threshold check."""

    def _condition(c: dict[str, int], f: str = field, t: int = threshold) -> bool:
        return c[f] >= t

    def _extract(c: dict[str, int], f: str = field) -> int:
        return c[f]

    return CostIndicator(name, _condition, multiplier, _extract)


def _bool_total(counts: dict[str, int]) -> int:
    return (counts["bool_must_count"] + counts["bool_should_count"]
            + counts["bool_filter_count"] + counts["bool_must_not_count"])


def _geo_total(counts: dict[str, int]) -> int:
    return counts["geo_distance_count"] + counts["geo_shape_count"]


_COST_INDICATORS: list[CostIndicator] = [
    _simple("has_script",          "script_clause_count",  1, 1.5),
    _simple("has_runtime_mapping", "runtime_mapping_count", 1, 1.5),
    _simple("has_wildcard",        "wildcard_clause_count", 1, 1.3),
    _simple("has_nested",          "nested_clause_count",  1, 1.3),
    _simple("has_fuzzy",           "fuzzy_clause_count",   1, 1.2),
    CostIndicator("has_geo",
                  lambda c: _geo_total(c) >= 1, 1.2, _geo_total),  # type: ignore[misc]
    _simple("has_knn",             "knn_clause_count",     1, 1.2),
    CostIndicator("excessive_bool",
                  lambda c: _bool_total(c) >= _COST_INDICATOR_BOOL_THRESHOLD,  # type: ignore[misc]
                  1.3, _bool_total),
    _simple("large_terms_list", "terms_values_count",
            _COST_INDICATOR_TERMS_THRESHOLD, 1.2),
    _simple("deep_aggs", "agg_clause_count",
            _COST_INDICATOR_AGGS_THRESHOLD, 1.3),
    CostIndicator("unbound_hits",
                  lambda c: c.get("hits_lower_bound", 0) >= 1, 1.3,  # type: ignore[misc]
                  lambda c: 1),
]


def evaluate_cost_indicators(
    counts: dict[str, int],
) -> tuple[dict[str, int], float, dict[str, float]]:
    indicators: dict[str, int] = {}
    indicator_multipliers: dict[str, float] = {}
    multiplier = 1.0
    for indicator in _COST_INDICATORS:
        if indicator.condition(counts):
            indicators[indicator.name] = indicator.extractor(counts)
            indicator_multipliers[indicator.name] = indicator.multiplier
            multiplier *= indicator.multiplier
    return indicators, multiplier, indicator_multipliers
