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

# ── ES index template mapping ───────────────────────────────────────────────

INDEX_TEMPLATE = {
    "index_patterns": ["applicative-load-observability-*"],
    "priority": 100,
    "template": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "5s",
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "timestamp": {"type": "date"},
                "identity": {
                    "properties": {
                        "username":             {"type": "keyword"},
                        "applicative_provider": {"type": "keyword"},
                        "user_agent":           {"type": "keyword"},
                        "client_host":          {"type": "keyword"},
                    }
                },
                "request": {
                    "properties": {
                        "method":     {"type": "keyword"},
                        "path":       {"type": "keyword"},
                        "operation":  {"type": "keyword"},
                        "target":     {"type": "keyword"},
                        "template":   {"type": "keyword"},
                        "body":       {"type": "object", "enabled": False},
                        "size_bytes": {"type": "integer"},
                        "size":       {"type": "integer"},
                    }
                },
                "response": {
                    "properties": {
                        "es_took_ms":      {"type": "float"},
                        "gateway_took_ms": {"type": "float"},
                        "hits":            {"type": "long"},
                        "shards_total":    {"type": "integer"},
                        "docs_affected":   {"type": "long"},
                        "size_bytes":      {"type": "integer"},
                    }
                },
                "clause_counts": {
                    "properties": {
                        "bool":            {"type": "integer"},
                        "bool_must":       {"type": "integer"},
                        "bool_should":     {"type": "integer"},
                        "bool_filter":     {"type": "integer"},
                        "bool_must_not":   {"type": "integer"},
                        "terms_values":    {"type": "integer"},
                        "knn":             {"type": "integer"},
                        "fuzzy":           {"type": "integer"},
                        "geo_bbox":        {"type": "integer"},
                        "geo_distance":    {"type": "integer"},
                        "geo_shape":       {"type": "integer"},
                        "agg":             {"type": "integer"},
                        "wildcard":        {"type": "integer"},
                        "nested":          {"type": "integer"},
                        "runtime_mapping": {"type": "integer"},
                        "script":          {"type": "integer"},
                    }
                },
                "cost_indicators": {
                    "properties": {
                        "has_script":          {"type": "integer"},
                        "has_runtime_mapping": {"type": "integer"},
                        "has_wildcard":        {"type": "integer"},
                        "has_nested":          {"type": "integer"},
                        "has_fuzzy":           {"type": "integer"},
                        "has_geo":             {"type": "integer"},
                        "has_knn":             {"type": "integer"},
                        "excessive_bool":      {"type": "integer"},
                        "large_terms_list":    {"type": "integer"},
                        "deep_aggs":           {"type": "integer"},
                    }
                },
                "stress": {
                    "properties": {
                        "score":                {"type": "float"},
                        "multiplier":           {"type": "float"},
                        "cost_indicator_count": {"type": "integer"},
                        "cost_indicator_names": {"type": "keyword"},
                    }
                },
                # Error records (partial)
                "error":  {"type": "text"},
                "path":   {"type": "keyword"},
                "method": {"type": "keyword"},
            }
        }
    }
}

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

