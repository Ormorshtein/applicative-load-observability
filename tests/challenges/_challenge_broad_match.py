"""Culprit + task configs for the broad text match challenge.

The culprit sends 1-2 word queries using common short English words
with size 200-500.  These broad terms match nearly every document,
producing massive hit counts.  No cost indicators trigger.

Documents are seeded with real English words (not random strings) so
that short common terms like "the", "to", "an" match thousands of docs.
"""

import random

from helpers import (
    rand_category, rand_color, rand_price, rand_int, rand_str,
)
from _trivial_noise import make_noise

INDEX = "challenge-broad-match"
APP_NAME = "search-api"
CULPRIT = "autocomplete"
DESCRIPTION = "Challenge: Broad Text Match — find the search-bar spam"
HINT = "One service has no minimum query-length validation."
CULPRIT_EXPLANATION = (
    "The culprit sent common short words ('the', 'to', 'an') that match\n"
    "  nearly every document, producing massive hit counts + size 200-500.\n"
    "  No cost indicators triggered — stress came from the hits component\n"
    "  and high es_took_ms on broad text matches.")
MISS_EXPLANATION = (
    "Look for services with disproportionately high response.hits\n"
    "  and response.es_took_ms on _search operations.")
SCRIPT_BUILDERS = ()

# -- English word pool for seeding and searching --------------------------

_COMMON_WORDS = [
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her",
    "she", "or", "an", "will", "my", "one", "all", "would", "there",
    "their", "what", "so", "up", "out", "if", "about", "who", "get",
    "which", "go", "me", "when", "make", "can", "like", "time", "no",
    "just", "him", "know", "take", "people", "into", "year", "your",
    "good", "some", "could", "them", "see", "other", "than", "then",
    "now", "look", "only", "come", "its", "over", "think", "also",
    "back", "after", "use", "two", "how", "our", "work", "first",
    "well", "way", "even", "new", "want", "because", "any", "these",
    "give", "day", "most", "us", "great", "between", "need", "large",
    "home", "big", "high", "old", "long", "small", "own", "right",
    "still", "find", "here", "thing", "many", "run", "down", "should",
    "call", "world", "each", "made", "live", "real", "set", "try",
    "hand", "point", "keep", "name", "head", "turn", "move", "end",
]

# Short words the culprit searches — these appear in nearly every document
_BROAD_TERMS = [w for w in _COMMON_WORDS if len(w) <= 3]


def _english_text(words=15):
    """Generate text from common English words."""
    return " ".join(random.choice(_COMMON_WORDS)
                    for _ in range(random.randint(words - 5, words + 5)))


def _english_doc():
    """Document with English-word text fields for broad match testing."""
    return {
        "title": _english_text(5),
        "description": _english_text(25),
        "category": rand_category(),
        "price": rand_price(),
        "quantity": rand_int(0, 500),
        "color": rand_color(),
        "tags": random.sample(["sale", "new", "popular", "limited",
                                "exclusive", "clearance", "premium"],
                               k=random.randint(1, 4)),
        "rating": round(random.uniform(1.0, 5.0), 1),
        "location": {"lat": round(random.uniform(29.0, 47.0), 4),
                      "lon": round(random.uniform(-124.0, -71.0), 4)},
        "created_at": f"2025-{random.randint(1, 12):02d}-"
                      f"{random.randint(1, 28):02d}",
    }


SEED_DOC_FN = _english_doc

_n = make_noise(INDEX, APP_NAME)


def _broad_match_search(gw, tr):
    """Short common words returning massive hit counts."""
    term = random.choice(_BROAD_TERMS)
    size = random.randint(200, 500)
    q = random.choice([
        {"query": {"match": {"description": term}}, "size": size},
        {"query": {"multi_match": {
            "query": term,
            "fields": ["title", "description"],
        }}, "size": size},
    ])
    return _n.search(gw, q)


TASK_CONFIGS = [
    ("full-search", 4, 40, [
        (_n.simple_search, 50), (_n.light_bool, 30), (_n.match_all, 20),
    ]),
    ("filter-panel", 4, 50, [
        (_n.light_bool, 50), (_n.simple_search, 30), (_n.light_agg, 20),
    ]),
    ("catalog-browse", 4, 40, [
        (_n.match_all, 40), (_n.simple_search, 40), (_n.single_index, 20),
    ]),
    ("trending-queries", 4, 50, [
        (_n.light_agg, 40), (_n.simple_search, 40), (_n.match_all, 20),
    ]),
    ("analytics-feed", 3, 60, [
        (lambda gw, tr: _n.bulk_index(gw, tr, 5, 15), 50),
        (_n.single_index, 30), (_n.simple_search, 20),
    ]),
    ("autocomplete", 3, 60, [
        (_broad_match_search, 80), (_n.simple_search, 20),
    ]),
]
