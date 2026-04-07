"""
Grafana dashboard JSON builders for ALO.

Generates provisioning-ready dashboard JSON files equivalent to the Kibana
dashboards, using Grafana's Elasticsearch datasource query format.
"""

import json
import os

DATASOURCE = {"type": "elasticsearch", "uid": "${datasource}"}
SUMMARY_DATASOURCE = DATASOURCE
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROVISION_DIR = os.path.join(SCRIPT_DIR, "provisioning", "dashboards")

SECTIONS = [
    ("identity.applicative_provider", "Application"),
    ("request.target", "Target"),
    ("request.operation", "Operation"),
    ("stress.cost_indicator_names", "Cost Indicator"),
    ("request.template", "Template"),
]

_CHEAT_SHEET_PATH = os.path.join(SCRIPT_DIR, "cheat_sheet.md")
with open(_CHEAT_SHEET_PATH, encoding="utf-8") as _f:
    CHEAT_SHEET = _f.read()


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


def _es_target(query="", metrics=None, bucket_aggs=None, ref_id="A",
               datasource=None):
    var_filter = _build_var_query()
    full_query = f"{var_filter} AND {query}" if query else var_filter
    target = {
        "datasource": datasource or DATASOURCE,
        "query": full_query,
        "refId": ref_id,
        "metrics": metrics or [],
        "bucketAggs": bucket_aggs or [],
    }
    return target


def _metric(metric_type, field=None, metric_id="1", settings=None):
    if metric_type.startswith("percentile_"):
        pct = int(metric_type.split("_", 1)[1])
        return {"type": "percentiles", "field": field, "id": metric_id,
                "settings": {"percents": [pct]}}
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


def _date_histogram(agg_id="3", interval="auto"):
    return {
        "type": "date_histogram",
        "field": "@timestamp",
        "id": agg_id,
        "settings": {"interval": interval},
    }


PROMETHEUS_DS = {"type": "prometheus", "uid": "${datasource_prometheus}"}


# ---------------------------------------------------------------------------
# Panel factories
# ---------------------------------------------------------------------------

def mk_cpu_panel(gridpos):
    """ES process CPU panel (Prometheus) with drilldown link to Health dashboard."""
    return {
        "id": _next_id(),
        "title": "ES CPU Usage",
        "description": "Elasticsearch process CPU %. Requires prometheus profile.",
        "type": "timeseries",
        "datasource": PROMETHEUS_DS,
        "gridPos": gridpos,
        "targets": [{
            "datasource": PROMETHEUS_DS,
            "expr": 'elasticsearch_process_cpu_percent{instance=~"$instance"}',
            "legendFormat": "{{instance}}",
            "refId": "A",
        }],
        "options": {
            "legend": {"displayMode": "list", "placement": "right"},
            "tooltip": {"mode": "multi"},
        },
        "fieldConfig": {
            "defaults": {
                "custom": {"drawStyle": "line", "fillOpacity": 20},
                "unit": "percent",
                "noValue": "Enable prometheus profile",
                "links": [{
                    "title": "Open ES Health Dashboard",
                    "url": "/d/alo-health?orgId=1&${__url_time_range}",
                }],
            },
            "overrides": [],
        },
    }


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


_FIELD_TO_VAR = {
    "identity.applicative_provider": "application",
    "request.target": "target",
    "request.operation": "operation",
    "stress.cost_indicator_names": "cost_indicator",
    "request.template": "template",
    "identity.username": "username",
    "identity.client_host": "client_host",
}


def _add_filter_link(panel, field, dashboard_uid="alo-main"):
    """Add a data link that filters the dashboard by the clicked value."""
    var_name = _FIELD_TO_VAR.get(field)
    if var_name:
        panel["fieldConfig"]["defaults"]["links"] = [{
            "title": "Filter by ${__data.fields[0]}",
            "url": f"/d/{dashboard_uid}?${{__url_time_range}}"
                   f"&var-{var_name}=${{__data.fields[0]}}",
            "targetBlank": False,
        }]


def mk_pie(title, field, gridpos, size=8, dashboard_uid="alo-main"):
    target = _es_target(
        metrics=[_metric("sum", "stress.score")],
        bucket_aggs=[_terms_agg(field, size=size)],
    )
    panel = _base_panel(title, "piechart", gridpos, targets=[target], options={
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
        "pieType": "pie",
        "legend": {"displayMode": "list", "placement": "bottom"},
        "tooltip": {"mode": "multi"},
    })
    _add_filter_link(panel, field, dashboard_uid)
    return panel


def mk_timeseries(title, field, gridpos, metric_field="stress.score",
                  metric_op="avg", size=5, series_type="line",
                  fill_opacity=20, summary_fallback=False, unit=None):
    """Timeseries panel.

    When *summary_fallback* is True, a second query (refId B) reads the
    equivalent metric from the summary index so the chart stays populated
    after raw data expires.
    """
    bucket_aggs = []
    if field:
        bucket_aggs.append(_terms_agg(field, agg_id="2", size=size))
    bucket_aggs.append(_date_histogram(agg_id="3"))
    target = _es_target(
        metrics=[_metric(metric_op, metric_field)],
        bucket_aggs=bucket_aggs,
    )
    targets = [target]
    if summary_fallback:
        summary_bucket_aggs = []
        if field:
            summary_bucket_aggs.append(_terms_agg(field, agg_id="2",
                                                  size=size))
        summary_bucket_aggs.append(
            _date_histogram(agg_id="3", interval="1h"))
        targets.append(_es_target(
            metrics=[_metric("sum", "count")],
            bucket_aggs=summary_bucket_aggs,
            ref_id="B",
            datasource=SUMMARY_DATASOURCE,
        ))
    custom = {"drawStyle": series_type, "fillOpacity": fill_opacity}
    overrides = []
    if summary_fallback:
        overrides.append({
            "matcher": {"id": "byFrameRefID", "options": "B"},
            "properties": [
                {"id": "custom.lineStyle", "value": {"fill": "dash",
                                                     "dash": [10, 10]}},
                {"id": "custom.lineWidth", "value": 1},
            ],
        })
    defaults = {"custom": custom}
    if unit:
        defaults["unit"] = unit
    return _base_panel(title, "timeseries", gridpos, targets=targets,
                       options={
                           "legend": {"displayMode": "list", "placement": "right"},
                           "tooltip": {"mode": "multi"},
                       },
                       field_config={"defaults": defaults,
                                     "overrides": overrides})


