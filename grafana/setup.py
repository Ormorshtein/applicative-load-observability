#!/usr/bin/env python3
"""
Set up Grafana for Applicative Load Observability.

Two modes:
  --mode provision  (default) Generate provisioning files for volume-mounted Grafana.
  --mode api        Push datasource + dashboards to an existing Grafana via HTTP API.

Usage:
    python grafana/setup.py                                          # generate provisioning files
    python grafana/setup.py --mode api --grafana http://grafana:3000 # push to external Grafana
    python grafana/setup.py --mode api --grafana http://grafana:3000 --elasticsearch http://es:9200
"""

import argparse
import base64
import json
import os
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from _dashboards import (
    build_cost_indicators_dashboard,
    build_main_dashboard,
    export_dashboards,
)
from _datasource import generate_datasource_yaml

INDEX_PATTERN = "logs-alo.*-*"
DATASOURCE_UID = "alo-elasticsearch"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _auth_header(username, password):
    creds = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {creds}"


def _grafana_request(grafana_url, method, path, body=None,
                     username="admin", password="admin"):
    url = f"{grafana_url}{path}"
    headers = {"Content-Type": "application/json"}
    if username and password:
        headers["Authorization"] = _auth_header(username, password)
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        resp = urlopen(req, timeout=30)
        return resp.status, json.loads(resp.read() or b"{}")
    except HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:
            return exc.code, {}


# ---------------------------------------------------------------------------
# API mode — push to external Grafana
# ---------------------------------------------------------------------------

def wait_grafana(grafana_url, username, password):
    print(f"  Waiting for Grafana ...", end=" ", flush=True)
    for _ in range(30):
        try:
            status, data = _grafana_request(
                grafana_url, "GET", "/api/health", username=username,
                password=password)
            if status == 200 and data.get("database") == "ok":
                print("ready")
                return True
        except Exception:
            pass
        time.sleep(2)
    print("TIMEOUT")
    return False


def create_datasource(grafana_url, elasticsearch_url, username, password):
    body = {
        "name": "Elasticsearch (ALO)",
        "type": "elasticsearch",
        "uid": DATASOURCE_UID,
        "access": "proxy",
        "url": elasticsearch_url,
        "database": INDEX_PATTERN,
        "isDefault": False,
        "jsonData": {
            "esVersion": "8.0.0",
            "timeField": "@timestamp",
            "maxConcurrentShardRequests": 5,
        },
    }
    # Try update first, then create
    status, _ = _grafana_request(
        grafana_url, "PUT", f"/api/datasources/uid/{DATASOURCE_UID}",
        body=body, username=username, password=password)
    if status in (200, 201):
        print(f"  OK: Datasource (updated)")
        return True

    status, resp = _grafana_request(
        grafana_url, "POST", "/api/datasources",
        body=body, username=username, password=password)
    ok = status in (200, 201)
    label = "created" if ok else f"FAIL ({status})"
    print(f"  {'OK' if ok else 'FAIL'}: Datasource ({label})")
    return ok


def import_dashboard(grafana_url, dashboard, username, password):
    body = {
        "dashboard": dashboard,
        "overwrite": True,
        "folderId": 0,
    }
    # Remove id to let Grafana assign one, keep uid for idempotency
    body["dashboard"].pop("id", None)

    status, resp = _grafana_request(
        grafana_url, "POST", "/api/dashboards/db",
        body=body, username=username, password=password)
    ok = status == 200
    title = dashboard.get("title", "?")
    url = resp.get("url", "")
    print(f"  {'OK' if ok else 'FAIL'}: {title} ({url})")
    return ok


def do_api_setup(grafana_url, elasticsearch_url, username, password):
    if not wait_grafana(grafana_url, username, password):
        return False

    print()
    all_ok = create_datasource(grafana_url, elasticsearch_url, username,
                               password)

    main_dashboard = build_main_dashboard()
    ci_dashboard = build_cost_indicators_dashboard()

    all_ok &= import_dashboard(grafana_url, main_dashboard, username, password)
    all_ok &= import_dashboard(grafana_url, ci_dashboard, username, password)

    print(f"\n  Main dashboard:            {grafana_url}/d/alo-main")
    print(f"  Cost indicators dashboard: {grafana_url}/d/alo-cost-indicators\n")
    return all_ok


# ---------------------------------------------------------------------------
# Provision mode — generate files
# ---------------------------------------------------------------------------

def do_provision(elasticsearch_url, grafana_url):
    print("  Generating provisioning files:\n")
    generate_datasource_yaml(elasticsearch_url)
    export_dashboards()
    print(f"\n  Main dashboard:            {grafana_url}/d/alo-main")
    print(f"  Cost indicators dashboard: {grafana_url}/d/alo-cost-indicators\n")
    print("  Mount grafana/provisioning/ at /etc/grafana/provisioning/.")
    print("  Dashboards will load automatically on startup.\n")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    default_es = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")
    default_grafana = os.getenv("GRAFANA_URL", "http://localhost:3000")

    parser = argparse.ArgumentParser(
        description="Set up Grafana for ALO (provisioning or API)")
    parser.add_argument(
        "--mode", choices=["provision", "api"], default="provision",
        help="Setup mode: 'provision' generates files, 'api' pushes to Grafana (default: provision)")
    parser.add_argument(
        "--elasticsearch", default=default_es,
        help="Elasticsearch URL (default: %(default)s)")
    parser.add_argument(
        "--grafana", default=default_grafana,
        help="Grafana URL (default: %(default)s)")
    parser.add_argument(
        "--username", default=os.getenv("GRAFANA_USERNAME", "admin"),
        help="Grafana admin username (default: admin)")
    parser.add_argument(
        "--password", default=os.getenv("GRAFANA_ADMIN_PASSWORD", "admin"),
        help="Grafana admin password (default: admin)")
    args = parser.parse_args()

    print(f"\n  Elasticsearch: {args.elasticsearch}")
    print(f"  Grafana:       {args.grafana}")
    print(f"  Mode:          {args.mode}\n")

    if args.mode == "api":
        ok = do_api_setup(args.grafana, args.elasticsearch, args.username,
                          args.password)
    else:
        ok = do_provision(args.elasticsearch, args.grafana)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
