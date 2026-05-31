#!/usr/bin/env python3
"""
Set up Grafana for Applicative Load Observability (ClickHouse datasource).

Two modes:
  --mode provision  (default) Generate provisioning files for volume-mounted Grafana.
  --mode api        Push datasource + dashboards to an existing Grafana via HTTP API.

Usage:
    python -m grafana.setup
    python -m grafana.setup --prometheus-url http://prometheus:9090
    python -m grafana.setup --mode api --grafana http://grafana:3000
    python -m grafana.setup --mode api --grafana http://grafana:3000 \\
        --clickhouse-url http://clickhouse:8123 --user default --password xxx
"""

import argparse
import base64
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ._dashboard_builders import (
    build_cost_indicators_dashboard,
    build_main_dashboard,
    build_main_dashboard_he,
    build_usage_dashboard,
)
from ._health_dashboard import build_health_dashboard
from ._dashboards import export_dashboards
from ._datasource import (
    _parse_host,
    generate_datasource_yaml,
    generate_prometheus_datasource_yaml,
)

DATASOURCE_UID = "alo-clickhouse"


# ΓöÇΓöÇ HTTP helpers ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

def _auth_header(username: str, password: str) -> str:
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


# ΓöÇΓöÇ API mode ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

def wait_grafana(grafana_url, username, password):
    print("  Waiting for Grafana ...", end=" ", flush=True)
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


def create_datasource(grafana_url, clickhouse_url, username, password,
                      ch_user="default", ch_password="", ch_database="alo",
                      ch_native_port=9000, ch_insecure=False):
    host, http_port, secure = _parse_host(clickhouse_url)
    port = ch_native_port if ch_native_port else http_port
    protocol = "native" if ch_native_port else "http"
    json_data = {
        "host": host,
        "port": port,
        "protocol": protocol,
        "secure": secure,
        "tlsSkipVerify": ch_insecure,
        "username": ch_user,
        "defaultDatabase": ch_database,
    }
    secure_json = {"password": ch_password}
    body = {
        "name": "ClickHouse (ALO)",
        "type": "grafana-clickhouse-datasource",
        "uid": DATASOURCE_UID,
        "access": "proxy",
        "isDefault": True,
        "jsonData": json_data,
        "secureJsonData": secure_json,
    }
    # Upsert: update first, then create.
    status, _ = _grafana_request(
        grafana_url, "PUT", f"/api/datasources/uid/{DATASOURCE_UID}",
        body=body, username=username, password=password)
    if status in (200, 201):
        print("  OK: Datasource (updated)")
        return True
    status, _ = _grafana_request(
        grafana_url, "POST", "/api/datasources",
        body=body, username=username, password=password)
    ok = status in (200, 201)
    label = "created" if ok else f"FAIL ({status})"
    print(f"  {'OK' if ok else 'FAIL'}: Datasource ({label})")
    return ok


PROMETHEUS_DATASOURCE_UID = "alo-prometheus"


def create_prometheus_datasource(grafana_url, prometheus_url, username, password):
    if not prometheus_url:
        return True
    body = {
        "name": "Prometheus (ALO)",
        "type": "prometheus",
        "uid": PROMETHEUS_DATASOURCE_UID,
        "access": "proxy",
        "url": prometheus_url,
        "isDefault": False,
        "jsonData": {"httpMethod": "POST", "timeInterval": "15s"},
    }
    status, _ = _grafana_request(
        grafana_url, "PUT", f"/api/datasources/uid/{PROMETHEUS_DATASOURCE_UID}",
        body=body, username=username, password=password)
    if status in (200, 201):
        print("  OK: Prometheus datasource (updated)")
        return True
    status, _ = _grafana_request(
        grafana_url, "POST", "/api/datasources",
        body=body, username=username, password=password)
    ok = status in (200, 201)
    label = "created" if ok else f"FAIL ({status})"
    print(f"  {'OK' if ok else 'FAIL'}: Prometheus datasource ({label})")
    return ok


def import_dashboard(grafana_url, dashboard, username, password):
    body = {"dashboard": dashboard, "overwrite": True, "folderId": 0}
    body["dashboard"].pop("id", None)
    status, resp = _grafana_request(
        grafana_url, "POST", "/api/dashboards/db",
        body=body, username=username, password=password)
    ok = status == 200
    title = dashboard.get("title", "?")
    url = resp.get("url", "")
    print(f"  {'OK' if ok else 'FAIL'}: {title} ({url})")
    return ok


def do_api_setup(grafana_url, clickhouse_url, username, password,
                 ch_user="default", ch_password="", ch_database="alo",
                 ch_native_port=9000, ch_insecure=False, ch_ca_cert="",
                 datasource=True, dashboards=True, health_dashboard=True,
                 prometheus_url=""):
    if not wait_grafana(grafana_url, username, password):
        return False

    print()
    all_ok = True
    if datasource:
        all_ok = create_datasource(grafana_url, clickhouse_url, username, password,
                                   ch_user=ch_user, ch_password=ch_password,
                                   ch_database=ch_database,
                                   ch_native_port=ch_native_port,
                                   ch_insecure=ch_insecure)
        if prometheus_url:
            all_ok &= create_prometheus_datasource(
                grafana_url, prometheus_url, username, password)

    if dashboards:
        builders = [build_main_dashboard, build_main_dashboard_he,
                    build_cost_indicators_dashboard, build_usage_dashboard]
        if health_dashboard:
            builders.append(build_health_dashboard)
        for builder in builders:
            all_ok &= import_dashboard(grafana_url, builder(), username, password)

    print(f"\n  Main dashboard:            {grafana_url}/d/alo-main")
    print(f"  Main dashboard (Hebrew):   {grafana_url}/d/alo-main-he")
    print(f"  Cost indicators dashboard: {grafana_url}/d/alo-cost-indicators")
    print(f"  Usage dashboard:           {grafana_url}/d/alo-usage")
    if dashboards and health_dashboard:
        print(f"  Stack Health dashboard:    {grafana_url}/d/alo-health")
    print()
    return all_ok


