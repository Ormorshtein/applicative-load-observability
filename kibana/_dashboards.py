"""Dashboard assembly: import, rebuild, and export Kibana dashboards."""

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from _client import StackConfig, _build_auth_header, _build_ssl_context, kibana_request, upsert
from _visualizations import (
    CHEAT_SHEET_MARKDOWN,
    PANEL_DESCRIPTIONS,
    SECTIONS,
    layout_cost_indicators,
    layout_main,
    mk_ci_metric,
    mk_datatable,
    mk_horizontal_bar,
    mk_markdown,
    mk_metric,
    mk_pie,
    mk_pie_filters,
    mk_ts,
    mk_ts_multi,
    mk_ts_response,
)

INDEX_PATTERN = "logs-alo.*-*"
DATA_VIEW_ID = "alo-data-view"
DASHBOARD_ID = "alo-dashboard"
CI_DASHBOARD_ID = "alo-ci-dashboard"
_SCRIPT_DIR = Path(__file__).resolve().parent
NDJSON_PATH = str(_SCRIPT_DIR / "dashboard.ndjson")
CI_NDJSON_PATH = str(_SCRIPT_DIR / "dashboard-cost-indicators.ndjson")

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
    return ok1 and ok2


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
    vis_ids = []
    for vid, attrs in vis_specs:
        if all_lens:
            obj_type, ref = "lens", DV_REF
        else:
            is_markdown = "visState" in attrs
            obj_type = "visualization" if is_markdown else "lens"
            ref = [] if is_markdown else DV_REF
        ok = upsert(cfg, obj_type, vid, attrs, ref)
        print(f"  {'OK' if ok else 'FAIL'}: {attrs['title']}")
        vis_ids.append(vid)
    return vis_ids


def _build_main_visualizations() -> list[tuple[str, dict]]:
    vis: list[tuple[str, dict]] = []

    vis.append(mk_markdown(
        "alo-cheat-sheet", "Dashboard Guide",
        CHEAT_SHEET_MARKDOWN,
        description="Quick reference guide for examining this dashboard."))

    vis.append(mk_metric(
        "alo-total-stress", "Total Stress Score",
        "stress.score", "sum",
        description="Sum of all stress scores in the selected time period."))

    for field, label in SECTIONS:
        if label == "Cost Indicator":
            vis.append(mk_pie_filters(
                "alo-pie-flagged-ratio", "Flagged vs Unflagged Requests", [
                    ("Flagged",   "stress.cost_indicator_count >= 1"),
                    ("Unflagged", "stress.cost_indicator_count < 1"),
                ],
                description="Proportion of requests with at least one cost indicator vs none."))
            continue
        size = 10 if field == "request.template" else 8
        slug = label.lower().replace(" ", "-")
        vis.append(mk_pie(
            f"alo-pie-{slug}",
            f"Stress by {label} (Selected Period)",
            field, size=size,
            description=PANEL_DESCRIPTIONS["pie"][label]))

    for field, label in SECTIONS:
        size = 10 if field == "request.template" else 5
        slug = label.lower().replace(" ", "-")
        vis.append(mk_ts(
            f"alo-ts-{slug}",
            f"Stress Over Time by {label}",
            field, size=size,
            description=PANEL_DESCRIPTIONS["ts"][label]))

    vis.append(mk_ts(
        "alo-ts-volume-template",
        "Request Volume Over Time by Template",
        "request.template",
        metric_field="___records___", metric_label="Requests",
        metric_op="count", size=10,
        description="Request count over time by template — shows ingestion/query rate trends."))

    vis.append(mk_datatable(
        "alo-table-top-templates", "Top 10 Templates by Stress Score",
        "request.template", "Template", [
            ("sum_stress",       "Sum Stress",              "stress.score",                "sum"),
            ("avg_stress",       "Avg Stress",              "stress.score",                "average"),
            ("avg_es_latency",   "Avg ES Latency (ms)",     "response.es_took_ms",         "average"),
            ("avg_gw_latency",   "Avg Gateway Latency (ms)","response.gateway_took_ms",    "average"),
            ("cost_indicators",  "Avg Cost Indicators",     "stress.cost_indicator_count",  "average"),
            ("requests",         "Requests",                None,                           "count"),
        ], size=10))

    vis.append(mk_datatable(
        "alo-table-top-indicators", "Top 10 Cost Indicators by Stress Score",
        "stress.cost_indicator_names", "Cost Indicator", [
            ("sum_stress",       "Sum Stress",              "stress.score",                "sum"),
            ("avg_stress",       "Avg Stress",              "stress.score",                "average"),
            ("avg_es_latency",   "Avg ES Latency (ms)",     "response.es_took_ms",         "average"),
            ("avg_gw_latency",   "Avg Gateway Latency (ms)","response.gateway_took_ms",    "average"),
            ("requests",         "Requests",                None,                           "count"),
        ], size=10))

    response_breakdowns = [
        ("stress.cost_indicator_names", "Cost Indicator"),
        ("request.operation",           "Operation"),
        ("request.template",            "Template"),
    ]
    for bd_field, bd_label in response_breakdowns:
        slug = bd_label.lower().replace(" ", "-")
        vis.append(mk_ts_response(
            f"alo-resp-es-{slug}",
            f"Avg ES Response Time by {bd_label}",
            bd_field, "response.es_took_ms", "Avg ES Latency (ms)",
            description=PANEL_DESCRIPTIONS["resp_es"][bd_label]))

    for bd_field, bd_label in response_breakdowns:
        slug = bd_label.lower().replace(" ", "-")
        vis.append(mk_ts_response(
            f"alo-resp-gw-{slug}",
            f"Avg Gateway Response Time by {bd_label}",
            bd_field, "response.gateway_took_ms", "Avg Gateway Latency (ms)",
            description=PANEL_DESCRIPTIONS["resp_gw"][bd_label]))

    vis.append(mk_datatable(
        "alo-sanity-recurring", "Top 10 Most Recurring Templates",
        "request.template", "Template", [
            ("requests", "Requests", None, "count"),
        ], size=10))

    vis.append(mk_datatable(
        "alo-sanity-cost-indicators", "Top 10 Templates with Most Cost Indicators",
        "request.template", "Template", [
            ("avg_ci",   "Avg Cost Indicators", "stress.cost_indicator_count", "average"),
            ("requests", "Requests",            None,                          "count"),
        ], size=10))

    return vis


