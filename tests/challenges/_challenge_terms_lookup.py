"""Culprit + task configs for the large terms lookup challenge.

The culprit sends terms queries with 200-400 values — below the
large_terms_list cost indicator threshold of 500.  Each query evaluates
hundreds of terms across all documents.  Zero cost indicators trigger.
"""

import random

from helpers import rand_category, rand_str
from _trivial_noise import make_noise

INDEX = "challenge-terms-lookup"
APP_NAME = "order-service"
CULPRIT = "batch-resolver"
DESCRIPTION = "Challenge: Large Terms Lookup — find the IN-clause abuser"
HINT = "One service translates SQL WHERE-IN clauses to Elasticsearch."
CULPRIT_EXPLANATION = (
    "The culprit sent terms queries with 200-400 values (below the 500\n"
    "  threshold for large_terms_list).  Each query evaluates hundreds\n"
    "  of terms across all documents.  No cost indicators triggered.")
MISS_EXPLANATION = (
    "Look for elevated clause_counts.terms_values (200-400 range) with\n"
    "  high response.es_took_ms.  large_terms_list never fires (< 500).")
SCRIPT_BUILDERS = ()

_n = make_noise(INDEX, APP_NAME)


def _large_terms_search(gw, tr):
    """terms query with 300 values — below 500 threshold."""
    values = [rand_str(random.randint(4, 8)) for _ in range(300)]
    # Mix in real category values so some hits occur
    values[:5] = [rand_category() for _ in range(5)]
    random.shuffle(values)
    return _n.search(gw, {"query": {"terms": {"category": values}},
                          "size": 50})


TASK_CONFIGS = [
    ("order-search", 4, 40, [
        (_n.simple_search, 50), (_n.light_bool, 30), (_n.match_all, 20),
    ]),
    ("payment-check", 4, 50, [
        (_n.simple_search, 40), (_n.match_all, 30), (_n.light_bool, 30),
    ]),
    ("shipping-calc", 4, 50, [
        (_n.light_bool, 40), (_n.simple_search, 40), (_n.light_agg, 20),
    ]),
    ("inventory-lookup", 4, 40, [
        (_n.simple_search, 40), (_n.single_index, 30), (_n.match_all, 30),
    ]),
    ("batch-resolver", 3, 80, [
        (_large_terms_search, 80), (_n.simple_search, 20),
    ]),
    ("customer-fetch", 4, 50, [
        (_n.simple_search, 50), (_n.light_bool, 30), (_n.match_all, 20),
    ]),
    ("report-gen", 3, 60, [
        (_n.light_agg, 40), (_n.simple_search, 40), (_n.match_all, 20),
    ]),
]