# ΓöÇΓöÇ Provision mode ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

def do_provision(clickhouse_url, grafana_url, prometheus_url="",
                 ch_user="default", ch_password="", ch_database="alo",
                 ch_native_port=9000, ch_insecure=False, ch_ca_cert=""):
    print("  Generating provisioning files:\n")
    generate_datasource_yaml(clickhouse_url=clickhouse_url,
                             database=ch_database,
                             native_port=ch_native_port,
                             username=ch_user,
                             password=ch_password,
                             insecure_skip_verify=ch_insecure,
                             ch_ca_cert=ch_ca_cert)
    generate_prometheus_datasource_yaml(prometheus_url)
    export_dashboards()
    print(f"\n  Main dashboard:            {grafana_url}/d/alo-main")
    print(f"  Main dashboard (Hebrew):   {grafana_url}/d/alo-main-he")
    print(f"  Cost indicators dashboard: {grafana_url}/d/alo-cost-indicators")
    print(f"  Cluster usage dashboard:   {grafana_url}/d/alo-usage\n")
    print("  Mount grafana/provisioning/ at /etc/grafana/provisioning/.")
    print("  Dashboards will load automatically on startup.\n")
    return True


# ΓöÇΓöÇ CLI ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

def main():
    default_ch = os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123")
    default_grafana = os.getenv("GRAFANA_URL", "http://localhost:3000")
    default_prometheus = os.getenv("PROMETHEUS_URL", "")

    parser = argparse.ArgumentParser(
        description="Set up Grafana for ALO (provisioning or API)")
    parser.add_argument(
        "--mode", choices=["provision", "api"], default="provision",
        help="'provision' generates files; 'api' pushes to Grafana (default: %(default)s)")
    parser.add_argument(
        "--clickhouse-url", default=default_ch,
        help="ClickHouse HTTP URL (default: %(default)s)")
    parser.add_argument(
        "--grafana", default=default_grafana,
        help="Grafana URL (default: %(default)s)")
    parser.add_argument(
        "--prometheus-url", default=default_prometheus,
        help="Prometheus URL for Grafana datasource (empty to skip).")
    parser.add_argument(
        "--username", default=os.getenv("GRAFANA_USERNAME", "admin"),
        help="Grafana admin username (default: admin)")
    parser.add_argument(
        "--password", default=os.getenv("GRAFANA_ADMIN_PASSWORD", "admin"),
        help="Grafana admin password (default: admin)")

    ch_auth = parser.add_argument_group("ClickHouse datasource auth/TLS")
    ch_auth.add_argument(
        "--user", default=os.getenv("CLICKHOUSE_USER", "default"),
        help="CH username (default: %(default)s)")
    ch_auth.add_argument(
        "--ch-password", default=os.getenv("CLICKHOUSE_PASSWORD", ""),
        help="CH password (default: CLICKHOUSE_PASSWORD env)")
    ch_auth.add_argument(
        "--database", default=os.getenv("CLICKHOUSE_DATABASE", "alo"),
        help="CH database (default: %(default)s)")
    ch_auth.add_argument(
        "--native-port", type=int,
        default=int(os.getenv("CLICKHOUSE_NATIVE_PORT", "9000") or 9000),
        help="CH native protocol port (default: %(default)s; 0 = HTTP only)")
    ch_auth.add_argument(
        "--insecure", action="store_true",
        default=os.getenv("CLICKHOUSE_INSECURE", "").lower() in ("1", "true", "yes"),
        help="Skip TLS verification")
    ch_auth.add_argument(
        "--ch-ca-cert", default=os.getenv("CLICKHOUSE_CA_CERT", ""),
        help="Path to PEM CA certificate for ClickHouse TLS, or literal PEM "
             "(default: CLICKHOUSE_CA_CERT env)")

    setup_sections = parser.add_argument_group("Setup scope (api mode only)")
    setup_sections.add_argument(
        "--datasource", action=argparse.BooleanOptionalAction, default=True,
        help="Create/update the ClickHouse datasource (default: enabled)")
    setup_sections.add_argument(
        "--dashboards", action=argparse.BooleanOptionalAction, default=True,
        help="Import/update dashboards (default: enabled)")
    setup_sections.add_argument(
        "--health-dashboard", action=argparse.BooleanOptionalAction, default=True,
        help="Include the Stack Health dashboard in the import (default: enabled). "
             "Set --no-health-dashboard when no exporter is on the cluster.")

    args = parser.parse_args()

    print(f"\n  ClickHouse: {args.clickhouse_url}")
    print(f"  Grafana:    {args.grafana}")
    print(f"  Mode:       {args.mode}\n")

    if args.mode == "api":
        ok = do_api_setup(args.grafana, args.clickhouse_url, args.username,
                          args.password,
                          ch_user=args.user, ch_password=args.ch_password,
                          ch_database=args.database,
                          ch_native_port=args.native_port,
                          ch_insecure=args.insecure,
                          ch_ca_cert=args.ch_ca_cert,
                          datasource=args.datasource,
                          dashboards=args.dashboards,
                          health_dashboard=args.health_dashboard,
                          prometheus_url=args.prometheus_url)
    else:
        ok = do_provision(args.clickhouse_url, args.grafana,
                          args.prometheus_url,
                          ch_user=args.user, ch_password=args.ch_password,
                          ch_database=args.database,
                          ch_native_port=args.native_port,
                          ch_insecure=args.insecure,
                          ch_ca_cert=args.ch_ca_cert)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
