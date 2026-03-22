"""
Grafana dashboard JSON builders for ALO.

Generates provisioning-ready dashboard JSON files equivalent to the Kibana
dashboards, using Grafana's Elasticsearch datasource query format.
"""

import json
import os

DATASOURCE = {"type": "elasticsearch", "uid": "alo-elasticsearch"}
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROVISION_DIR = os.path.join(SCRIPT_DIR, "provisioning", "dashboards")

SECTIONS = [
    ("identity.applicative_provider", "Application"),
    ("request.target", "Target"),
    ("request.operation", "Operation"),
    ("stress.cost_indicator_names", "Cost Indicator"),
    ("request.template", "Template"),
]

CHEAT_SHEET = """\
## Dashboard Cheat Sheet

**How to examine this dashboard:**

1. **Start with the top row** — pie charts show which application, target, \
operation, or template contributes the most stress; the overall trend shows \
whether stress is rising or falling.
2. **Check the time series** — look for spikes or trends in stress over time. \
Correlate with deployments or traffic changes.
3. **Review the Top 10 Templates table** — focus on templates with the highest \
sum stress and cost indicator counts.
4. **Examine response times** — high ES or gateway latency alongside high stress \
may indicate query optimization opportunities.
5. **Sanity check tables** — verify if the most recurring templates are also the \
most stressful; templates with many cost indicators need attention.

**What to focus on:**
- **High stress slices** in pie charts — these are your optimization targets
- **Upward trends** in time series — indicates growing load or degrading patterns
- **Templates with many cost indicators** — likely candidates for query optimization
- **Latency spikes** correlating with specific operations or templates
"""


# ---------------------------------------------------------------------------
# Panel builder helpers
# ---------------------------------------------------------------------------

def _next_id():
    _next_id.counter += 1
    return _next_id.counter


_next_id.counter = 0


def _reset_ids():
    _next_id.counter = 0


def _base_panel(title, panel_type, gridpos, targets=None, options=None,
                field_config=None, transformations=None):
    panel = {
        "id": _next_id(),
        "title": title,
        "type": panel_type,
        "datasource": DATASOURCE,
        "gridPos": gridpos,
    }
    if targets:
        panel["targets"] = targets
    if options:
        panel["options"] = options
    if field_config:
        panel["fieldConfig"] = field_config
    else:
        panel["fieldConfig"] = {
            "defaults": {}, "overrides": [],
        }
    if transformations:
        panel["transformations"] = transformations
    return panel


def _es_target(query="", metrics=None, bucket_aggs=None, ref_id="A"):
    var_filter = _build_var_query()
    full_query = f"{var_filter} AND {query}" if query else var_filter
    target = {
        "datasource": DATASOURCE,
        "query": full_query,
        "refId": ref_id,
        "metrics": metrics or [],
        "bucketAggs": bucket_aggs or [],
    }
    return target


def _metric(metric_type, field=None, metric_id="1", settings=None):
    m = {"type": metric_type, "id": metric_id}
    if field:
        m["field"] = field
    if settings:
        m["settings"] = settings
    return m


def _terms_agg(field, agg_id="2", size=8, order_by="1"):
    return {
        "type": "terms",
        "field": field,
        "id": agg_id,
        "settings": {
            "size": str(size),
            "order": "desc",
            "orderBy": order_by,
            "min_doc_count": "1",
        },
    }


def _date_histogram(agg_id="3"):
    return {
        "type": "date_histogram",
        "field": "@timestamp",
        "id": agg_id,
        "settings": {"interval": "auto"},
    }


# ---------------------------------------------------------------------------
# Panel factories
# ---------------------------------------------------------------------------

def mk_text(title, content, gridpos):
    panel = _base_panel(title, "text", gridpos)
    panel["options"] = {
        "mode": "markdown",
        "content": content,
    }
    panel.pop("datasource", None)
    panel.pop("targets", None)
    return panel


_STAT_CALC = {"sum": "sum", "count": "sum", "avg": "mean", "max": "max"}