def _build_ci_visualizations() -> list[tuple[str, dict]]:
    return [
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


DRILLDOWN_SEARCH_ID = "alo-template-drilldown"

_DRILLDOWN_COLUMNS = [
    "request.template", "request.path", "request.operation",
    "identity.applicative_provider", "request.body", "stress.score",
]


def _create_drilldown_search(cfg: StackConfig) -> None:
    attrs = {
        "title": "Sample Request Bodies",
        "description": "Sample request bodies for template drilldown",
        "columns": _DRILLDOWN_COLUMNS,
        "sort": [["@timestamp", "desc"]],
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
    ok = upsert(cfg, "search", DRILLDOWN_SEARCH_ID, attrs, refs)
    print(f"  {'OK' if ok else 'FAIL'}: Template Drilldown (Saved Search)")


def do_rebuild(cfg: StackConfig) -> bool:
    _create_data_view(cfg)
    _create_drilldown_search(cfg)

    main_vis = _build_main_visualizations()
    vis_ids = _upsert_visualizations(cfg, main_vis, all_lens=False)
    vis_ids.append(DRILLDOWN_SEARCH_ID)
    ok1 = build_dashboard(cfg, DASHBOARD_ID, "Applicative Load Observability",
                          "Stress analysis by application, target, operation, and template, with overall trend.",
                          vis_ids, layout_main)

    print()
    ci_vis = _build_ci_visualizations()
    ci_ids = _upsert_visualizations(cfg, ci_vis)
    ok2 = build_dashboard(cfg, CI_DASHBOARD_ID, "Cost Indicators & Query Patterns",
                          "Cost indicators, clause counts, and query pattern analysis.",
                          ci_ids, layout_cost_indicators)

    print()
    export_dashboard(cfg, DASHBOARD_ID, NDJSON_PATH)
    export_dashboard(cfg, CI_DASHBOARD_ID, CI_NDJSON_PATH)

    return ok1 and ok2
