"""Culprit + task configs for the geo broad sweep challenge.

The culprit uses geo_distance with 200-500km radius returning huge
result sets (size 500-1000).  has_geo (1.2x) fires for the culprit AND
for noise tasks doing tight-radius geo, so the indicator alone is not
diagnostic.
"""

import random

from _trivial_noise import make_noise

INDEX = "challenge-geo-sweep"
APP_NAME = "delivery-app"
CULPRIT = "store-finder"
DESCRIPTION = "Challenge: Geo Broad Sweep — find the service with the giant radius"
HINT = "Multiple services use geo queries.  The radius matters."
CULPRIT_EXPLANATION = (
    "The culprit used geo_distance with 200-500km radius + size 500-1000.\n"
    "  has_geo (1.2x) fired for the culprit AND for noise tasks doing\n"
    "  tight-radius geo — the indicator alone was not diagnostic.\n"
    "  The real signal was massive response.hits and es_took_ms.")
MISS_EXPLANATION = (
    "has_geo fires for many services.  Distinguish by response.hits —\n"
    "  the culprit returns 10-100x more documents per geo query.")
SCRIPT_BUILDERS = ()

_n = make_noise(INDEX, APP_NAME)


def _geo_sweep_search(gw, tr):
    """geo_distance with 200-500km radius, size 500-1000."""
    lat = round(random.uniform(33.0, 42.0), 4)
    lon = round(random.uniform(-118.0, -74.0), 4)
    radius = random.randint(200, 500)
    size = random.randint(500, 1000)
    return _n.search(gw, {"query": {"geo_distance": {
        "distance": f"{radius}km",
        "location": {"lat": lat, "lon": lon},
    }}, "size": size})


TASK_CONFIGS = [
    ("address-lookup", 4, 40, [
        (_n.light_geo, 35), (_n.simple_search, 35), (_n.light_bool, 30),
    ]),
    ("route-planner", 4, 40, [
        (_n.light_geo, 30), (_n.geo_bbox, 30), (_n.simple_search, 40),
    ]),
    ("zone-checker", 4, 50, [
        (_n.light_geo, 30), (_n.geo_cat_filter, 30), (_n.simple_search, 40),
    ]),
    ("fleet-tracker", 4, 50, [
        (_n.geo_sort_small, 30), (_n.light_geo, 30), (_n.match_all, 40),
    ]),
    ("store-finder", 3, 80, [
        (_geo_sweep_search, 70), (_n.simple_search, 30),
    ]),
    ("order-dispatch", 4, 40, [
        (lambda gw, tr: _n.bulk_index(gw, tr, 5, 15), 40),
        (_n.light_geo, 30), (_n.simple_search, 30),
    ]),
    ("eta-service", 4, 50, [
        (_n.light_geo, 35), (_n.geo_bbox, 35), (_n.simple_search, 30),
    ]),
]
