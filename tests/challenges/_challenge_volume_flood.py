"""Culprit + task configs for the volume flood challenge.

The culprit polls for recent items by date range at extreme rate (12
workers, 0ms delay).  Each query is cheap (size 20, narrow range) but
the culprit's unique template appears at 10x the rate of any other.
Per-request stress is LOW — the signal is the template's request count.
"""

import random

from _trivial_noise import make_noise

INDEX = "challenge-volume-flood"
APP_NAME = "notification-service"
CULPRIT = "event-poller"
DESCRIPTION = "Challenge: Volume Flood — find the service drowning the cluster"
HINT = (
    "Per-request stress is low everywhere.  Think about volume.\n"
    "  Hint: 'Stress by Application' won't help — it's all one app.")
CULPRIT_EXPLANATION = (
    "The culprit polled for recent items by date range at extreme rate\n"
    "  (12 workers, no delay).  Each query was cheap — size 20, narrow\n"
    "  range — but 100+ req/s from one service dwarfed all others.\n"
    "  Diagnosis requires looking at request count per template.")
MISS_EXPLANATION = (
    "Look for a template with disproportionately high request count\n"
    "  but low per-request stress.  Volume is the problem, not cost.")
SCRIPT_BUILDERS = ()

_n = make_noise(INDEX, APP_NAME)


def _poll_recent(gw, tr):
    """Poll for recent items by date range — cheap but at extreme rate."""
    month = random.randint(1, 12)
    return _n.search(gw, {
        "query": {"range": {"created_at": {
            "gte": f"2025-{month:02d}-01",
            "lte": f"2025-{month:02d}-28",
        }}},
        "sort": [{"created_at": "desc"}],
        "size": 20,
    })


TASK_CONFIGS = [
    ("digest-builder", 3, 80, [
        (_n.simple_search, 30), (_n.light_agg, 40), (_n.light_bool, 30),
    ]),
    ("user-prefs", 3, 100, [
        (_n.simple_search, 50), (_n.match_all, 30), (_n.single_index, 20),
    ]),
    ("event-poller", 12, 0, [
        (_poll_recent, 80), (_n.simple_search, 20),
    ]),
    ("alert-engine", 3, 80, [
        (_n.light_bool, 40), (_n.simple_search, 40), (_n.match_all, 20),
    ]),
    ("delivery-tracker", 3, 80, [
        (_n.simple_search, 40), (_n.single_index, 30), (_n.match_all, 30),
    ]),
    ("subscription-mgr", 3, 100, [
        (lambda gw, tr: _n.bulk_index(gw, tr, 5, 10), 40),
        (_n.simple_search, 40), (_n.match_all, 20),
    ]),
    ("template-loader", 2, 100, [
        (_n.simple_search, 50), (_n.match_all, 50),
    ]),
]
