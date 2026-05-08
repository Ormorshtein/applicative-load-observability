"""Stress formulas — one function per operation class."""

import math
import os
from collections.abc import Callable
from dataclasses import dataclass

from .._baselines import get_baselines
from ._cost_indicators import _bool_total


@dataclass
class StressContext:
    es_took_ms:       float
    gateway_took_ms:  float
    hits:             int
    shards_total:     int
    docs_affected:    int
    bulk_doc_count:   int = 0  # action-line count from request body (bulk-only)


def normalize(value: float, baseline: float) -> float:
    return value / baseline if baseline else 0.0


def _stress_query(ctx: StressContext, bl: dict[str, float]) -> dict[str, float]:
    return {
        "took":   0.50 * normalize(ctx.es_took_ms, bl["took_ms"]),
        "shards": 0.15 * normalize(ctx.shards_total, bl["shards_total"]),
        "hits":   0.35 * normalize(ctx.hits, bl["hits"]),
    }


def _stress_bulk(ctx: StressContext, bl: dict[str, float]) -> dict[str, float]:
    return {
        "took":           0.45 * normalize(ctx.es_took_ms, bl["took_ms"]),
        "bulk_doc_count": 0.55 * normalize(ctx.bulk_doc_count, bl["docs_affected"]),
    }


def _stress_by_query(ctx: StressContext, bl: dict[str, float]) -> dict[str, float]:
    return {
        "took":          0.40 * normalize(ctx.es_took_ms, bl["took_ms"]),
        "docs_affected": 0.35 * normalize(ctx.docs_affected, bl["docs_affected"]),
        "shards":        0.25 * normalize(ctx.shards_total, bl["shards_total"]),
    }


def _stress_update(ctx: StressContext, bl: dict[str, float]) -> dict[str, float]:
    return {
        "took":   0.60 * normalize(ctx.es_took_ms, bl["took_ms"]),
        "shards": 0.40 * normalize(ctx.shards_total, bl["shards_total"]),
    }


def _stress_doc_write(ctx: StressContext, bl: dict[str, float]) -> dict[str, float]:
    return {
        "took":   0.70 * normalize(ctx.es_took_ms, bl["took_ms"]),
        "shards": 0.30 * normalize(ctx.shards_total, bl["shards_total"]),
    }


_STRESS_DISPATCH: dict[str, Callable[[StressContext, dict[str, float]], dict[str, float]]] = {
    "_search":          _stress_query,
    "_msearch":         _stress_query,
    "_count":           _stress_query,
    "_scroll":          _stress_query,
    "_explain":         _stress_query,
    "_validate":        _stress_query,
    "_bulk":            _stress_bulk,
    "_update_by_query": _stress_by_query,
    "_delete_by_query": _stress_by_query,
    "_update":          _stress_update,
    "_create":          _stress_doc_write,
    "index":            _stress_doc_write,
    "delete":           _stress_doc_write,
    "get":              _stress_doc_write,
}

_NO_MULTIPLIER_OPS = {"_bulk", "_create", "index", "delete"}

_CLAUSE_THRESHOLD    = int(os.environ.get("STRESS_CLAUSE_THRESHOLD", 4))
_CLAUSE_WEIGHT       = float(os.environ.get("STRESS_CLAUSE_WEIGHT", 0.10))
_CLAUSE_CAP          = float(os.environ.get("STRESS_CLAUSE_CAP", 0.50))

_AGG_THRESHOLD = int(os.environ.get("STRESS_AGG_THRESHOLD", 3))
_AGG_WEIGHT    = float(os.environ.get("STRESS_AGG_WEIGHT", 0.10))
_AGG_CAP       = float(os.environ.get("STRESS_AGG_CAP", 0.50))

_GEO_VERTEX_THRESHOLD = int(os.environ.get("STRESS_GEO_VERTEX_THRESHOLD", 10))

# (count_key, threshold, weight, cap) — applied additively to base before multiplier
_CONTINUOUS_BONUSES: list[tuple[str, int, float, float]] = [
    ("bool_total",            _CLAUSE_THRESHOLD, _CLAUSE_WEIGHT, _CLAUSE_CAP),
    ("agg_clause_count",      _AGG_THRESHOLD,    _AGG_WEIGHT,    _AGG_CAP),
    ("wildcard_clause_count", 1, 0.10, 0.50),
    ("nested_clause_count",   1, 0.10, 0.50),
    ("fuzzy_clause_count",    1, 0.10, 0.50),
    ("geo_vertex_count",      _GEO_VERTEX_THRESHOLD, 0.12, 0.60),
    ("knn_clause_count",      1, 0.10, 0.50),
    ("script_clause_count",   1, 0.10, 0.50),
    ("terms_values_count",    50, 0.10, 0.50),
]


def calc_stress(
    operation: str,
    ctx: StressContext,
    stress_multiplier: float = 1.0,
    clause_counts: dict[str, int] | None = None,
) -> tuple[float, dict[str, float], dict[str, float]]:
    """Return (score, bonuses, components).

    ``components`` maps each formula input (took, shards, hits, etc.)
    plus ``bonus`` (sum of continuous bonuses) to its contribution to
    the base score *before* the multiplier is applied.
    """
    bl = get_baselines()
    formula = _STRESS_DISPATCH.get(operation, _stress_doc_write)
    components = formula(ctx, bl)
    base = sum(components.values())
    if operation in _NO_MULTIPLIER_OPS:
        return base, {}, components
    bonuses: dict[str, float] = {}
    if clause_counts:
        counts = {
            **clause_counts,
            "bool_total": _bool_total(clause_counts),
        }
        bonus_total = 0.0
        for key, threshold, weight, cap in _CONTINUOUS_BONUSES:
            count = counts.get(key, 0)
            if count > threshold:
                bonus = min(weight * math.log(1 + count - threshold), cap)
                bonuses[key] = bonus
                bonus_total += bonus
        if bonus_total > 0:
            components["bonus"] = bonus_total
            base += bonus_total
    return base * stress_multiplier, bonuses, components