def mk_stat(title, field, operation, gridpos, query=""):
    target = _es_target(
        query=query,
        metrics=[_metric(operation, field)],
        bucket_aggs=[_date_histogram(agg_id="2")],
    )
    calc = _STAT_CALC.get(operation, "lastNotNull")
    return _base_panel(title, "stat", gridpos, targets=[target], options={
        "reduceOptions": {"calcs": [calc], "fields": "", "values": False},
        "colorMode": "value",
        "graphMode": "none",
        "textMode": "auto",
    })


def mk_pie(title, field, gridpos, size=8):
    target = _es_target(
        metrics=[_metric("sum", "stress.score")],
        bucket_aggs=[_terms_agg(field, size=size)],
    )
    return _base_panel(title, "piechart", gridpos, targets=[target], options={
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
        "pieType": "donut",
        "legend": {"displayMode": "list", "placement": "bottom"},
        "tooltip": {"mode": "multi"},
    })


def mk_pie_filters(title, filters, gridpos):
    """Pie chart with Lucene query-filtered slices (one target per slice)."""
    targets = []
    for i, (label, query) in enumerate(filters):
        target = _es_target(
            query=query,
            metrics=[_metric("sum", "stress.score")],
            bucket_aggs=[_date_histogram(agg_id="2")],
            ref_id=chr(65 + i),
        )
        target["alias"] = label
        targets.append(target)
    return _base_panel(title, "piechart", gridpos, targets=targets, options={
        "reduceOptions": {"calcs": ["sum"], "fields": "", "values": False},
        "pieType": "donut",
        "legend": {"displayMode": "list", "placement": "bottom"},
        "tooltip": {"mode": "multi"},
    })


def mk_timeseries(title, field, gridpos, metric_field="stress.score",
                  metric_op="avg", size=5, series_type="line",
                  fill_opacity=20):
    target = _es_target(
        metrics=[_metric(metric_op, metric_field)],
        bucket_aggs=[
            _terms_agg(field, agg_id="2", size=size),
            _date_histogram(agg_id="3"),
        ],
    )
    custom = {"drawStyle": series_type, "fillOpacity": fill_opacity}
    return _base_panel(title, "timeseries", gridpos, targets=[target],
                       options={
                           "legend": {"displayMode": "list", "placement": "right"},
                           "tooltip": {"mode": "multi"},
                       },
                       field_config={"defaults": {"custom": custom}, "overrides": []})


def mk_timeseries_response(title, breakdown_field, latency_field,
                           latency_label, gridpos, size=5):
    latency_target = _es_target(
        metrics=[_metric("avg", latency_field, metric_id="1")],
        bucket_aggs=[
            _terms_agg(breakdown_field, agg_id="2", size=size),
            _date_histogram(agg_id="3"),
        ],
        ref_id="A",
    )
    count_target = _es_target(
        metrics=[_metric("count", metric_id="1")],
        bucket_aggs=[_date_histogram(agg_id="2")],
        ref_id="B",
    )
    return _base_panel(title, "timeseries", gridpos,
                       targets=[latency_target, count_target],
                       options={
                           "legend": {"displayMode": "list", "placement": "right"},
                           "tooltip": {"mode": "multi"},
                       },
                       field_config={
                           "defaults": {"custom": {"drawStyle": "line",
                                                   "fillOpacity": 0}},
                           "overrides": [{
                               "matcher": {"id": "byFrameRefID", "options": "B"},
                               "properties": [
                                   {"id": "custom.axisPlacement", "value": "right"},
                                   {"id": "custom.drawStyle", "value": "bars"},
                                   {"id": "custom.fillOpacity", "value": 20},
                                   {"id": "displayName", "value": "Requests"},
                               ],
                           }],
                       })


def mk_timeseries_multi(title, metrics_spec, gridpos, series_type="line",
                        stacked=False):
    targets = []
    for i, (label, field, op, query) in enumerate(metrics_spec):
        ref = chr(65 + i)
        target = _es_target(
            query=query,
            metrics=[_metric(op, field, metric_id="1")],
            bucket_aggs=[_date_histogram(agg_id="2")],
            ref_id=ref,
        )
        target["alias"] = label
        targets.append(target)
    fill = 20 if series_type == "bars" else (50 if stacked else 0)
    custom = {"drawStyle": series_type, "fillOpacity": fill}
    if stacked:
        custom["stacking"] = {"mode": "normal"}
        custom["fillOpacity"] = 50
    return _base_panel(title, "timeseries", gridpos, targets=targets,
                       options={
                           "legend": {"displayMode": "list", "placement": "right"},
                           "tooltip": {"mode": "multi"},
                       },
                       field_config={"defaults": {"custom": custom}, "overrides": []})


