"""Dashboard assembly: import, rebuild, and export Kibana dashboards."""

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from _client import StackConfig, _build_auth_header, _build_ssl_context, kibana_request, upsert
from _dashboard_builders import (
    build_ci_visualizations,
    build_main_visualizations,
    build_usage_visualizations,
)
from _visualizations import (
    layout_cost_indicators,
    layout_main,
    layout_usage,
)

INDEX_PATTERN = "logs-alo.*-*,alo-summary"
DATA_VIEW_ID = "alo-data-view"
DASHBOARD_ID = "alo-dashboard"
CI_DASHBOARD_ID = "alo-ci-dashboard"
USAGE_DASHBOARD_ID = "alo-usage-dashboard"

# Dashboard-level controls (dropdown filters above all panels).
_CONTROLS = [
    ("cluster_name", "Cluster"),
]


def _build_control_group_input() -> dict:
    """Build Kibana controlGroupInput for dashboard-level filters."""
    panels = {}
    for idx, (field, title) in enumerate(_CONTROLS):
        panels[str(idx)] = {
            "order": idx,
            "width": "medium",
            "grow": True,
            "type": "optionsListControl",
            "explicitInput": {
                "fieldName": field,
                "title": title,
                "id": str(idx),
                "dataViewId": DATA_VIEW_ID,
                "selectedOptions": [],
                "singleSelect": False,
                "enhancements": {},
            },
        }
    return {
        "chainingSystem": "HIERARCHICAL",
        "controlStyle": "oneLine",
        "ignoreParentSettingsJSON": json.dumps({
            "ignoreFilters": False, "ignoreQuery": False,
            "ignoreTimerange": False, "ignoreValidations": False,
        }),
        "panelsJSON": json.dumps(panels),
    }
_SCRIPT_DIR = Path(__file__).resolve().parent
NDJSON_PATH = str(_SCRIPT_DIR / "dashboard.ndjson")
CI_NDJSON_PATH = str(_SCRIPT_DIR / "dashboard-cost-indicators.ndjson")
USAGE_NDJSON_PATH = str(_SCRIPT_DIR / "dashboard-usage.ndjson")
DV_REF = [{"type": "index-pattern", "id": DATA_VIEW_ID,
           "name": "indexpattern-datasource-layer-layer1"}]


# ── import mode ──────────────────────────────────────────────────────────────

def import_ndjson(cfg: StackConfig, path: str, label: str) -> bool:
    ndjson_file = Path(path)
    if not ndjson_file.exists():
        print(f"  ERROR: {path} not found. Run with --rebuild first.")
        return False

    ndjson_data = ndjson_file.read_bytes()
    filename = ndjson_file.name
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
    auth = _build_auth_header(cfg)
    if auth:
        req.add_header("Authorization", auth)
    ssl_ctx = _build_ssl_context(cfg.kibana_ca_cert, cfg.kibana_insecure)

    try:
        resp = urlopen(req, timeout=30, context=ssl_ctx)
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
    ok3 = import_ndjson(cfg, USAGE_NDJSON_PATH, "usage dashboard")
    return ok1 and ok2 and ok3


# ── export / build helpers ───────────────────────────────────────────────────

def export_dashboard(cfg: StackConfig, dashboard_id: str,
                     ndjson_path: str) -> None:
    url = f"{cfg.kibana_url}/api/saved_objects/_export"
    body = json.dumps({"objects": [{"type": "dashboard", "id": dashboard_id}],
                       "includeReferencesDeep": True}).encode()
    headers = {"kbn-xsrf": "true", "Content-Type": "application/json"}
    auth = _build_auth_header(cfg)
    if auth:
        headers["Authorization"] = auth
    ssl_ctx = _build_ssl_context(cfg.kibana_ca_cert, cfg.kibana_insecure)
    req = Request(url, data=body, headers=headers, method="POST")
    try:
        resp = urlopen(req, timeout=30, context=ssl_ctx)
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
        "controlGroupInput": _build_control_group_input(),
        "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(
            {"query": {"query": "", "language": "kuery"}, "filter": []})},
        "panelsJSON": json.dumps(panels),
        "timeRestore": True, "timeTo": "now", "timeFrom": "now-15m",
        "refreshInterval": {"pause": False, "value": 30000},
        "optionsJSON": json.dumps({"useMargins": True, "syncColors": True,
                                    "syncCursor": True, "syncTooltips": True,
                                    "hidePanelTitles": False}),
    }, refs)
    print(f"  {'OK' if ok else 'FAIL'}: {title}")
    return ok


# ── rebuild mode ─────────────────────────────────────────────────────────────