# Ordered per dashboard layout: Application → Target → Operation → Cost Indicator → Template
SECTIONS = [
    ("identity.applicative_provider", "Application"),
    ("request.target",                "Target"),
    ("request.operation",             "Operation"),
    ("stress.cost_indicator_names",   "Cost Indicator"),
    ("request.template",              "Template"),
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


def mk_pie(vis_id, title, field, size=8):
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
                    "breakdown": {"label": field.split(".")[-1], "dataType": "string",
                                  "operationType": "terms", "sourceField": field, "isBucketed": True,
                                  "params": {"size": size, "orderBy": {"type": "column", "columnId": "metric"},
                                             "orderDirection": "desc", "otherBucket": True}},
                    "metric": {"label": "Total Stress", "dataType": "number",
                               "operationType": "sum", "sourceField": "stress.score", "isBucketed": False},
                },
                "columnOrder": ["breakdown", "metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_ts(vis_id, title, field, metric_field="stress.score", metric_label="Avg Stress Score",
          metric_op="average", size=5):
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
                    "breakdown": {"label": field.split(".")[-1], "dataType": "string",
                                  "operationType": "terms", "sourceField": field, "isBucketed": True,
                                  "params": {"size": size, "orderBy": {"type": "column", "columnId": "metric"},
                                             "orderDirection": "desc", "otherBucket": True}},
                    "metric": {"label": metric_label, "dataType": "number",
                               "operationType": metric_op, "sourceField": metric_field, "isBucketed": False},
                },
                "columnOrder": ["time", "breakdown", "metric"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_ts_response(vis_id, title, breakdown_field, latency_field, latency_label, size=5):
    """Time series: avg latency over time, split by breakdown_field, with request count as secondary axis."""
    return vis_id, {
        "title": title, "visualizationType": "lnsXY",
        "state": {
            "visualization": {
                "preferredSeriesType": "line",
                "layers": [{"layerId": "layer1", "layerType": "data", "seriesType": "line",
                            "xAccessor": "time", "accessors": ["latency", "count"], "splitAccessor": "breakdown"}],
                "legend": {"isVisible": True, "position": "right"},
                "axisTitlesVisibilitySettings": {"x": False, "yLeft": True, "yRight": True},
                "yLeftExtent": {"mode": "dataBounds"},
                "yRightExtent": {"mode": "dataBounds"},
            },
            "datasourceStates": {"formBased": {"layers": {"layer1": {
                "columns": {
                    "time": {"label": "timestamp", "dataType": "date", "operationType": "date_histogram",
                             "sourceField": "timestamp", "isBucketed": True, "params": {"interval": "auto"}},
                    "breakdown": {"label": breakdown_field.split(".")[-1], "dataType": "string",
                                  "operationType": "terms", "sourceField": breakdown_field, "isBucketed": True,
                                  "params": {"size": size, "orderBy": {"type": "column", "columnId": "latency"},
                                             "orderDirection": "desc", "otherBucket": True}},
                    "latency": {"label": latency_label, "dataType": "number",
                                "operationType": "average", "sourceField": latency_field, "isBucketed": False},
                    "count": {"label": "Requests", "dataType": "number",
                              "operationType": "count", "sourceField": "___records___", "isBucketed": False},
                },
                "columnOrder": ["time", "breakdown", "latency", "count"], "incompleteColumns": {},
            }}}},
            "query": {"query": "", "language": "kuery"}, "filters": [],
        },
    }


def mk_ci_metric(vis_id, title, source_field, operation, kql_filter=None):
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
        "breakdown": {"label": field.split(".")[-1], "dataType": "string",
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


def layout_main(vis_ids, panels, refs):
    """
    Layout structure (mapped to improvement notes):

    Row 0 (y=0, h=10):   5 pie charts in one row — Application, Target, Operation, Cost Indicator, Template
                          (Note 1: KPI panels removed; Note 5: pies in one line, this order)
    Row 1-5 (h=12 each): 5 stress-over-time charts, same order as pies
                          (Note 5.1: same order; Note 5.2: grouped after pies to avoid confusion)
    Row 6 (h=14):         Top 10 Templates by Stress Score table
                          (Note 6: sum stress, avg ES/gateway latency, cost indicators, requests)
    Row 7-8 (h=12 each): Avg ES Response Time — by Cost Indicator, by Operation, by Template
                          Avg Gateway Response Time — by Cost Indicator, by Operation, by Template
                          (Note 8: two latency types × 3 breakdowns, request count on hover)
    Row 9 (h=12):         Sanity check tables — most recurring templates, most cost indicators
                          (Note 7: sanity tables at the bottom)
    """
    y = 0

    # --- Row 0: 5 pie charts (indices 0-4) ---
    pie_w = 48 // 5  # ~9 each, last one gets remainder
    for i in range(5):
        vid = vis_ids[i]
        w = pie_w if i < 4 else 48 - pie_w * 4
        panels.append({"panelIndex": vid, "gridData": {"x": i * pie_w, "y": y, "w": w, "h": 10, "i": vid},
                       "type": "lens", "panelRefName": f"panel_{vid}"})
        refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
    y += 10

    # --- Rows 1-5: 5 stress-over-time charts (indices 5-9) ---
    for i in range(5):
        vid = vis_ids[5 + i]
        panels.append({"panelIndex": vid, "gridData": {"x": 0, "y": y, "w": 48, "h": 12, "i": vid},
                       "type": "lens", "panelRefName": f"panel_{vid}"})
        refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
        y += 12

    # --- Row 6: Top Templates by Stress Score table (index 10) ---
    vid = vis_ids[10]
    panels.append({"panelIndex": vid, "gridData": {"x": 0, "y": y, "w": 48, "h": 14, "i": vid},
                   "type": "lens", "panelRefName": f"panel_{vid}"})
    refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
    y += 14

    # --- Rows 7-8: Response time panels (indices 11-16), 3 per row ---
    for row_start in (11, 14):
        for j in range(3):
            vid = vis_ids[row_start + j]
            panels.append({"panelIndex": vid, "gridData": {"x": j * 16, "y": y, "w": 16, "h": 12, "i": vid},
                           "type": "lens", "panelRefName": f"panel_{vid}"})
            refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
        y += 12

    # --- Row 9: 2 sanity check tables (indices 17-18) ---
    for j in range(2):
        vid = vis_ids[17 + j]
        panels.append({"panelIndex": vid, "gridData": {"x": j * 24, "y": y, "w": 24, "h": 12, "i": vid},
                       "type": "lens", "panelRefName": f"panel_{vid}"})
        refs.append({"type": "lens", "id": vid, "name": f"panel_{vid}"})
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
