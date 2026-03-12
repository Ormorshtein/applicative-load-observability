"""Culprit + task configs for the oversized bulk batches challenge.

The culprit sends infrequent but massive bulk requests (500-2000 docs).
Each request is expensive and blocks cluster resources.  Few requests,
but each one dominates the cluster.
"""

import json
import random

from helpers import rand_doc, rand_str
from _trivial_noise import make_noise

INDEX = "challenge-mega-bulk"
APP_NAME = "data-importer"
CULPRIT = "csv-loader"
DESCRIPTION = "Challenge: Oversized Bulk — find the service sending mega-batches"
HINT = "One service sends very large payloads infrequently."
CULPRIT_EXPLANATION = (
    "The culprit sent bulk requests with 500-2000 documents each.\n"
    "  Each request is expensive: bulk stress 0.55×(docs/500) = 0.55-2.2\n"
    "  from docs_affected alone, plus high took_ms.  Few requests,\n"
    "  but each one dominated the cluster.")
MISS_EXPLANATION = (
    "Look at response.docs_affected and response.es_took_ms per _bulk\n"
    "  request.  The culprit has very low count but extreme per-request\n"
    "  impact.")
SCRIPT_BUILDERS = ()
MAX_DOCS = 200000

_n = make_noise(INDEX, APP_NAME)


def _mega_bulk(gw, tr):
    """Massive bulk request (500-2000 docs)."""
    capped = not tr.writes_allowed
    count = random.randint(500, 2000)
    actions = []
    for _ in range(count):
        did = tr.pick() if capped else rand_str(12)
        if did is None:
            did = rand_str(12)
        actions.append(json.dumps({"index": {"_index": INDEX, "_id": did}}))
        actions.append(json.dumps(rand_doc()))
        if not capped:
            tr.remember(did)
    s, _ = _n.send(gw, "POST", "/_bulk", "\n".join(actions) + "\n",
                   content_type="application/x-ndjson", timeout=120)
    return "_bulk", s


TASK_CONFIGS = [
    ("api-ingest", 3, 60, [
        (_n.simple_search, 50), (_n.match_all, 30), (_n.light_bool, 20),
    ]),
    ("delta-sync", 3, 80, [
        (lambda gw, tr: _n.bulk_index(gw, tr, 5, 15), 10),
        (_n.simple_search, 50), (_n.match_all, 40),
    ]),
    ("transform-worker", 3, 60, [
        (_n.simple_search, 40), (_n.light_bool, 30), (_n.light_agg, 30),
    ]),
    ("quality-check", 3, 80, [
        (_n.simple_search, 50), (_n.match_all, 30), (_n.light_bool, 20),
    ]),
    ("backup-service", 2, 100, [
        (_n.match_all, 50), (_n.simple_search, 50),
    ]),
    ("csv-loader", 3, 500, [
        (_mega_bulk, 90), (_n.simple_search, 10),
    ]),
    ("index-optimizer", 2, 100, [
        (_n.simple_search, 40), (_n.light_agg, 40), (_n.match_all, 20),
    ]),
]
