#!/usr/bin/env python3
"""
Set up the Applicative Load Observability stack:
  - Elasticsearch index template (mapping + settings)
  - Kibana data view and dashboards

By default, imports the pre-built dashboard.ndjson.
Use --rebuild to recreate everything from scratch via the API and re-export.

Usage:
    python kibana/setup.py                         # import dashboard.ndjson
    python kibana/setup.py --rebuild               # recreate via API + re-export
    python kibana/setup.py --kibana http://host:5601 --elasticsearch http://host:9200
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from index_template import INDEX_TEMPLATE
from visualizations import (
    SECTIONS,
    layout_cost_indicators,
    layout_main,
    mk_ci_metric,
    mk_datatable,
    mk_horizontal_bar,
    mk_pie,
    mk_ts,
    mk_ts_multi,
    mk_ts_response,
)

INDEX_PATTERN = "applicative-load-observability-v2"
DATA_VIEW_ID = "alo-data-view"
DASHBOARD_ID = "alo-dashboard"
CI_DASHBOARD_ID = "alo-ci-dashboard"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NDJSON_PATH = os.path.join(SCRIPT_DIR, "dashboard.ndjson")
CI_NDJSON_PATH = os.path.join(SCRIPT_DIR, "dashboard-cost-indicators.ndjson")


@dataclass
class StackConfig:
    kibana_url: str = field(
        default_factory=lambda: os.getenv("KIBANA_URL", "http://localhost:5601"))
    elasticsearch_url: str = field(
        default_factory=lambda: os.getenv("ELASTICSEARCH_URL", "http://localhost:9200"))

# ── helpers ──────────────────────────────────────────────────────────────────

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


# ── import mode ──────────────────────────────────────────────────────────────

def import_ndjson(cfg: StackConfig, path: str, label: str) -> bool:
    if not os.path.exists(path):
        print(f"  ERROR: {path} not found. Run with --rebuild first.")
        return False

    with open(path, "rb") as f:
        ndjson_data = f.read()

    filename = os.path.basename(path)
    boundary = "----KibanaDashboardImport"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/ndjson\r\n\r\n"
    ).encode() + ndjson_data + f"\r\n--{boundary}--\r\n".encode()

    url = f"{cfg.kibana_url}/api/saved_objects/_import?overwrite=true"
    req = Request(url, data=body, method="POST")
    req.add_header("kbn-xsrf", "true")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    try:
        resp = urlopen(req, timeout=30)
        result = json.loads(resp.read())
        count = result.get("successCount", 0)
        if result.get("success"):
            print(f"  Imported {count} objects successfully ({label})")
        else:
            print(f"  Imported {count} objects with errors ({label}):")
            for err in result.get("errors", []):
                print(f"    {err.get('id')}: {err.get('error', {}).get('message', '')[:200]}")
        return result.get("success", False)
    except HTTPError as e:
        print(f"  Import failed ({label}): {e.code} {e.read().decode()[:300]}")
        return False


def do_import(cfg: StackConfig) -> bool:
    ok1 = import_ndjson(cfg, NDJSON_PATH, "main dashboard")
    ok2 = import_ndjson(cfg, CI_NDJSON_PATH, "cost indicators dashboard")
    return ok1 and ok2


# ── rebuild mode ─────────────────────────────────────────────────────────────

DV_REF = [{"type": "index-pattern", "id": DATA_VIEW_ID, "name": "indexpattern-datasource-layer-layer1"}]


def export_dashboard(cfg: StackConfig, dashboard_id: str,
                     ndjson_path: str) -> None:
    url = f"{cfg.kibana_url}/api/saved_objects/_export"
    body = json.dumps({"objects": [{"type": "dashboard", "id": dashboard_id}],
                       "includeReferencesDeep": True}).encode()
    req = Request(url, data=body, headers={"kbn-xsrf": "true", "Content-Type": "application/json"}, method="POST")
    try:
        resp = urlopen(req, timeout=30)
        ndjson = resp.read().decode()
        with open(ndjson_path, "w", encoding="utf-8") as f:
            f.write(ndjson)
        count = sum(1 for line in ndjson.strip().split("\n") if line.strip()) - 1
        print(f"  Exported {count} objects to {ndjson_path}")
    except HTTPError as e:
        print(f"  Export failed: {e.code}")


def build_dashboard(cfg: StackConfig, dashboard_id: str, title: str,
                    description: str, vis_ids: list[str],
                    layout_fn) -> bool:
    panels, refs = [], []
    layout_fn(vis_ids, panels, refs)
    ok = upsert(cfg, "dashboard", dashboard_id, {
        "title": title,
        "description": description,
        "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(
            {"query": {"query": "", "language": "kuery"}, "filter": []})},
        "panelsJSON": json.dumps(panels),
        "timeRestore": True, "timeTo": "now", "timeFrom": "now-24h",
        "refreshInterval": {"pause": False, "value": 30000},
        "optionsJSON": json.dumps({"useMargins": True, "syncColors": True,
                                    "syncCursor": True, "syncTooltips": True,
                                    "hidePanelTitles": False}),
    }, refs)
    print(f"  {'OK' if ok else 'FAIL'}: {title}")
    return ok


def do_rebuild(cfg: StackConfig) -> bool:
    # Data view
    kibana_request(cfg, "DELETE", f"/api/data_views/data_view/{DATA_VIEW_ID}")
    s, _ = kibana_request(cfg, "POST", "/api/data_views/data_view", {
        "data_view": {"id": DATA_VIEW_ID, "title": INDEX_PATTERN,
                      "timeFieldName": "timestamp", "name": "Applicative Load Observability"},
        "override": True,
    })
    print(f"  {'OK' if s in (200,201) else 'FAIL'}: Data view")

    # ── Main dashboard visualizations ──
    # Note 1: KPI panels removed (no more top-row metrics)
    # Note 5: Pie charts ordered — Application, Target, Operation, Cost Indicator, Template

    all_vis = []

    # --- Pie charts (indices 0-4): stress share by each dimension ---
    # Note 2: renamed to include "Selected Period" to clarify time scope
    # Note 4: Template pie explicitly shows top 10 in title
    for field, label in SECTIONS:
        size = 10 if field == "request.template" else 8
        suffix = " — Top 10" if field == "request.template" else ""
        slug = label.lower().replace(" ", "-")
        all_vis.append(mk_pie(
            f"alo-pie-{slug}",
            f"Stress by {label}{suffix} (Selected Period)",
            field, size=size))

    # --- Time series (indices 5-9): stress over time, same dimension order ---
    # Note 5.1: same order as pies; Note 5.2: grouped after pies to avoid confusion
    for field, label in SECTIONS:
        size = 10 if field == "request.template" else 5
        suffix = " — Top 10" if field == "request.template" else ""
        slug = label.lower().replace(" ", "-")
        all_vis.append(mk_ts(
            f"alo-ts-{slug}",
            f"Stress Over Time by {label}{suffix}",
            field, size=size))

    # --- Table (index 10): top 10 templates by stress score ---
    # Note 6: sum stress, avg ES latency, avg gateway latency, cost indicators, requests
    all_vis.append(mk_datatable(
        "alo-table-top-templates", "Top 10 Templates by Stress Score",
        "request.template", "Template", [
            ("sum_stress",       "Sum Stress",              "stress.score",                "sum"),
            ("avg_es_latency",   "Avg ES Latency (ms)",     "response.es_took_ms",         "average"),
            ("avg_gw_latency",   "Avg Gateway Latency (ms)","response.gateway_took_ms",    "average"),
            ("cost_indicators",  "Avg Cost Indicators",     "stress.cost_indicator_count",  "average"),
            ("requests",         "Requests",                None,                           "count"),
        ], size=10))

    # --- Response time panels (indices 11-16) ---
    # Note 8: avg ES and gateway latency over time, with request count on hover
    # 3 breakdowns each: cost indicator, operation, template
    response_breakdowns = [
        ("stress.cost_indicator_names", "Cost Indicator"),
        ("request.operation",           "Operation"),
        ("request.template",            "Template"),
    ]
    for bd_field, bd_label in response_breakdowns:
        slug = bd_label.lower().replace(" ", "-")
        all_vis.append(mk_ts_response(
            f"alo-resp-es-{slug}",
            f"Avg ES Response Time by {bd_label}",
            bd_field, "response.es_took_ms", "Avg ES Latency (ms)"))

    for bd_field, bd_label in response_breakdowns:
        slug = bd_label.lower().replace(" ", "-")
        all_vis.append(mk_ts_response(
            f"alo-resp-gw-{slug}",
            f"Avg Gateway Response Time by {bd_label}",
            bd_field, "response.gateway_took_ms", "Avg Gateway Latency (ms)"))

    # --- Sanity check tables (indices 17-18) ---
    # Note 7: sanity tables at the bottom
    all_vis.append(mk_datatable(
        "alo-sanity-recurring", "Top 10 Most Recurring Templates",
        "request.template", "Template", [
            ("requests", "Requests", None, "count"),
        ], size=10))

    all_vis.append(mk_datatable(
        "alo-sanity-cost-indicators", "Top 10 Templates with Most Cost Indicators",
        "request.template", "Template", [
            ("avg_ci",   "Avg Cost Indicators", "stress.cost_indicator_count", "average"),
            ("requests", "Requests",            None,                          "count"),
        ], size=10))

    vis_ids = []
    for vid, attrs in all_vis:
        ok = upsert(cfg, "lens", vid, attrs, DV_REF)
        print(f"  {'OK' if ok else 'FAIL'}: {attrs['title']}")
        vis_ids.append(vid)

    ok1 = build_dashboard(cfg, DASHBOARD_ID, "Applicative Load Observability",
                          "Stress analysis by application, target, operation, cost indicator, and template.",
                          vis_ids, layout_main)

    # ── Cost indicators dashboard visualizations ──
    print()
    ci_vis = [
        mk_ci_metric("alo-ci-kpi-flagged",   "Flagged Requests",      "stress.cost_indicator_count", "count",
                      "stress.cost_indicator_count >= 1"),
        mk_ci_metric("alo-ci-kpi-avg-flags",  "Avg Indicator Count",  "stress.cost_indicator_count", "average"),
        mk_ci_metric("alo-ci-kpi-avg-mult",   "Avg Stress Multiplier", "stress.multiplier",          "average"),
        mk_ci_metric("alo-ci-kpi-max-mult",   "Max Stress Multiplier", "stress.multiplier",          "max"),
        mk_horizontal_bar("alo-ci-bar-indicator-types", "Cost Indicator Types — Frequency",
                          "stress.cost_indicator_names", None, "count", "Count"),
        mk_ts_multi("alo-ci-ts-flag-rate", "Flagged vs Total Requests Over Time", [
            ("flagged", "Flagged Requests", "stress.cost_indicator_count >= 1", "count"),
            ("total",   "Total Requests",   "",                                  "count"),
        ], "area"),
        mk_ts_multi("alo-ci-ts-clause-counts", "Clause Count Trends", [
            ("terms_avg",    "Avg terms_values", "clause_counts.terms_values", "average"),
            ("aggs_avg",     "Avg agg",          "clause_counts.agg",          "average"),
            ("script_avg",   "Avg script",       "clause_counts.script",       "average"),
            ("wildcard_avg", "Avg wildcard",     "clause_counts.wildcard",     "average"),
        ], "line"),
        mk_ts_multi("alo-ci-ts-bool", "Bool Clause Breakdown Over Time", [
            ("must",      "Avg must",     "clause_counts.bool_must",     "average"),
            ("should",    "Avg should",   "clause_counts.bool_should",   "average"),
            ("filter_c",  "Avg filter",   "clause_counts.bool_filter",   "average"),
            ("must_not",  "Avg must_not", "clause_counts.bool_must_not", "average"),
        ], "area_stacked"),
        mk_datatable("alo-ci-table-templates", "Top Templates by Cost Indicator Count",
                     "request.template", "Template", [
                         ("avg_indicators", "Avg Indicators", "stress.cost_indicator_count", "average"),
                         ("count",          "Requests",       None,                          "count"),
                         ("avg_mult",       "Avg Multiplier", "stress.multiplier",           "average"),
                         ("avg_stress",     "Avg Stress",     "stress.score",                "average"),
                     ]),
        mk_horizontal_bar("alo-ci-bar-apps", "Stress Multiplier by Application",
                          "identity.applicative_provider", "stress.multiplier", "average",
                          "Avg Stress Multiplier", 8),
        mk_horizontal_bar("alo-ci-bar-targets", "Cost Indicator Count by Target Index",
                          "request.target", "stress.cost_indicator_count", "average",
                          "Avg Indicator Count", 8),
    ]

    ci_ids = []
    for vid, attrs in ci_vis:
        ok = upsert(cfg, "lens", vid, attrs, DV_REF)
        print(f"  {'OK' if ok else 'FAIL'}: {attrs['title']}")
        ci_ids.append(vid)

    ok2 = build_dashboard(cfg, CI_DASHBOARD_ID, "Cost Indicators & Query Patterns",
                          "Cost indicators, clause counts, and query pattern analysis.",
                          ci_ids, layout_cost_indicators)

    # Export both dashboards
    print()
    export_dashboard(cfg, DASHBOARD_ID, NDJSON_PATH)
    export_dashboard(cfg, CI_DASHBOARD_ID, CI_NDJSON_PATH)

    return ok1 and ok2


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    defaults = StackConfig()
    parser = argparse.ArgumentParser(description="Set up the ALO stack (ES template + Kibana dashboards)")
    parser.add_argument("--kibana", default=defaults.kibana_url,
                        help="Kibana URL (default: %(default)s)")
    parser.add_argument("--elasticsearch", default=defaults.elasticsearch_url,
                        help="Elasticsearch URL (default: %(default)s)")
    parser.add_argument("--rebuild", action="store_true",
                        help="Recreate all objects via API and re-export dashboard.ndjson")
    args = parser.parse_args()

    cfg = StackConfig(kibana_url=args.kibana,
                      elasticsearch_url=args.elasticsearch)

    print(f"\n  Kibana:        {cfg.kibana_url}")
    print(f"  Elasticsearch: {cfg.elasticsearch_url}\n")

    wait_es(cfg)
    wait_kibana(cfg)
    ensure_index_template(cfg)

    if args.rebuild:
        print("  Mode: rebuild\n")
        ok = do_rebuild(cfg)
    else:
        print("  Mode: import\n")
        ok = do_import(cfg)

    if ok:
        print(f"\n  Main dashboard:            {cfg.kibana_url}/app/dashboards#/view/{DASHBOARD_ID}")
        print(f"  Cost indicators dashboard: {cfg.kibana_url}/app/dashboards#/view/{CI_DASHBOARD_ID}\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
