"""HTTP client, auth, and TLS helpers shared across tests and tools."""

import argparse
import base64
import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT = 15

_auth_header: str | None = None
_ssl_ctx: ssl.SSLContext | None = None


def build_ssl_context(
    ca_cert: str = "", insecure: bool = False,
) -> ssl.SSLContext | None:
    """Build an SSL context for TLS-secured Elasticsearch connections."""
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if ca_cert:
        return ssl.create_default_context(cafile=ca_cert)
    return None


def configure_auth(
    username: str = "", password: str = "",
    ca_cert: str = "", insecure: bool = False,
) -> None:
    """Call once at startup to set credentials and TLS mode for all requests."""
    global _auth_header, _ssl_ctx
    if username and password:
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        _auth_header = f"Basic {encoded}"
    else:
        _auth_header = None
    _ssl_ctx = build_ssl_context(ca_cert, insecure)


def add_auth_args(parser: argparse.ArgumentParser) -> None:
    """Add --username, --password, --ca-cert, --insecure to an argparse parser."""
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


def apply_auth_args(args: argparse.Namespace) -> None:
    """Configure global auth/TLS from parsed CLI args."""
    configure_auth(
        username=args.username,
        password=args.password,
        ca_cert=args.ca_cert,
        insecure=args.insecure,
    )


def http_request(
    gateway: str, method: str, path: str,
    body: str | bytes | dict | None = None,
    headers: dict | None = None,
    content_type: str = "application/json",
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[int, bytes]:
    """Send an HTTP request, returning (status_code, response_body)."""
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
    except (URLError, OSError) as e:
        return 0, str(e).encode()