def mk_timeseries_multi(title, metrics_spec, gridpos, series_type="line",
                        stacked=False, unit=None):
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
    defaults = {"custom": custom}
    if unit:
        defaults["unit"] = unit
    return _base_panel(title, "timeseries", gridpos, targets=targets,
                       options={
                           "legend": {"displayMode": "list", "placement": "right"},
                           "tooltip": {"mode": "multi"},
                       },
                       field_config={"defaults": defaults, "overrides": []})


def mk_bar(title, field, metric_field, metric_op, metric_label, gridpos,
           size=10, dashboard_uid="alo-main"):
    metrics = [_metric(metric_op, metric_field)] if metric_field else [
        _metric("count")]
    target = _es_target(
        metrics=metrics,
        bucket_aggs=[_terms_agg(field, size=size)],
    )
    panel = _base_panel(title, "barchart", gridpos, targets=[target], options={
        "orientation": "horizontal",
        "showValue": "always",
        "legend": {"displayMode": "hidden"},
        "tooltip": {"mode": "single"},
    })
    _add_filter_link(panel, field, dashboard_uid)
    return panel


def mk_stacked_bar(title, bucket_field, metrics_spec, gridpos, size=10):
    """Stacked horizontal bar chart with multiple metrics per bucket.

    metrics_spec: [(label, field, op), ...]
    """
    metrics = []
    overrides = []
    _GRAFANA_NAMES = {"sum": "Sum", "avg": "Average", "count": "Count", "max": "Max"}
    for i, (label, field, op) in enumerate(metrics_spec):
        metrics.append(_metric(op, field, metric_id=str(i + 1)))
        default = _GRAFANA_NAMES.get(op, op)
        if field:
            default = f"{default} {field}"
        overrides.append({
            "matcher": {"id": "byName", "options": default},
            "properties": [{"id": "displayName", "value": label}],
        })
    target = _es_target(
        metrics=metrics,
        bucket_aggs=[_terms_agg(bucket_field, agg_id="99", size=size,
                                order_by="1")],
    )
    return _base_panel(title, "barchart", gridpos, targets=[target],
                       options={
                           "orientation": "horizontal",
                           "showValue": "auto",
                           "stacking": "normal",
                           "legend": {"displayMode": "list", "placement": "right"},
                           "tooltip": {"mode": "multi"},
                       },
                       field_config={
                           "defaults": {},
                           "overrides": overrides,
                       })


def mk_table(title, bucket_field, bucket_label, metrics_spec, gridpos,
             size=10, dashboard_uid="alo-main"):
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
    panel = _base_panel(title, "table", gridpos, targets=[target],
                        options={
                            "showHeader": True,
                            "sortBy": [{"displayName": metrics_spec[0][0],
                                        "desc": True}],
                        },
                        field_config={"defaults": {}, "overrides": overrides})
    _add_filter_link(panel, bucket_field, dashboard_uid)
    return panel


# ---------------------------------------------------------------------------
# Dashboard assembly
# ---------------------------------------------------------------------------

_VARIABLES = [
    ("cluster", "Cluster", "cluster_name"),
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
        "allValue": "*",
        "multi": True,
        "sort": 1,
        "refresh": 2,
        "current": {"text": "All", "value": "$__all", "selected": True},
    }


def _build_var_query():
    """Build a Lucene filter string from the dashboard variables."""
    parts = []
    for name, _, field in _VARIABLES:
        parts.append(f'{field}:(${{{name}:lucene}})')
    return " AND ".join(parts)


def _wrap_dashboard(uid, title, description, panels):
    template_vars = [
        {
            "type": "datasource",
            "name": "datasource",
            "label": "Elasticsearch",
            "query": "elasticsearch",
            "current": {"text": "Elasticsearch (ALO)",
                        "value": "alo-elasticsearch"},
            "regex": "",
        },
        {
            "type": "datasource",
            "name": "datasource_prometheus",
            "label": "Prometheus",
            "query": "prometheus",
            "current": {"text": "Prometheus (ALO)",
                        "value": "alo-prometheus"},
            "regex": "",
            "hide": 2,
        },
    ]
    template_vars += [_make_query_var(n, l, f) for n, l, f in _VARIABLES]
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
        "time": {"from": "now-15m", "to": "now"},
        "panels": panels,
        "templating": {"list": template_vars},
        "annotations": {"list": []},
        "editable": True,
    }


def export_dashboards():
    from _dashboard_builders import (
        build_cost_indicators_dashboard,
        build_main_dashboard,
        build_usage_dashboard,
    )

    os.makedirs(PROVISION_DIR, exist_ok=True)

    for builder, filename in [
        (build_main_dashboard, "alo-main.json"),
        (build_cost_indicators_dashboard, "alo-cost-indicators.json"),
        (build_usage_dashboard, "alo-usage.json"),
    ]:
        dashboard = builder()
        path = os.path.join(PROVISION_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dashboard, f, indent=2)
        print(f"  Exported: {path}")

    return PROVISION_DIR


if __name__ == "__main__":
    export_dashboards()
