"""Shared helpers for integration tests — random data generators, HTTP client, stats."""

import base64
import json
import os
import random
import ssl
import string
import threading
import time
from collections import defaultdict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# Random data generators
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Auth / TLS
# ---------------------------------------------------------------------------

_auth_header: str | None = None
_ssl_ctx: ssl.SSLContext | None = None


def _build_ssl_context(ca_cert: str = "", insecure: bool = False) -> ssl.SSLContext | None:
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if ca_cert:
        return ssl.create_default_context(cafile=ca_cert)
    return None


def configure_auth(username: str = "", password: str = "",
                   ca_cert: str = "", insecure: bool = False) -> None:
    """Call once at startup to set credentials and TLS mode for all requests."""
    global _auth_header, _ssl_ctx
    if username and password:
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        _auth_header = f"Basic {encoded}"
    else:
        _auth_header = None
    _ssl_ctx = _build_ssl_context(ca_cert, insecure)


def add_auth_args(parser: "argparse.ArgumentParser") -> None:
    """Add --username, --password, --ca-cert, --insecure to an argparse parser."""
    import argparse  # noqa: F811 — local import to keep module-level imports clean
    parser.add_argument(
        "--username", default=os.getenv("ES_USERNAME", ""),
        help="Elasticsearch username (env: ES_USERNAME)")
    parser.add_argument(
        "--password", default=os.getenv("ES_PASSWORD", ""),
        help="Elasticsearch password (env: ES_PASSWORD)")
    parser.add_argument(
        "--ca-cert", default=os.getenv("ES_CA_CERT", ""),
        help="Path to CA certificate for TLS (env: ES_CA_CERT)")
    parser.add_argument(
        "--insecure", action="store_true",
        default=os.getenv("ES_INSECURE", "").lower() in ("1", "true", "yes"),
        help="Skip TLS certificate verification (env: ES_INSECURE)")


def apply_auth_args(args: "argparse.Namespace") -> None:
    """Configure global auth/TLS from parsed CLI args."""
    configure_auth(
        username=args.username,
        password=args.password,
        ca_cert=args.ca_cert,
        insecure=args.insecure,
    )


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

def http_request(gateway: str, method: str, path: str,
                 body=None, headers: dict | None = None,
                 content_type: str = "application/json",
                 timeout: int = 15) -> tuple[int, bytes]:
    url = f"{gateway}{path}"
    hdrs = {"Content-Type": content_type}
    if _auth_header:
        hdrs["Authorization"] = _auth_header
    if headers:
        hdrs.update(headers)
    if isinstance(body, str):
        data = body.encode()
    elif isinstance(body, bytes):
        data = body
    elif body is not None:
        data = json.dumps(body).encode()
    else:
        data = None
    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        resp = urlopen(req, timeout=timeout, context=_ssl_ctx)
        return resp.status, resp.read()
    except HTTPError as e:
        return e.code, e.read()
    except (URLError, OSError):
        return 0, b""


# ---------------------------------------------------------------------------
# Stats tracker
# ---------------------------------------------------------------------------

class Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counts: dict[str, int] = defaultdict(int)
        self.errors: dict[str, int] = defaultdict(int)
        self.total: int = 0
        self.start: float = time.time()

    def record(self, operation: str, status: int) -> None:
        with self._lock:
            self.total += 1
            self.counts[operation] += 1
            if status == 0 or status >= 400:
                self.errors[operation] += 1

    def report(self, label: str = "") -> None:
        elapsed = time.time() - self.start
        title = f"  {label}  ({elapsed:.1f}s)" if label else f"  Results  ({elapsed:.1f}s)"
        print(f"\n{'=' * 60}")
        print(title)
        print(f"{'=' * 60}")
        print(f"  Total requests:  {self.total}")
        print(f"  Throughput:      {self.total / max(elapsed, 0.1):.1f} req/s")
        print(f"{'=' * 60}")
        print(f"  {'Operation':<25} {'Count':>8} {'Errors':>8}")
        print(f"  {'-' * 41}")
        for op in sorted(self.counts):
            print(f"  {op:<25} {self.counts[op]:>8} {self.errors.get(op, 0):>8}")
        total_errors = sum(self.errors.values())
        print(f"  {'-' * 41}")
        print(f"  {'TOTAL':<25} {self.total:>8} {total_errors:>8}")
        print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Index mapping for load-test documents
# ---------------------------------------------------------------------------

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
