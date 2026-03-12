"""Culprit + task configs for the shadow flood challenge.

The culprit sends the EXACT SAME templates as noise — indistinguishable
by query structure.  12 workers, zero delay, 10x normal rate.  The only
signal is request volume.  Template analysis is useless — diagnosis
requires stopping services and observing the req/s drop.
"""

from _trivial_noise import make_noise

INDEX = "challenge-shadow-flood"
APP_NAME = "notification-service"
CULPRIT = "event-poller"
DESCRIPTION = "Challenge: Shadow Flood — find the invisible flood"
HINT = (
    "Per-request stress is low everywhere.  Templates look identical.\n"
    "  The dashboard can't help — this requires process of elimination.")
CULPRIT_EXPLANATION = (
    "The culprit sent perfectly efficient queries (size 20, simple\n"
    "  match/term) — but at 10x the rate of any other service.\n"
    "  No caching layer, polling every few ms in a tight loop.\n"
    "  Diagnosis requires looking at throughput, not per-query cost.")
MISS_EXPLANATION = (
    "The culprit's queries looked identical to noise — the only signal\n"
    "  was request volume.  Stop services and watch req/s drop.")
SCRIPT_BUILDERS = ()

_n = make_noise(INDEX, APP_NAME)

# Culprit uses the exact same simple queries as noise — indistinguishable
# by template.  The only signal is volume (12 workers, 0ms think time).

TASK_CONFIGS = [
    ("digest-builder", 3, 80, [
        (_n.simple_search, 30), (_n.light_agg, 40), (_n.light_bool, 30),
    ]),
    ("user-prefs", 3, 100, [
        (_n.simple_search, 50), (_n.match_all, 30), (_n.single_index, 20),
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
    ("event-poller", 12, 0, [
        (_n.simple_search, 50), (_n.match_all, 50),
    ]),
]
