"""Culprit + task configs for the forced refresh challenge.

The culprit appends ?refresh=true to every index and bulk operation,
forcing segment merges after every write.  This prevents ES from
batching merges efficiently, causing elevated took_ms across all
operations — reads included.
"""

import json
import random

from _trivial_noise import make_noise
from helpers import ndjson, rand_doc, rand_str

INDEX = "challenge-forced-refresh"
APP_NAME = "cms-backend"
CULPRIT = "content-writer"
DESCRIPTION = "Challenge: Forced Refresh — find the service forcing segment merges"
HINT = "One service needs read-your-writes consistency at any cost."
CULPRIT_EXPLANATION = (
    "The culprit appended ?refresh=true to every write operation.\n"
    "  Each forced segment merge is cheap alone, but at high write\n"
    "  rates it prevents ES from batching merges, causing elevated\n"
    "  took_ms even for other services' reads.")
MISS_EXPLANATION = (
    "Look for ?refresh=true in request paths.  The culprit's write\n"
    "  path forces segment merges, degrading cluster-wide performance.")
SCRIPT_BUILDERS = ()
MAX_DOCS = 200000

_n = make_noise(INDEX, APP_NAME)


def _forced_refresh_index(gw, tr):
    """Single index with ?refresh=true — forced segment merge."""
    doc_id = tr.pick() if not tr.writes_allowed else rand_str(12)
    s, _ = _n.send(gw, "PUT",
                   f"/{INDEX}/_doc/{doc_id}?refresh=true", rand_doc())
    if 200 <= s < 300 and tr.writes_allowed:
        tr.remember(doc_id)
    return "index", s


def _forced_refresh_bulk(gw, tr):
    """Small bulk with ?refresh=true."""
    capped = not tr.writes_allowed
    actions = []
    for _ in range(random.randint(3, 8)):
        did = tr.pick() if capped else rand_str(12)
        if did is None:
            did = rand_str(12)
        actions.append(json.dumps({"index": {"_index": INDEX, "_id": did}}))
        actions.append(json.dumps(rand_doc()))
        if not capped:
            tr.remember(did)
    s, _ = _n.send(gw, "POST", "/_bulk?refresh=true",
                   ndjson(actions),
                   content_type="application/x-ndjson", timeout=30)
    return "_bulk", s


TASK_CONFIGS = [
    ("page-reader", 4, 40, [
        (_n.simple_search, 50), (_n.match_all, 30), (_n.light_bool, 20),
    ]),
    ("asset-manager", 4, 50, [
        (_n.single_index, 40), (_n.simple_search, 40), (_n.match_all, 20),
    ]),
    ("content-writer", 3, 60, [
        (_forced_refresh_index, 60), (_forced_refresh_bulk, 25),
        (_n.simple_search, 15),
    ]),
    ("draft-saver", 4, 50, [
        (_n.single_index, 40), (_n.simple_search, 30), (_n.light_bool, 30),
    ]),
    ("publish-queue", 4, 40, [
        (lambda gw, tr: _n.bulk_index(gw, tr, 5, 15), 40),
        (_n.simple_search, 40), (_n.match_all, 20),
    ]),
    ("search-indexer", 4, 50, [
        (_n.simple_search, 40), (_n.light_agg, 30), (_n.light_bool, 30),
    ]),
    ("revision-log", 3, 60, [
        (_n.single_index, 50), (_n.match_all, 50),
    ]),
]
