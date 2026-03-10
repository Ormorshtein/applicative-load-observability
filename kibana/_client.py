"""HTTP client helpers for Elasticsearch and Kibana APIs."""

import json
import os
import sys
import time
from dataclasses import dataclass, field
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from _index_template import (
    COMPONENT_TEMPLATE,
    COMPONENT_TEMPLATE_NAME,
    ILM_POLICIES,
    INDEX_TEMPLATES,
)


@dataclass
class StackConfig:
    kibana_url: str = field(
        default_factory=lambda: os.getenv("KIBANA_URL", "http://127.0.0.1:5601"))
    elasticsearch_url: str = field(
        default_factory=lambda: os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"))


def _http_json(base_url: str, method: str, path: str,
               body: dict | None = None,
               extra_headers: dict[str, str] | None = None) -> tuple[int, dict]:
    url = f"{base_url}{path}"
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        resp = urlopen(req, timeout=30)
        return resp.status, json.loads(resp.read() or b"{}")
    except HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def kibana_request(cfg: StackConfig, method: str, path: str,
                   body: dict | None = None) -> tuple[int, dict]:
    return _http_json(cfg.kibana_url, method, path, body,
                      extra_headers={"kbn-xsrf": "true"})


def es_request(cfg: StackConfig, method: str, path: str,
               body: dict | None = None) -> tuple[int, dict]:
    return _http_json(cfg.elasticsearch_url, method, path, body)


def wait_for_service(cfg: StackConfig, name: str, check_fn) -> None:
    print(f"  Waiting for {name} ...", end=" ", flush=True)
    for _ in range(30):
        try:
            status, _ = check_fn(cfg)
            if status == 200:
                print("ready")
                return
        except Exception:
            pass
        time.sleep(2)
    print("TIMEOUT")
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

    return all_ok