def mk_bar(title, field, metric_field, metric_op, metric_label, gridpos,
           size=10):
    metrics = [_metric(metric_op, metric_field)] if metric_field else [
        _metric("count")]
    target = _es_target(
        metrics=metrics,
        bucket_aggs=[_terms_agg(field, size=size)],
    )
    return _base_panel(title, "barchart", gridpos, targets=[target], options={
        "orientation": "horizontal",
        "showValue": "always",
        "legend": {"displayMode": "hidden"},
        "tooltip": {"mode": "single"},
    })


def mk_table(title, bucket_field, bucket_label, metrics_spec, gridpos,
             size=10):
    metrics = []
    overrides = []
    for i, (label, field, op) in enumerate(metrics_spec):
        metrics.append(_metric(op, field, metric_id=str(i + 1)))
    target = _es_target(
        metrics=metrics,
        bucket_aggs=[_terms_agg(bucket_field, agg_id="99", size=size,
                                order_by="1")],
    )
    # Build field overrides to rename columns (settings.alias causes 400
    # on Grafana 11's ES plugin).
    _GRAFANA_DEFAULT_NAMES = {"sum": "Sum", "avg": "Average", "count": "Count"}
    for i, (label, field, op) in enumerate(metrics_spec):
        default = _GRAFANA_DEFAULT_NAMES.get(op, op)
        if field:
            default = f"{default} {field}"
        overrides.append({
            "matcher": {"id": "byName", "options": default},
            "properties": [{"id": "displayName", "value": label}],
        })
    return _base_panel(title, "table", gridpos, targets=[target],
                       options={
                           "showHeader": True,
                           "sortBy": [{"displayName": metrics_spec[0][0],
                                       "desc": True}],
                       },
                       field_config={"defaults": {}, "overrides": overrides})


# ---------------------------------------------------------------------------
# Dashboard assembly
# ---------------------------------------------------------------------------

