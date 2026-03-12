"""Culprit + task configs for the micro-bulk flood challenge.

The culprit wraps every individual write in a _bulk call with 1-3
documents and fires at extreme rate (10 workers, 0ms delay).  The HTTP
and coordination overhead per request dominates actual indexing work.
"""

from _trivial_noise import make_noise

INDEX = "challenge-micro-bulk"
APP_NAME = "event-collector"
CULPRIT = "log-shipper"
DESCRIPTION = "Challenge: Micro-Bulk Flood — find the service wasting bulk overhead"
HINT = "One service wraps every write in its own bulk call."
CULPRIT_EXPLANATION = (
    "The culprit sent _bulk requests with only 1-3 documents each,\n"
    "  at extreme rate (10 workers, no delay).  Each bulk is cheap,\n"
    "  but the sheer request rate overwhelms the cluster with\n"
    "  coordination overhead.  Low docs_affected per request, high count.")
MISS_EXPLANATION = (
    "Look at _bulk request count vs response.docs_affected per request.\n"
    "  The culprit has extremely high count with tiny batch sizes.")
SCRIPT_BUILDERS = ()
MAX_DOCS = 200000

_n = make_noise(INDEX, APP_NAME)


def _micro_bulk(gw, tr):
    """Tiny bulk request (1-3 docs) — maximum overhead per doc."""
    return _n.bulk_index(gw, tr, 1, 3)


TASK_CONFIGS = [
    ("metrics-ingest", 3, 60, [
        (lambda gw, tr: _n.bulk_index(gw, tr, 10, 25), 50),
        (_n.simple_search, 30), (_n.match_all, 20),
    ]),
    ("trace-writer", 3, 80, [
        (lambda gw, tr: _n.bulk_index(gw, tr, 5, 15), 40),
        (_n.single_index, 30), (_n.simple_search, 30),
    ]),
    ("audit-log", 3, 80, [
        (_n.single_index, 40), (_n.simple_search, 40), (_n.match_all, 20),
    ]),
    ("log-shipper", 10, 0, [
        (_micro_bulk, 85), (_n.simple_search, 15),
    ]),
    ("session-store", 3, 80, [
        (_n.simple_search, 40), (_n.single_index, 30), (_n.light_bool, 30),
    ]),
    ("click-tracker", 3, 60, [
        (lambda gw, tr: _n.bulk_index(gw, tr, 8, 20), 50),
        (_n.match_all, 30), (_n.simple_search, 20),
    ]),
    ("error-reporter", 2, 100, [
        (_n.single_index, 50), (_n.simple_search, 50),
    ]),
]
