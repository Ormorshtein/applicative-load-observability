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
INDEX_PATTERN = "applicative-load-observability"
DATA_VIEW_ID = "alo-data-view"
DASHBOARD_ID = "alo-dashboard"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NDJSON_PATH = os.path.join(SCRIPT_DIR, "dashboard.ndjson")

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

def do_import():
    if not os.path.exists(NDJSON_PATH):
        print(f"  ERROR: {NDJSON_PATH} not found. Run with --rebuild first.")
        sys.exit(1)

    with open(NDJSON_PATH, "rb") as f:
        ndjson_data = f.read()

    boundary = "----KibanaDashboardImport"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="dashboard.ndjson"\r\n'
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
            print(f"  Imported {count} objects successfully")
        else:
            print(f"  Imported {count} objects with errors:")
            for err in result.get("errors", []):
                print(f"    {err.get('id')}: {err.get('error', {}).get('message', '')[:200]}")
        return result.get("success", False)
    except HTTPError as e:
        print(f"  Import failed: {e.code} {e.read().decode()[:300]}")
        return False


# ── rebuild mode ─────────────────────────────────────────────────────────────

DV_REF = [{"type": "index-pattern", "id": DATA_VIEW_ID, "name": "indexpattern-datasource-layer-layer1"}]

SECTIONS = [
    ("template.keyword",              "Template"),
    ("operation.keyword",             "Operation"),
    ("target.keyword",                "Target"),
    ("applicative_provider.keyword",  "Application"),
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


def do_rebuild():
    # Data view
    kbn("DELETE", f"/api/data_views/data_view/{DATA_VIEW_ID}")
    s, _ = kbn("POST", "/api/data_views/data_view", {
        "data_view": {"id": DATA_VIEW_ID, "title": INDEX_PATTERN,
                      "timeFieldName": "timestamp", "name": "Applicative Load Observability"},
        "override": True,
    })
    print(f"  {'OK' if s in (200,201) else 'FAIL'}: Data view")

    # Visualizations
    all_vis = [
        mk_metric("alo-kpi-requests",   "Total Requests",       "stress_score",    "count"),
        mk_metric("alo-kpi-stress",     "Avg Stress Score",     "stress_score",    "average"),
        mk_metric("alo-kpi-latency",    "Avg Latency (ms)",     "gateway_took_ms", "average"),
        mk_metric("alo-kpi-complexity", "Avg Query Complexity", "query_complexity","average"),
    ]
    for field, label in SECTIONS:
        all_vis.append(mk_pie(f"alo-pie-{label.lower()}", f"Stress Share — {label}", field))
        all_vis.append(mk_ts(f"alo-ts-{label.lower()}", f"Stress Over Time — {label}", field))

    vis_ids = []
    for vid, attrs in all_vis:
        ok = upsert("lens", vid, attrs, DV_REF)
        print(f"  {'OK' if ok else 'FAIL'}: {attrs['title']}")
        vis_ids.append(vid)

    # Dashboard
    panels, refs = [], []
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

    ok = upsert("dashboard", DASHBOARD_ID, {
        "title": "Applicative Load Observability",
        "description": "Stress scores by template, operation, target, and application.",
        "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(
            {"query": {"query": "", "language": "kuery"}, "filter": []})},
        "panelsJSON": json.dumps(panels),
        "timeRestore": True, "timeTo": "now", "timeFrom": "now-24h",
        "refreshInterval": {"pause": False, "value": 30000},
        "optionsJSON": json.dumps({"useMargins": True, "syncColors": True,
                                    "syncCursor": True, "syncTooltips": True,
                                    "hidePanelTitles": False}),
    }, refs)
    print(f"  {'OK' if ok else 'FAIL'}: Dashboard")

    # Export
    print()
    url = f"{KIBANA}/api/saved_objects/_export"
    body = json.dumps({"objects": [{"type": "dashboard", "id": DASHBOARD_ID}],
                       "includeReferencesDeep": True}).encode()
    req = Request(url, data=body, headers={"kbn-xsrf": "true", "Content-Type": "application/json"}, method="POST")
    try:
        resp = urlopen(req, timeout=30)
        ndjson = resp.read().decode()
        with open(NDJSON_PATH, "w", encoding="utf-8") as f:
            f.write(ndjson)
        count = sum(1 for l in ndjson.strip().split("\n") if l.strip()) - 1
        print(f"  Exported {count} objects to {NDJSON_PATH}")
    except HTTPError as e:
        print(f"  Export failed: {e.code}")

    return ok


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    global KIBANA
    parser = argparse.ArgumentParser(description="Set up the ALO Kibana dashboard")
    parser.add_argument("--kibana", default=KIBANA, help="Kibana URL (default: %(default)s)")
    parser.add_argument("--rebuild", action="store_true",
                        help="Recreate all objects via API and re-export dashboard.ndjson")
    args = parser.parse_args()
    KIBANA = args.kibana

    print(f"\n  Kibana: {KIBANA}\n")
    wait_kibana()

    if args.rebuild:
        print("  Mode: rebuild\n")
        ok = do_rebuild()
    else:
        print("  Mode: import\n")
        ok = do_import()

    if ok:
        print(f"\n  Dashboard: {KIBANA}/app/dashboards#/view/{DASHBOARD_ID}\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