def build_main_dashboard():
    _reset_ids()
    panels = []
    y = 0

    # Row 0: Cheat sheet + Total Stress Score
    panels.append(mk_text("Dashboard Guide", CHEAT_SHEET,
                          {"x": 0, "y": y, "w": 18, "h": 8}))
    panels.append(mk_stat("Total Stress Score", "stress.score", "sum",
                          {"x": 18, "y": y, "w": 6, "h": 8}))
    y += 8

    # Row 1: 5 pie charts — 3 on first row, 2 on second row
    pie_h = 10
    # First row: Application, Target, Operation
    for i, (field, label) in enumerate(SECTIONS[:3]):
        size = 8
        panels.append(mk_pie(f"Stress by {label} (Selected Period)", field,
                             {"x": i * 8, "y": y, "w": 8, "h": pie_h},
                             size=size))
    y += pie_h
    # Second row: Flagged/Unflagged + Template
    panels.append(mk_pie_filters(
        "Flagged vs Unflagged Requests", [
            ("Flagged", "stress.cost_indicator_count:[1 TO *]"),
            ("Unflagged", "NOT stress.cost_indicator_count:[1 TO *]"),
        ], {"x": 0, "y": y, "w": 12, "h": pie_h}))
    panels.append(mk_pie("Stress by Template (Selected Period)",
                         "request.template",
                         {"x": 12, "y": y, "w": 12, "h": pie_h}, size=10))
    y += pie_h

    # Rows 2-6: Stress over time per dimension
    for field, label in SECTIONS:
        size = 10 if field == "request.template" else 5
        panels.append(mk_timeseries(
            f"Stress Over Time by {label}", field,
            {"x": 0, "y": y, "w": 24, "h": 8},
            size=size, series_type="line", fill_opacity=20))
        y += 8

    # Row 7: Request volume over time by template (count, no scoring)
    panels.append(mk_timeseries(
        "Request Volume Over Time by Template", "request.template",
        {"x": 0, "y": y, "w": 24, "h": 8},
        metric_field=None, metric_op="count", size=10,
        series_type="line", fill_opacity=20))
    y += 8

    # Row 8: Top 10 Templates table
    panels.append(mk_table(
        "Top 10 Templates by Stress Score", "request.template", "Template", [
            ("Sum Stress", "stress.score", "sum"),
            ("Avg Stress", "stress.score", "avg"),
            ("Avg ES Latency (ms)", "response.es_took_ms", "avg"),
            ("Avg Gateway Latency (ms)", "response.gateway_took_ms", "avg"),
            ("Avg Cost Indicators", "stress.cost_indicator_count", "avg"),
            ("Requests", None, "count"),
        ], {"x": 0, "y": y, "w": 24, "h": 8}, size=10))
    y += 8

    # Row 9: Top 10 Cost Indicators table
    panels.append(mk_table(
        "Top 10 Cost Indicators by Stress Score",
        "stress.cost_indicator_names", "Cost Indicator", [
            ("Sum Stress", "stress.score", "sum"),
            ("Avg Stress", "stress.score", "avg"),
            ("Avg ES Latency (ms)", "response.es_took_ms", "avg"),
            ("Avg Gateway Latency (ms)", "response.gateway_took_ms", "avg"),
            ("Requests", None, "count"),
        ], {"x": 0, "y": y, "w": 24, "h": 8}, size=10))
    y += 8

    # Rows 9-10: Response time panels (3 per row)
    response_breakdowns = [
        ("stress.cost_indicator_names", "Cost Indicator"),
        ("request.operation", "Operation"),
        ("request.template", "Template"),
    ]
    for latency_field, latency_label, row_label in [
        ("response.es_took_ms", "Avg ES Latency (ms)", "ES"),
        ("response.gateway_took_ms", "Avg Gateway Latency (ms)", "Gateway"),
    ]:
        for j, (bd_field, bd_label) in enumerate(response_breakdowns):
            panels.append(mk_timeseries_response(
                f"Avg {row_label} Response Time by {bd_label}",
                bd_field, latency_field, latency_label,
                {"x": j * 8, "y": y, "w": 8, "h": 8}))
        y += 8

    # Row 10: Sanity check tables
    panels.append(mk_table(
        "Top 10 Most Recurring Templates", "request.template", "Template", [
            ("Requests", None, "count"),
        ], {"x": 0, "y": y, "w": 12, "h": 8}, size=10))
    panels.append(mk_table(
        "Top 10 Templates with Most Cost Indicators",
        "request.template", "Template", [
            ("Avg Cost Indicators", "stress.cost_indicator_count", "avg"),
            ("Requests", None, "count"),
        ], {"x": 12, "y": y, "w": 12, "h": 8}, size=10))

    return _wrap_dashboard(
        uid="alo-main",
        title="ALO — Stress Analysis",
        description="Stress analysis by application, target, operation, and "
                    "template, with overall trend.",
        panels=panels,
    )


