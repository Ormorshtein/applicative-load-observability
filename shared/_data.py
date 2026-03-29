"""Random data generators, index mapping, and NDJSON helpers."""

import random
import string


def rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


def rand_text(words: int = 10) -> str:
    return " ".join(rand_str(random.randint(3, 10)) for _ in range(words))


def rand_int(lo: int = 1, hi: int = 10000) -> int:
    return random.randint(lo, hi)


def rand_price() -> float:
    return round(random.uniform(1.0, 999.99), 2)


def rand_category() -> str:
    return random.choice(["electronics", "clothing", "food", "books",
                          "sports", "home", "toys", "automotive"])


def rand_color() -> str:
    return random.choice(["red", "blue", "green", "black", "white",
                          "yellow", "orange", "purple"])


def rand_doc() -> dict:
    return {
        "title": rand_text(random.randint(2, 6)),
        "description": rand_text(random.randint(10, 30)),
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
        "created_at": f"2025-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
    }


def ndjson(lines: list[str]) -> str:
    """Build an NDJSON body from a list of JSON-encoded lines."""
    return "\n".join(lines) + "\n"


LOADTEST_MAPPING: dict = {
    "mappings": {
        "properties": {
            "title":       {"type": "text"},
            "description": {"type": "text"},
            "category":    {"type": "keyword"},
            "price":       {"type": "float"},
            "quantity":    {"type": "integer"},
            "color":       {"type": "keyword"},
            "tags":        {"type": "keyword"},
            "rating":      {"type": "float"},
            "location":    {"type": "geo_point"},
            "created_at":  {"type": "date", "format": "yyyy-MM-dd"},
        }
    }
}
