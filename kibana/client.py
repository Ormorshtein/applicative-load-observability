"""HTTP client helpers for Elasticsearch and Kibana APIs."""

import json
import os
import sys
import time
from dataclasses import dataclass, field
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from index_template import INDEX_TEMPLATE


@dataclass
class StackConfig:
    kibana_url: str = field(
        default_factory=lambda: os.getenv("KIBANA_URL", "http://localhost:5601"))
    elasticsearch_url: str = field(
        default_factory=lambda: os.getenv("ELASTICSEARCH_URL", "http://localhost:9200"))


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


def ensure_index_template(cfg: StackConfig) -> bool:
    status, _ = es_request(cfg, "PUT", "/_index_template/alo-template",
                           INDEX_TEMPLATE)
    print(f"  {'OK' if status in (200, 201) else 'FAIL'}: Index template (alo-template)")
    return status in (200, 201)
