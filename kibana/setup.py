#!/usr/bin/env python3
"""
Set up the Applicative Load Observability dashboard in Kibana.

By default, imports the pre-built dashboard.ndjson.
Use --rebuild to recreate everything from scratch via the API and re-export.

Usage:
    python kibana/setup.py                         # import dashboard.ndjson
    python kibana/setup.py --rebuild               # recreate via API + re-export
    python kibana/setup.py --kibana http://host:5601
"""

import argparse
import json
import os
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

KIBANA = "http://localhost:5601"
ELASTICSEARCH = "http://localhost:9200"
INDEX_PATTERN = "applicative-load-observability-v2"
DATA_VIEW_ID = "alo-data-view"
DASHBOARD_ID = "alo-dashboard"
CI_DASHBOARD_ID = "alo-ci-dashboard"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NDJSON_PATH = os.path.join(SCRIPT_DIR, "dashboard.ndjson")
CI_NDJSON_PATH = os.path.join(SCRIPT_DIR, "dashboard-cost-indicators.ndjson")

# ── helpers ──────────────────────────────────────────────────────────────────

def kbn(method, path, body=None):
    url = f"{KIBANA}{path}"
    headers = {"kbn-xsrf": "true", "Content-Type": "application/json"}
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


def es_request(method, path, body=None):
    url = f"{ELASTICSEARCH}{path}"
    headers = {"Content-Type": "application/json"}
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


INDEX_TEMPLATE = {
    "index_patterns": ["applicative-load-observability*"],
    "priority": 100,
    "template": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "dynamic": "true",
            "properties": {
                "timestamp":             {"type": "date"},
                "method":                {"type": "keyword"},
                "path":                  {"type": "keyword"},
                "operation":             {"type": "keyword"},
                "target":                {"type": "keyword"},
                "template":              {"type": "keyword"},
                "applicative_provider":  {"type": "keyword"},
                "username":              {"type": "keyword"},
                "user_agent":            {"type": "keyword"},
                "client_host":           {"type": "keyword"},

                "stress_score":          {"type": "float"},
                "stress_multiplier":     {"type": "float"},
                "es_took_ms":            {"type": "float"},
                "gateway_took_ms":       {"type": "float"},

                "hits":                  {"type": "long"},
                "size":                  {"type": "long"},
                "shards_total":          {"type": "long"},
                "docs_affected":         {"type": "long"},
                "request_size_bytes":    {"type": "long"},
                "response_size_bytes":   {"type": "long"},

                "cost_indicators":       {"type": "keyword"},
                "cost_indicator_count":  {"type": "integer"},

                "bool_clause_count":     {"type": "integer"},
                "bool_must_count":       {"type": "integer"},
                "bool_should_count":     {"type": "integer"},
                "bool_filter_count":     {"type": "integer"},
                "bool_must_not_count":   {"type": "integer"},
                "terms_values_count":    {"type": "integer"},
                "knn_clause_count":      {"type": "integer"},
                "fuzzy_clause_count":    {"type": "integer"},
                "geo_bbox_count":        {"type": "integer"},
                "geo_distance_count":    {"type": "integer"},
                "geo_shape_count":       {"type": "integer"},
                "agg_clause_count":      {"type": "integer"},
                "wildcard_clause_count": {"type": "integer"},
                "nested_clause_count":   {"type": "integer"},
                "runtime_mapping_count": {"type": "integer"},
                "script_clause_count":   {"type": "integer"},
            },
        },
    },
}


def ensure_index_template():
    s, _ = es_request("PUT", "/_index_template/applicative-load-observability", INDEX_TEMPLATE)
    print(f"  {'OK' if s in (200, 201) else 'FAIL'}: Index template")
    return s in (200, 201)


def wait_kibana():
    print("  Waiting for Kibana ...", end=" ", flush=True)
    for _ in range(30):
        try:
            s, _ = kbn("GET", "/api/status")
            if s == 200:
                print("ready")
                return
        except Exception:
            pass
        time.sleep(2)
    print("TIMEOUT"); sys.exit(1)


