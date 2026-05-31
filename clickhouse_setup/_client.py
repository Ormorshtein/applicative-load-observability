"""Minimal HTTP client for ClickHouse setup.

Uses ``urllib`` only — same approach as ``analyzer/_baselines.py`` so the
``ch-setup`` image needs no extra Python dependencies. The setup job issues a
small number of DDL statements; a heavyweight driver would be overkill.
"""

import os
import ssl
import sys
import time
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_HTTP_TIMEOUT = 30
_WAIT_ATTEMPTS = 60
_WAIT_INTERVAL = 2.0


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").lower() in ("1", "true", "yes")


@dataclass
class ClickHouseConfig:
    url: str = field(
        default_factory=lambda: os.getenv("CLICKHOUSE_URL", "http://127.0.0.1:8123"))
    user: str = field(
        default_factory=lambda: os.getenv("CLICKHOUSE_USER", "default"))
    password: str = field(
        default_factory=lambda: os.getenv("CLICKHOUSE_PASSWORD", ""))
    database: str = field(
        default_factory=lambda: os.getenv("CLICKHOUSE_DATABASE", "alo"))
    ca_cert: str = field(
        default_factory=lambda: os.getenv("CLICKHOUSE_CA_CERT", ""))
    insecure: bool = field(
        default_factory=lambda: _env_bool("CLICKHOUSE_INSECURE"))
    cluster: str = field(
        default_factory=lambda: os.getenv("CLICKHOUSE_CLUSTER", ""))


def _build_ssl_context(cfg: ClickHouseConfig) -> ssl.SSLContext | None:
    if cfg.insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if cfg.ca_cert:
        return ssl.create_default_context(cafile=cfg.ca_cert)
    return None


def _build_headers(cfg: ClickHouseConfig) -> dict[str, str]:
    # CH >= 22 rejects mixing X-ClickHouse-* and Authorization headers
    # ("It is not allowed to use X-ClickHouse HTTP headers and Authorization
    #  HTTP header simultaneously"). Use X-ClickHouse-* only — native and
    # required for any modern CH.
    headers: dict[str, str] = {"Content-Type": "text/plain; charset=utf-8"}
    if cfg.user:
        headers["X-ClickHouse-User"] = cfg.user
    if cfg.password:
        headers["X-ClickHouse-Key"] = cfg.password
    return headers


def ping(cfg: ClickHouseConfig) -> bool:
    url = f"{cfg.url.rstrip('/')}/ping"
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT,
                     context=_build_ssl_context(cfg)) as resp:
            return resp.status == 200
    except (HTTPError, URLError, OSError, TimeoutError):
        return False


def wait_clickhouse(cfg: ClickHouseConfig) -> None:
    print(f"  Waiting for ClickHouse at {cfg.url} ...", end=" ", flush=True)
    for _ in range(_WAIT_ATTEMPTS):
        if ping(cfg):
            print("ready")
            return
        time.sleep(_WAIT_INTERVAL)
    print("TIMEOUT")
    sys.exit(1)


def execute(cfg: ClickHouseConfig, sql: str,
            *, use_database: bool = True) -> tuple[int, str]:
    """Execute a single SQL/DDL statement against ClickHouse over HTTP.

    Returns (http_status, body). 200 means success. CH echoes errors in the
    response body with non-200 status; we surface both so callers can log
    the actual message.
    """
    base = cfg.url.rstrip("/")
    query_string = f"?database={cfg.database}" if use_database else ""
    url = f"{base}/{query_string}"
    headers = _build_headers(cfg)

    data = sql.encode("utf-8")
    req = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT,
                     context=_build_ssl_context(cfg)) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, body
    except (URLError, OSError, TimeoutError) as e:
        return 0, str(e)


def execute_or_die(cfg: ClickHouseConfig, label: str, sql: str,
                   *, use_database: bool = True) -> bool:
    """Run a DDL and print a status line. Returns success flag."""
    status, body = execute(cfg, sql, use_database=use_database)
    ok = status == 200
    print(f"  {'OK  ' if ok else 'FAIL'}: {label}")
    if not ok:
        snippet = body.strip().splitlines()[:5]
        for line in snippet:
            print(f"          {line}")
    return ok