def build_cost_indicators_dashboard():
    _reset_ids()
    panels = []
    y = 0

    # Row 0: KPIs
    kpis = [
        ("Flagged Requests", "stress.cost_indicator_count", "count",
         "stress.cost_indicator_count:[1 TO *]"),
        ("Avg Indicator Count", "stress.cost_indicator_count", "avg", ""),
        ("Avg Stress Multiplier", "stress.multiplier", "avg", ""),
        ("Max Stress Multiplier", "stress.multiplier", "max", ""),
    ]
    for i, (title, field, op, query) in enumerate(kpis):
        panels.append(mk_stat(title, field, op,
                              {"x": i * 6, "y": y, "w": 6, "h": 5},
                              query=query))
    y += 5

    # Row 1: Indicator overview
    panels.append(mk_bar(
        "Cost Indicator Types - Frequency",
        "stress.cost_indicator_names", None, "count", "Count",
        {"x": 0, "y": y, "w": 10, "h": 10}))
    panels.append(mk_timeseries_multi(
        "Flagged vs Total Requests Over Time", [
            ("Flagged Requests", None, "count",
             "stress.cost_indicator_count:[1 TO *]"),
            ("Total Requests", None, "count", ""),
        ], {"x": 10, "y": y, "w": 14, "h": 10}, series_type="line"))
    y += 10

    # Row 2: Clause counts
    panels.append(mk_timeseries_multi(
        "Clause Count Trends", [
            ("Avg terms_values", "clause_counts.terms_values", "avg", ""),
            ("Avg agg", "clause_counts.agg", "avg", ""),
            ("Avg script", "clause_counts.script", "avg", ""),
            ("Avg wildcard", "clause_counts.wildcard", "avg", ""),
        ], {"x": 0, "y": y, "w": 14, "h": 10}, series_type="line"))
    panels.append(mk_timeseries_multi(
        "Bool Clause Breakdown Over Time", [
            ("Avg must", "clause_counts.bool_must", "avg", ""),
            ("Avg should", "clause_counts.bool_should", "avg", ""),
            ("Avg filter", "clause_counts.bool_filter", "avg", ""),
            ("Avg must_not", "clause_counts.bool_must_not", "avg", ""),
        ], {"x": 14, "y": y, "w": 10, "h": 10},
        series_type="line", stacked=True))
    y += 10

    # Row 3: Table
    panels.append(mk_table(
        "Top Templates by Cost Indicator Count",
        "request.template", "Template", [
            ("Avg Indicators", "stress.cost_indicator_count", "avg"),
            ("Requests", None, "count"),
            ("Avg Multiplier", "stress.multiplier", "avg"),
            ("Avg Stress", "stress.score", "avg"),
        ], {"x": 0, "y": y, "w": 24, "h": 8}))
    y += 8

    # Row 4: By dimension
    panels.append(mk_bar(
        "Stress Multiplier by Application",
        "identity.applicative_provider", "stress.multiplier", "avg",
        "Avg Stress Multiplier", {"x": 0, "y": y, "w": 12, "h": 10}, size=8))
    panels.append(mk_bar(
        "Cost Indicator Count by Target Index",
        "request.target", "stress.cost_indicator_count", "avg",
        "Avg Indicator Count", {"x": 12, "y": y, "w": 12, "h": 10}, size=8))

    return _wrap_dashboard(
        uid="alo-cost-indicators",
        title="Cost Indicators & Query Patterns",
        description="Cost indicators, clause counts, and query pattern analysis.",
        panels=panels,
    )


_VARIABLES = [
    ("application", "Application", "identity.applicative_provider"),
    ("target", "Target", "request.target"),
    ("operation", "Operation", "request.operation"),
    ("username", "Username", "identity.username"),
    ("cost_indicator", "Cost Indicator", "stress.cost_indicator_names"),
    ("client_host", "Client Host", "identity.client_host"),
    ("template", "Template", "request.template"),
]


def _make_query_var(name, label, field):
    return {
        "type": "query",
        "name": name,
        "label": label,
        "datasource": DATASOURCE,
        "query": json.dumps({"find": "terms", "field": field}),
        "includeAll": True,
        "allValue": "",
        "multi": True,
        "sort": 1,
        "refresh": 2,
    }


def _build_var_query():
    """Build a Lucene filter string from the dashboard variables."""
    parts = []
    for name, _, field in _VARIABLES:
        parts.append(f'{field}:${{{name}}}')
    return " AND ".join(parts)


def _wrap_dashboard(uid, title, description, panels):
    template_vars = [_make_query_var(n, l, f) for n, l, f in _VARIABLES]
    template_vars.append({
        "type": "adhoc",
        "name": "Filters",
        "datasource": DATASOURCE,
    })
    return {
        "uid": uid,
        "title": title,
        "description": description,
        "tags": ["alo", "observability"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-24h", "to": "now"},
        "panels": panels,
        "templating": {"list": template_vars},
        "annotations": {"list": []},
        "editable": True,
    }


def export_dashboards():
    os.makedirs(PROVISION_DIR, exist_ok=True)

    main = build_main_dashboard()
    main_path = os.path.join(PROVISION_DIR, "alo-main.json")
    with open(main_path, "w", encoding="utf-8") as f:
        json.dump(main, f, indent=2)
    print(f"  Exported: {main_path}")

    ci = build_cost_indicators_dashboard()
    ci_path = os.path.join(PROVISION_DIR, "alo-cost-indicators.json")
    with open(ci_path, "w", encoding="utf-8") as f:
        json.dump(ci, f, indent=2)
    print(f"  Exported: {ci_path}")

    return main_path, ci_path


if __name__ == "__main__":
    export_dashboards()