def upsert(obj_type, obj_id, attrs, refs=None):
    kbn("DELETE", f"/api/saved_objects/{obj_type}/{obj_id}")
    body = {"attributes": attrs}
    if refs:
        body["references"] = refs
    s, _ = kbn("POST", f"/api/saved_objects/{obj_type}/{obj_id}", body)
    return s in (200, 201)


# ── import mode ──────────────────────────────────────────────────────────────

def import_ndjson(path, label):
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

    url = f"{KIBANA}/api/saved_objects/_import?overwrite=true"
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


def do_import():
    ok1 = import_ndjson(NDJSON_PATH, "main dashboard")
    ok2 = import_ndjson(CI_NDJSON_PATH, "cost indicators dashboard")
    return ok1 and ok2


# ── rebuild mode ─────────────────────────────────────────────────────────────

DV_REF = [{"type": "index-pattern", "id": DATA_VIEW_ID, "name": "indexpattern-datasource-layer-layer1"}]

SECTIONS = [
    ("template",              "Template"),
    ("operation",             "Operation"),
    ("target",                "Target"),
    ("applicative_provider",  "Application"),
]


def mk_metric(vis_id, title, source_field, operation):
    col = {"label": title, "dataType": "number", "operationType": operation, "isBucketed": False}
    col["sourceField"] = "___records___" if operation == "count" else source_field
    return vis_id, {
        "title": title, "visualizationType": "lnsMetric",
        "state": {
            "visualization": {"layerId": "layer1", "layerType": "data", "metricAccessor": "metric"},
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": {"metric": col}, "columnOrder": ["metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_pie(vis_id, title, field):
    return vis_id, {
        "title": title, "visualizationType": "lnsPie",
        "state": {
            "visualization": {
                "shape": "donut",
                "layers": [{"layerId": "layer1", "layerType": "data",
                            "primaryGroups": ["breakdown"], "metrics": ["metric"],
                            "numberDisplay": "percent", "categoryDisplay": "default",
                            "legendDisplay": "default", "legendPosition": "right"}],
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": {
                    "breakdown": {"label": field.split(".")[0], "dataType": "string",
                                  "operationType": "terms", "sourceField": field, "isBucketed": True,
                                  "params": {"size": 8, "orderBy": {"type": "column", "columnId": "metric"},
                                             "orderDirection": "desc", "otherBucket": True}},
                    "metric": {"label": "Total Stress", "dataType": "number",
                               "operationType": "sum", "sourceField": "stress_score", "isBucketed": False},
                },
                "columnOrder": ["breakdown", "metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_ts(vis_id, title, field):
    return vis_id, {
        "title": title, "visualizationType": "lnsXY",
        "state": {
            "visualization": {
                "preferredSeriesType": "area",
                "layers": [{"layerId": "layer1", "layerType": "data", "seriesType": "area",
                            "xAccessor": "time", "accessors": ["metric"], "splitAccessor": "breakdown"}],
                "legend": {"isVisible": True, "position": "right"},
                "axisTitlesVisibilitySettings": {"x": False, "yLeft": True, "yRight": True},
                "yLeftExtent": {"mode": "dataBounds"},
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": {
                    "time": {"label": "timestamp", "dataType": "date", "operationType": "date_histogram",
                             "sourceField": "timestamp", "isBucketed": True, "params": {"interval": "auto"}},
                    "breakdown": {"label": field.split(".")[0], "dataType": "string",
                                  "operationType": "terms", "sourceField": field, "isBucketed": True,
                                  "params": {"size": 5, "orderBy": {"type": "column", "columnId": "metric"},
                                             "orderDirection": "desc", "otherBucket": True}},
                    "metric": {"label": "Avg Stress Score", "dataType": "number",
                               "operationType": "average", "sourceField": "stress_score", "isBucketed": False},
                },
                "columnOrder": ["time", "breakdown", "metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_rf_metric(vis_id, title, source_field, operation, kql_filter=None):
    col = {"label": title, "dataType": "number", "operationType": operation, "isBucketed": False}
    col["sourceField"] = "___records___" if operation == "count" else source_field
    if kql_filter:
        col["filter"] = {"language": "kuery", "query": kql_filter}
    return vis_id, {
        "title": title, "visualizationType": "lnsMetric",
        "state": {
            "visualization": {"layerId": "layer1", "layerType": "data", "metricAccessor": "metric"},
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": {"metric": col}, "columnOrder": ["metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_horizontal_bar(vis_id, title, field, metric_field, metric_op, metric_label, size=10):
    cols = {
        "breakdown": {"label": field.split(".")[0], "dataType": "string",
                      "operationType": "terms", "sourceField": field, "isBucketed": True,
                      "params": {"size": size, "orderBy": {"type": "column", "columnId": "metric"},
                                 "orderDirection": "desc", "otherBucket": False}},
        "metric": {"label": metric_label, "dataType": "number",
                   "operationType": metric_op, "isBucketed": False},
    }
    cols["metric"]["sourceField"] = "___records___" if metric_op == "count" else metric_field
    return vis_id, {
        "title": title, "visualizationType": "lnsXY",
        "state": {
            "visualization": {
                "preferredSeriesType": "bar_horizontal",
                "layers": [{"layerId": "layer1", "layerType": "data", "seriesType": "bar_horizontal",
                            "xAccessor": "breakdown", "accessors": ["metric"]}],
                "legend": {"isVisible": False},
                "axisTitlesVisibilitySettings": {"x": False, "yLeft": False, "yRight": False},
                "valueLabels": "show",
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": cols, "columnOrder": ["breakdown", "metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_ts_multi(vis_id, title, metrics, series_type="line"):
    """Time series with multiple metric columns (no breakdown/split)."""
    cols = {
        "time": {"label": "timestamp", "dataType": "date", "operationType": "date_histogram",
                 "sourceField": "timestamp", "isBucketed": True, "params": {"interval": "auto"}},
    }
    col_order = ["time"]
    accessors = []
    for col_id, label, field, op in metrics:
        c = {"label": label, "dataType": "number", "operationType": op, "sourceField": field, "isBucketed": False}
        if op == "count":
            c["sourceField"] = "___records___"
            if field:
                c["filter"] = {"language": "kuery", "query": field}
        cols[col_id] = c
        col_order.append(col_id)
        accessors.append(col_id)
    return vis_id, {
        "title": title, "visualizationType": "lnsXY",
        "state": {
            "visualization": {
                "preferredSeriesType": series_type,
                "layers": [{"layerId": "layer1", "layerType": "data", "seriesType": series_type,
                            "xAccessor": "time", "accessors": accessors}],
                "legend": {"isVisible": True, "position": "right"},
                "axisTitlesVisibilitySettings": {"x": False, "yLeft": True, "yRight": True},
                "yLeftExtent": {"mode": "dataBounds"},
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": cols, "columnOrder": col_order, "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_datatable(vis_id, title, bucket_field, bucket_label, metrics, size=10):
    cols = {
        "bucket": {"label": bucket_label, "dataType": "string",
                   "operationType": "terms", "sourceField": bucket_field, "isBucketed": True,
                   "params": {"size": size, "orderBy": {"type": "column", "columnId": metrics[0][0]},
                              "orderDirection": "desc", "otherBucket": False}},
    }
    col_order = ["bucket"]
    vis_columns = [{"columnId": "bucket"}]
    for col_id, label, field, op in metrics:
        c = {"label": label, "dataType": "number", "operationType": op, "isBucketed": False}
        c["sourceField"] = "___records___" if op == "count" else field
        cols[col_id] = c
        col_order.append(col_id)
        vis_columns.append({"columnId": col_id})
    return vis_id, {
        "title": title, "visualizationType": "lnsDatatable",
        "state": {
            "visualization": {"columns": vis_columns, "layerId": "layer1", "layerType": "data"},
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": cols, "columnOrder": col_order, "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def export_dashboard(dashboard_id, ndjson_path):
    url = f"{KIBANA}/api/saved_objects/_export"
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


def build_dashboard(dashboard_id, title, description, vis_ids, layout_fn):
    panels, refs = [], []
    layout_fn(vis_ids, panels, refs)
    ok = upsert("dashboard", dashboard_id, {
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


def layout_main(vis_ids, panels, refs):
    y = 0
    for i, vid in enumerate(vis_ids[:4]):
        panels.append({"panelIndex": vid, "gridData": {"x": i*12, "y": y, "w": 12, "h": 6, "i": vid},
                       "type": "lens", "panelRefName": f"panel_{vid}"})
        refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
    y += 6
    for j in range(0, len(vis_ids[4:]), 2):
        pid, tid = vis_ids[4+j], vis_ids[4+j+1]
        panels.append({"panelIndex": pid, "gridData": {"x": 0, "y": y, "w": 16, "h": 12, "i": pid},
                       "type": "lens", "panelRefName": f"panel_{pid}"})
        panels.append({"panelIndex": tid, "gridData": {"x": 16, "y": y, "w": 32, "h": 12, "i": tid},
                       "type": "lens", "panelRefName": f"panel_{tid}"})
        refs.append({"type": "lens", "id": pid, "name": f"panel_{pid}"})
        refs.append({"type": "lens", "id": tid, "name": f"panel_{tid}"})
        y += 12


def layout_cost_indicators(vis_ids, panels, refs):
    grid = [
        # Row 0: KPIs (h=6)
        (vis_ids[0],  0,  0, 12, 6),
        (vis_ids[1], 12,  0, 12, 6),
        (vis_ids[2], 24,  0, 12, 6),
        (vis_ids[3], 36,  0, 12, 6),
        # Row 1: Indicator overview (h=14)
        (vis_ids[4],  0,  6, 20, 14),
        (vis_ids[5], 20,  6, 28, 14),
        # Row 2: Clause counts (h=14)
        (vis_ids[6],  0, 20, 28, 14),
        (vis_ids[7], 28, 20, 20, 14),
        # Row 3: Table (h=12)
        (vis_ids[8],  0, 34, 48, 12),
        # Row 4: By dimension (h=14)
        (vis_ids[9],   0, 46, 24, 14),
        (vis_ids[10], 24, 46, 24, 14),
    ]
    for vid, x, y, w, h in grid:
        panels.append({"panelIndex": vid, "gridData": {"x": x, "y": y, "w": w, "h": h, "i": vid},
                       "type": "lens", "panelRefName": f"panel_{vid}"})
        refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})


def do_rebuild():
    # Data view
    kbn("DELETE", f"/api/data_views/data_view/{DATA_VIEW_ID}")
    s, _ = kbn("POST", "/api/data_views/data_view", {
        "data_view": {"id": DATA_VIEW_ID, "title": INDEX_PATTERN,
                      "timeFieldName": "timestamp", "name": "Applicative Load Observability"},
        "override": True,
    })
    print(f"  {'OK' if s in (200,201) else 'FAIL'}: Data view")

    # ── Main dashboard visualizations ──
    all_vis = [
        mk_metric("alo-kpi-requests",   "Total Requests",       "stress_score",    "count"),
        mk_metric("alo-kpi-stress",     "Avg Stress Score",     "stress_score",    "average"),
        mk_metric("alo-kpi-latency",    "Avg Latency (ms)",     "gateway_took_ms", "average"),
        mk_metric("alo-kpi-multiplier", "Avg Stress Multiplier", "stress_multiplier", "average"),
    ]
    for field, label in SECTIONS:
        all_vis.append(mk_pie(f"alo-pie-{label.lower()}", f"Stress Share — {label}", field))
        all_vis.append(mk_ts(f"alo-ts-{label.lower()}", f"Stress Over Time — {label}", field))

    vis_ids = []
    for vid, attrs in all_vis:
        ok = upsert("lens", vid, attrs, DV_REF)
        print(f"  {'OK' if ok else 'FAIL'}: {attrs['title']}")
        vis_ids.append(vid)

    ok1 = build_dashboard(DASHBOARD_ID, "Applicative Load Observability",
                          "Stress scores by template, operation, target, and application.",
                          vis_ids, layout_main)

    # ── Cost indicators dashboard visualizations ──
    print()
    ci_vis = [
        mk_rf_metric("alo-ci-kpi-flagged",    "Flagged Requests",           "cost_indicator_count", "count", "cost_indicator_count >= 1"),
        mk_rf_metric("alo-ci-kpi-avg-flags",   "Avg Indicator Count",       "cost_indicator_count", "average"),
        mk_rf_metric("alo-ci-kpi-avg-mult",    "Avg Stress Multiplier",     "stress_multiplier",    "average"),
        mk_rf_metric("alo-ci-kpi-max-mult",    "Max Stress Multiplier",     "stress_multiplier",    "max"),
        mk_horizontal_bar("alo-ci-bar-indicator-types", "Cost Indicator Types — Frequency",
                          "cost_indicators", None, "count", "Count"),
        mk_ts_multi("alo-ci-ts-flag-rate", "Flagged vs Total Requests Over Time", [
            ("flagged", "Flagged Requests", "cost_indicator_count >= 1", "count"),
            ("total",   "Total Requests",   "",                          "count"),
        ], "area"),
        mk_ts_multi("alo-ci-ts-clause-counts", "Clause Count Trends", [
            ("terms_avg",    "Avg terms_values_count",    "terms_values_count",    "average"),
            ("aggs_avg",     "Avg agg_clause_count",      "agg_clause_count",      "average"),
            ("script_avg",   "Avg script_clause_count",   "script_clause_count",   "average"),
            ("wildcard_avg", "Avg wildcard_clause_count", "wildcard_clause_count", "average"),
        ], "line"),
        mk_ts_multi("alo-ci-ts-bool", "Bool Clause Breakdown Over Time", [
            ("must",      "Avg must",     "bool_must_count",     "average"),
            ("should",    "Avg should",   "bool_should_count",   "average"),
            ("filter_c",  "Avg filter",   "bool_filter_count",   "average"),
            ("must_not",  "Avg must_not", "bool_must_not_count", "average"),
        ], "area_stacked"),
        mk_datatable("alo-ci-table-templates", "Top Templates by Cost Indicator Count",
                     "template", "Template", [
                         ("avg_indicators", "Avg Indicators", "cost_indicator_count", "average"),
                         ("count",          "Requests",       None,                   "count"),
                         ("avg_mult",       "Avg Multiplier", "stress_multiplier",    "average"),
                         ("avg_stress",     "Avg Stress",     "stress_score",         "average"),
                     ]),
        mk_horizontal_bar("alo-ci-bar-apps", "Stress Multiplier by Application",
                          "applicative_provider", "stress_multiplier", "average",
                          "Avg Stress Multiplier", 8),
        mk_horizontal_bar("alo-ci-bar-targets", "Cost Indicator Count by Target Index",
                          "target", "cost_indicator_count", "average",
                          "Avg Indicator Count", 8),
    ]

    ci_ids = []
    for vid, attrs in ci_vis:
        ok = upsert("lens", vid, attrs, DV_REF)
        print(f"  {'OK' if ok else 'FAIL'}: {attrs['title']}")
        ci_ids.append(vid)

    ok2 = build_dashboard(CI_DASHBOARD_ID, "Cost Indicators & Query Patterns",
                          "Cost indicators, clause counts, and query pattern analysis.",
                          ci_ids, layout_cost_indicators)

    # Export both dashboards
    print()
    export_dashboard(DASHBOARD_ID, NDJSON_PATH)
    export_dashboard(CI_DASHBOARD_ID, CI_NDJSON_PATH)

    return ok1 and ok2


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    global KIBANA, ELASTICSEARCH
    parser = argparse.ArgumentParser(description="Set up the ALO Kibana dashboard")
    parser.add_argument("--kibana", default=KIBANA, help="Kibana URL (default: %(default)s)")
    parser.add_argument("--elasticsearch", default=ELASTICSEARCH,
                        help="Elasticsearch URL (default: %(default)s)")
    parser.add_argument("--rebuild", action="store_true",
                        help="Recreate all objects via API and re-export dashboard.ndjson")
    args = parser.parse_args()
    KIBANA = args.kibana
    ELASTICSEARCH = args.elasticsearch

    print(f"\n  Kibana:        {KIBANA}")
    print(f"  Elasticsearch: {ELASTICSEARCH}\n")
    wait_kibana()
    ensure_index_template()

    if args.rebuild:
        print("  Mode: rebuild\n")
        ok = do_rebuild()
    else:
        print("  Mode: import\n")
        ok = do_import()

    if ok:
        print(f"\n  Main dashboard:      {KIBANA}/app/dashboards#/view/{DASHBOARD_ID}")
        print(f"  Cost indicators dashboard: {KIBANA}/app/dashboards#/view/{CI_DASHBOARD_ID}\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
