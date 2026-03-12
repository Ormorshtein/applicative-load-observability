"""Culprit + task configs for the low stress / high CPU challenge.

The culprit runs high-cardinality terms aggregations with size:0 (no
documents returned) at extreme rate.  took_ms is low (no fetch phase),
response payloads are small, so stress scores are low — but actual CPU
is pinned because ES must rank 50k+ unique tokens to find top buckets.

This challenge uses a custom mapping that enables fielddata on the
description field so terms aggregations can run on analyzed text.
"""

from helpers import LOADTEST_MAPPING
from _trivial_noise import make_noise

INDEX = "challenge-hidden-cpu"
APP_NAME = "reporting-api"
CULPRIT = "cardinality-scanner"
DESCRIPTION = "Challenge: Low Stress, High CPU — find the blind-spot exploit"
HINT = (
    "Stress scores are low everywhere.  But CPU is pinned.\n"
    "  The dashboard stress formula has a blind spot — correlate\n"
    "  the CPU timeline with your actions.")
CULPRIT_EXPLANATION = (
    "The culprit ran high-cardinality terms aggs with size:0.\n"
    "  took_ms was low (no fetch phase), so stress was low.\n"
    "  But ES spent massive CPU ranking 50k+ unique tokens per query.\n"
    "  The stress formula weighs took_ms at 55% — if took is low,\n"
    "  stress is low, even when actual CPU is high.\n"
    "  Diagnosis requires correlating CPU timeline with service stops.")
MISS_EXPLANATION = (
    "The stress formula has a blind spot: low took_ms = low stress,\n"
    "  even when CPU is high.  Correlate cluster CPU with service stops.")
SCRIPT_BUILDERS = ()

# Enable fielddata on description for high-cardinality terms aggs
MAPPING = {
    "mappings": {
        "properties": {
            **LOADTEST_MAPPING["mappings"]["properties"],
            "description": {"type": "text", "fielddata": True},
        }
    }
}

_n = make_noise(INDEX, APP_NAME)


def _high_cardinality_agg(gw, tr):
    """size:0 + high-cardinality terms agg (top 1000 from 50k+ tokens)."""
    return _n.search(gw, {"size": 0, "aggs": {
        "top_words": {"terms": {"field": "description", "size": 1000}},
    }})


TASK_CONFIGS = [
    ("summary-builder", 3, 80, [
        (_n.simple_search, 40), (_n.light_agg, 40), (_n.light_bool, 20),
    ]),
    ("drill-down", 3, 80, [
        (_n.light_bool, 40), (_n.simple_search, 40), (_n.match_all, 20),
    ]),
    ("export-csv", 3, 80, [
        (_n.simple_search, 50), (_n.match_all, 30), (_n.light_agg, 20),
    ]),
    ("scheduled-report", 3, 100, [
        (_n.light_agg, 40), (_n.simple_search, 40), (_n.match_all, 20),
    ]),
    ("filter-service", 3, 80, [
        (_n.light_bool, 40), (_n.simple_search, 40), (_n.single_index, 20),
    ]),
    ("cache-loader", 2, 100, [
        (_n.simple_search, 50), (_n.match_all, 50),
    ]),
    ("cardinality-scanner", 10, 0, [
        (_high_cardinality_agg, 55), (_n.simple_search, 45),
    ]),
]
