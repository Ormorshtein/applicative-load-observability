"""Culprit + task configs for the over-fetching challenge.

The culprit requests size 2000-5000 per query — no pagination.
Zero cost indicators trigger; stress comes purely from the size component.
"""

import random

from helpers import rand_category, rand_str
from _trivial_noise import make_noise

INDEX = "challenge-overfetch"
APP_NAME = "ecommerce-api"
CULPRIT = "product-catalog"
DESCRIPTION = "Challenge: Over-Fetching — find the service skipping pagination"
HINT = "One service never implemented pagination."
CULPRIT_EXPLANATION = (
    "The culprit requested size 2000-5000 per query.\n"
    "  The size term alone contributes 0.10 × (size/100) to stress,\n"
    "  plus high took_ms from fetching/serializing thousands of documents.")
MISS_EXPLANATION = (
    "Look for services with abnormally high request.size and "
    "response.size_bytes.")
SCRIPT_BUILDERS = ()

_n = make_noise(INDEX, APP_NAME)


def _overfetch_search(gw, tr):
    """match_all + sort by _doc with size 2000-5000 — the anti-pattern."""
    size = random.randint(2000, 5000)
    return _n.search(gw, {
        "query": {"match_all": {}},
        "sort": [{"_doc": "asc"}],
        "size": size,
    })


TASK_CONFIGS = [
    ("user-auth", 4, 50, [
        (_n.simple_search, 50), (_n.match_all, 30), (_n.light_bool, 20),
    ]),
    ("order-service", 4, 40, [
        (_n.light_bool, 40), (_n.simple_search, 40), (_n.single_index, 20),
    ]),
    ("cart-manager", 4, 50, [
        (_n.simple_search, 40), (_n.single_index, 30), (_n.match_all, 30),
    ]),
    ("inventory-sync", 4, 40, [
        (lambda gw, tr: _n.bulk_index(gw, tr, 5, 15), 60),
        (_n.match_all, 40),
    ]),
    ("product-catalog", 3, 80, [
        (_overfetch_search, 80), (_n.simple_search, 20),
    ]),
    ("search-suggest", 4, 50, [
        (_n.simple_search, 50), (_n.light_bool, 30), (_n.light_agg, 20),
    ]),
    ("price-updater", 3, 60, [
        (_n.single_index, 50), (_n.simple_search, 50),
    ]),
]
