"""Culprit + task configs for the unfiltered aggregations challenge.

The culprit runs match_all with 6-8 aggregations (below the deep_aggs
threshold of 10) and size 100-500.  Every document is evaluated for
every aggregation.  No cost indicators trigger.

NOTE: On a single-node cluster with only 10k documents, keyword-field
aggregations are inherently fast — ES processes them in milliseconds.
CPU may plateau around 50% regardless of worker count.  The challenge
is still valid because the culprit's templates (6-8 aggs + match_all +
large size) are clearly distinguishable from noise, and stopping the
culprit produces a visible CPU drop.  On a multi-node cluster or with
a larger dataset (100k+ docs), CPU impact would be more dramatic.
"""

import random

from helpers import rand_str
from _trivial_noise import make_noise

INDEX = "challenge-unfiltered-aggs"
APP_NAME = "analytics-platform"
CULPRIT = "dashboard-builder"
DESCRIPTION = "Challenge: Unfiltered Aggregations — find the analytics hog"
HINT = "One service runs heavy aggregations without filter context."
CULPRIT_EXPLANATION = (
    "The culprit ran match_all with 6-8 aggregations (below deep_aggs\n"
    "  threshold of 10) and size 100-500.  Full-index scans on every query\n"
    "  caused high es_took_ms with zero cost indicators.")
MISS_EXPLANATION = (
    "Look for elevated clause_counts.agg (below 10) combined with\n"
    "  high response.es_took_ms on _search operations.")
SCRIPT_BUILDERS = ()

_n = make_noise(INDEX, APP_NAME)

_EXTRA_AGGS = {
    "max_rating": {"max": {"field": "rating"}},
    "min_price": {"min": {"field": "price"}},
}


def _unfiltered_agg_search(gw, tr):
    """match_all + 6-8 aggregations (below deep_aggs threshold of 10)."""
    size = random.randint(100, 500)
    aggs = {
        "by_category": {"terms": {"field": "category", "size": 50}},
        "by_color": {"terms": {"field": "color", "size": 20}},
        "avg_price": {"avg": {"field": "price"}},
        "price_stats": {"stats": {"field": "price"}},
        "qty_histogram": {"histogram": {"field": "quantity",
                                         "interval": 50}},
        "rating_pct": {"percentiles": {"field": "rating"}},
    }
    for key, val in random.sample(list(_EXTRA_AGGS.items()),
                                   k=random.randint(0, 2)):
        aggs[key] = val
    return _n.search(gw, {
        "query": {"match_all": {}}, "aggs": aggs, "size": size})


TASK_CONFIGS = [
    ("report-api", 4, 40, [
        (_n.simple_search, 40), (_n.light_agg, 40), (_n.light_bool, 20),
    ]),
    ("user-tracker", 4, 50, [
        (_n.simple_search, 50), (_n.single_index, 30), (_n.match_all, 20),
    ]),
    ("data-export", 4, 50, [
        (_n.light_bool, 40), (_n.simple_search, 40), (_n.match_all, 20),
    ]),
    ("dashboard-builder", 3, 80, [
        (_unfiltered_agg_search, 80), (_n.simple_search, 20),
    ]),
    ("cache-warmer", 4, 40, [
        (_n.simple_search, 50), (_n.match_all, 30), (_n.light_bool, 20),
    ]),
    ("metrics-writer", 4, 40, [
        (lambda gw, tr: _n.bulk_index(gw, tr, 5, 15), 50),
        (_n.single_index, 30), (_n.match_all, 20),
    ]),
    ("event-logger", 3, 60, [
        (_n.single_index, 50), (_n.simple_search, 50),
    ]),
]