def _create_data_view(cfg: StackConfig) -> None:
    kibana_request(cfg, "DELETE", f"/api/data_views/data_view/{DATA_VIEW_ID}")
    s, _ = kibana_request(cfg, "POST", "/api/data_views/data_view", {
        "data_view": {"id": DATA_VIEW_ID, "title": INDEX_PATTERN,
                      "timeFieldName": "@timestamp", "name": "Applicative Load Observability"},
        "override": True,
    })
    print(f"  {'OK' if s in (200,201) else 'FAIL'}: Data view")



def _upsert_visualizations(
    cfg: StackConfig,
    vis_specs: list[tuple[str, dict]],
    all_lens: bool = True,
) -> list[str]:
    return _upsert_visualizations_with_ref(
        cfg, vis_specs, DV_REF if all_lens else None,
    )


def _upsert_visualizations_with_ref(
    cfg: StackConfig,
    vis_specs: list[tuple[str, dict]],
    default_ref: list[dict] | None = None,
) -> list[str]:
    vis_ids = []
    for vid, attrs in vis_specs:
        is_markdown = "visState" in attrs
        if is_markdown:
            obj_type, ref = "visualization", []
        elif default_ref is not None:
            obj_type, ref = "lens", default_ref
        else:
            obj_type, ref = "lens", DV_REF
        ok = upsert(cfg, obj_type, vid, attrs, ref)
        print(f"  {'OK' if ok else 'FAIL'}: {attrs['title']}")
        vis_ids.append(vid)
    return vis_ids


HEAVIEST_OPS_SEARCH_ID = "alo-heaviest-ops"

_HEAVIEST_OPS_COLUMNS = [
    "request.body", "identity.applicative_provider", "request.operation",
    "request.target", "request.path", "stress.score", "response.es_took_ms",
    "stress.cost_indicator_names", "_id",
]


def _create_saved_search(cfg: StackConfig, search_id: str, title: str,
                         description: str, columns: list[str],
                         sort_field: str, sort_order: str = "desc") -> None:
    attrs = {
        "title": title,
        "description": description,
        "columns": columns,
        "sort": [[sort_field, sort_order]],
        "kibanaSavedObjectMeta": {
            "searchSourceJSON": json.dumps({
                "query": {"query": "", "language": "kuery"},
                "filter": [],
                "index": DATA_VIEW_ID,
            }),
        },
    }
    refs = [{"type": "index-pattern", "id": DATA_VIEW_ID,
             "name": "kibanaSavedObjectMeta.searchSourceJSON.index"}]
    ok = upsert(cfg, "search", search_id, attrs, refs)
    print(f"  {'OK' if ok else 'FAIL'}: {title} (Saved Search)")


def do_rebuild(cfg: StackConfig) -> bool:
    _create_data_view(cfg)
    _create_saved_search(
        cfg, HEAVIEST_OPS_SEARCH_ID, "Top 10 Heaviest Operations",
        "Individual requests with highest stress scores",
        _HEAVIEST_OPS_COLUMNS, sort_field="stress.score")

    main_vis = build_main_visualizations()
    vis_ids = _upsert_visualizations(cfg, main_vis, all_lens=False)
    vis_ids.append(HEAVIEST_OPS_SEARCH_ID)
    ok1 = build_dashboard(cfg, DASHBOARD_ID,
                          "ALO \u2014 Stress Analysis",
                          "Stress analysis by application, target, operation, and template.",
                          vis_ids, layout_main)

    print()
    ci_vis = build_ci_visualizations()
    ci_ids = _upsert_visualizations(cfg, ci_vis, all_lens=False)
    ok2 = build_dashboard(cfg, CI_DASHBOARD_ID,
                          "ALO \u2014 Cost Indicators & Query Patterns",
                          "Cost indicators, clause counts, and query pattern analysis.",
                          ci_ids, layout_cost_indicators)

    print()
    usage_vis = build_usage_visualizations()
    usage_ids = _upsert_visualizations(cfg, usage_vis, all_lens=False)
    ok3 = build_dashboard(cfg, USAGE_DASHBOARD_ID,
                          "ALO \u2014 Cluster Usage",
                          "Operational overview: request rates, latency, errors, and data volume.",
                          usage_ids, layout_usage)

    print()
    export_dashboard(cfg, DASHBOARD_ID, NDJSON_PATH)
    export_dashboard(cfg, CI_DASHBOARD_ID, CI_NDJSON_PATH)
    export_dashboard(cfg, USAGE_DASHBOARD_ID, USAGE_NDJSON_PATH)

    return ok1 and ok2 and ok3
