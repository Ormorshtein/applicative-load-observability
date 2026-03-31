"""HTTP client helpers for Elasticsearch and Kibana APIs."""

import base64
import json
import os
import ssl
import sys
import time
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_HTTP_TIMEOUT = 30

from _index_template import (
    COMPONENT_TEMPLATE,
    COMPONENT_TEMPLATE_NAME,
    ILM_POLICIES,
    INDEX_TEMPLATES,
    SUMMARY_INDEX_TEMPLATE,
    SUMMARY_TRANSFORM,
    SUMMARY_TRANSFORM_ID,
)


@dataclass
class StackConfig:
    kibana_url: str = field(
        default_factory=lambda: os.getenv("KIBANA_URL", "http://127.0.0.1:5601"))
    elasticsearch_url: str = field(
        default_factory=lambda: os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
    username: str = field(
        default_factory=lambda: os.getenv("ES_USERNAME", ""))
    password: str = field(
        default_factory=lambda: os.getenv("ES_PASSWORD", ""))
    es_ca_cert: str = field(
        default_factory=lambda: os.getenv("ES_CA_CERT", ""))
    es_insecure: bool = field(
        default_factory=lambda: os.getenv("ES_INSECURE", "").lower() in ("1", "true", "yes"))
    kibana_ca_cert: str = field(
        default_factory=lambda: os.getenv("KIBANA_CA_CERT", ""))
    kibana_insecure: bool = field(
        default_factory=lambda: os.getenv("KIBANA_INSECURE", "").lower() in ("1", "true", "yes"))


def _build_ssl_context(ca_cert: str = "", insecure: bool = False) -> ssl.SSLContext | None:
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if ca_cert:
        return ssl.create_default_context(cafile=ca_cert)
    return None


def _build_auth_header(cfg: StackConfig) -> str | None:
    if cfg.username and cfg.password:
        credentials = base64.b64encode(
            f"{cfg.username}:{cfg.password}".encode()).decode()
        return f"Basic {credentials}"
    return None


def _http_json(cfg: StackConfig, base_url: str, method: str, path: str,
               body: dict | None = None,
               extra_headers: dict[str, str] | None = None,
               ssl_ctx: ssl.SSLContext | None = None) -> tuple[int, dict]:
    url = f"{base_url}{path}"
    headers = {"Content-Type": "application/json"}
    auth = _build_auth_header(cfg)
    if auth:
        headers["Authorization"] = auth
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        resp = urlopen(req, timeout=_HTTP_TIMEOUT, context=ssl_ctx)
        return resp.status, json.loads(resp.read() or b"{}")
    except HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}
    except (URLError, OSError, TimeoutError):
        return 0, {}


def kibana_request(cfg: StackConfig, method: str, path: str,
                   body: dict | None = None) -> tuple[int, dict]:
    ssl_ctx = _build_ssl_context(cfg.kibana_ca_cert, cfg.kibana_insecure)
    return _http_json(cfg, cfg.kibana_url, method, path, body,
                      extra_headers={"kbn-xsrf": "true"}, ssl_ctx=ssl_ctx)


def es_request(cfg: StackConfig, method: str, path: str,
               body: dict | None = None) -> tuple[int, dict]:
    ssl_ctx = _build_ssl_context(cfg.es_ca_cert, cfg.es_insecure)
    return _http_json(cfg, cfg.elasticsearch_url, method, path, body,
                      ssl_ctx=ssl_ctx)


def wait_for_service(cfg: StackConfig, name: str, check_fn) -> None:
    print(f"  Waiting for {name} ...", end=" ", flush=True)
    last_error = ""
    for _ in range(30):
        try:
            status, _ = check_fn(cfg)
            if status == 200:
                print("ready")
                return
        except ssl.SSLError as e:
            print(f"TLS error: {e}")
            sys.exit(1)
        except Exception as e:
            last_error = str(e)
        time.sleep(2)
    print(f"TIMEOUT (last error: {last_error})" if last_error else "TIMEOUT")
    sys.exit(1)


def wait_kibana(cfg: StackConfig) -> None:
    wait_for_service(cfg, "Kibana",
                     lambda c: kibana_request(c, "GET", "/api/status"))


def wait_es(cfg: StackConfig) -> None:
    wait_for_service(cfg, "Elasticsearch",
                     lambda c: es_request(c, "GET", "/_cluster/health"))


def upsert(cfg: StackConfig, obj_type: str, obj_id: str,
           attrs: dict, refs: list[dict] | None = None) -> bool:
    kibana_request(cfg, "DELETE", f"/api/saved_objects/{obj_type}/{obj_id}")
    body = {"attributes": attrs}
    if refs:
        body["references"] = refs
    status, _ = kibana_request(cfg, "POST",
                               f"/api/saved_objects/{obj_type}/{obj_id}", body)
    return status in (200, 201)


def _put_ok(status: int) -> bool:
    return status in (200, 201)


def _status_label(ok: bool) -> str:
    return "OK" if ok else "FAIL"


def ensure_es_resources(cfg: StackConfig) -> bool:
    """Create ILM policies, component template, and composable index templates."""
    all_ok = True

    # 1. ILM policies (referenced by index templates)
    for name, body in ILM_POLICIES.items():
        status, _ = es_request(cfg, "PUT", f"/_ilm/policy/{name}", body)
        ok = _put_ok(status)
        print(f"  {_status_label(ok)}: ILM policy ({name})")
        all_ok &= ok

    # 2. Component template (referenced by composable templates)
    status, _ = es_request(
        cfg, "PUT",
        f"/_component_template/{COMPONENT_TEMPLATE_NAME}",
        COMPONENT_TEMPLATE,
    )
    ok = _put_ok(status)
    print(f"  {_status_label(ok)}: Component template ({COMPONENT_TEMPLATE_NAME})")
    all_ok &= ok

    # 3. Composable index templates
    for name, body in INDEX_TEMPLATES.items():
        status, _ = es_request(cfg, "PUT", f"/_index_template/{name}", body)
        ok = _put_ok(status)
        print(f"  {_status_label(ok)}: Index template ({name})")
        all_ok &= ok

    # Clean up the legacy single template if it exists
    es_request(cfg, "DELETE", "/_index_template/alo-template")

    # 4. Summary index template (long-term retention)
    status, _ = es_request(
        cfg, "PUT", "/_index_template/alo-summary", SUMMARY_INDEX_TEMPLATE,
    )
    ok = _put_ok(status)
    print(f"  {_status_label(ok)}: Summary index template (alo-summary)")
    all_ok &= ok

    # 5. Continuous transform for summary aggregation
    # Stop existing transform before updating (PUT requires it stopped)
    es_request(cfg, "POST", f"/_transform/{SUMMARY_TRANSFORM_ID}/_stop")
    status, _ = es_request(
        cfg, "PUT", f"/_transform/{SUMMARY_TRANSFORM_ID}",
        SUMMARY_TRANSFORM,
    )
    ok = _put_ok(status)
    print(f"  {_status_label(ok)}: Summary transform ({SUMMARY_TRANSFORM_ID})")
    all_ok &= ok
    if ok:
        es_request(cfg, "POST", f"/_transform/{SUMMARY_TRANSFORM_ID}/_start")

    return all_ok
