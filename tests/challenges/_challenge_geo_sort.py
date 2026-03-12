"""Culprit + task configs for the geo sort + large fetch challenge.

The culprit combines geo_distance sort with size 1000-3000.  Sorting
thousands of documents by _geo_distance is computationally expensive.
has_geo fires for innocent noise tasks too, so the indicator is not
enough to pinpoint the culprit.
"""

import random

from _trivial_noise import make_noise

INDEX = "challenge-geo-sort"
APP_NAME = "location-service"
CULPRIT = "nearby-ranker"
DESCRIPTION = "Challenge: Geo Sort + Large Fetch — find the distance-sorting hog"
HINT = "Multiple services use geo queries.  Watch for expensive sorts."
CULPRIT_EXPLANATION = (
    "The culprit combined geo_distance sort with size 1000-3000.\n"
    "  Sorting thousands of documents by _geo_distance is expensive.\n"
    "  has_geo fired for innocent tasks too — the distinguishing signal\n"
    "  was high request.size combined with elevated es_took_ms.")
MISS_EXPLANATION = (
    "has_geo fires for many services.  The culprit stands out by its\n"
    "  combination of geo sort + large size producing high es_took_ms.")
SCRIPT_BUILDERS = ()

_n = make_noise(INDEX, APP_NAME)


def _geo_sort_search(gw, tr):
    """geo_distance sort with large fetch (size 1000-3000)."""
    lat = round(random.uniform(33.0, 42.0), 4)
    lon = round(random.uniform(-118.0, -74.0), 4)
    size = random.randint(1000, 3000)
    return _n.search(gw, {
        "query": {"geo_distance": {
            "distance": f"{random.randint(50, 150)}km",
            "location": {"lat": lat, "lon": lon},
        }},
        "sort": [{"_geo_distance": {
            "location": {"lat": lat, "lon": lon},
            "order": "asc",
            "unit": "km",
        }}],
        "size": size,
    })


TASK_CONFIGS = [
    ("place-search", 4, 40, [
        (_n.geo_bbox, 35), (_n.simple_search, 35), (_n.light_geo, 30),
    ]),
    ("check-in", 4, 50, [
        (_n.simple_search, 40), (_n.single_index, 30), (_n.geo_cat_filter, 30),
    ]),
    ("coverage-map", 4, 50, [
        (_n.light_bool, 40), (_n.simple_search, 40), (_n.light_agg, 20),
    ]),
    ("poi-indexer", 4, 40, [
        (lambda gw, tr: _n.bulk_index(gw, tr, 5, 15), 50),
        (_n.single_index, 30), (_n.match_all, 20),
    ]),
    ("geo-cache", 4, 50, [
        (_n.geo_sort_small, 30), (_n.light_geo, 30), (_n.simple_search, 40),
    ]),
    ("nearby-ranker", 3, 80, [
        (_geo_sort_search, 75), (_n.simple_search, 25),
    ]),
    ("boundary-check", 3, 60, [
        (_n.geo_bbox, 35), (_n.light_bool, 35), (_n.simple_search, 30),
    ]),
]
