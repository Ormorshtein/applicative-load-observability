"""
Grafana dashboard JSON builders for ALO (ClickHouse datasource).

Public helpers (``mk_stat``, ``mk_pie``, ``mk_timeseries`` ΓÇª) keep the same
signatures as the prior Elasticsearch implementation. Each builder emits a
panel whose target carries a raw ClickHouse SQL query against the
``alo.alo_raw`` table.

The ``grafana-clickhouse-datasource`` plugin recognises ``$__timeFilter``
and ``$__timeInterval`` macros and ``${var:singlequote}`` for multi-select
variable expansion.
"""

import json
import os
from collections.abc import Iterable

DATASOURCE = {"type": "grafana-clickhouse-datasource", "uid": "${datasource}"}
PROMETHEUS_DS = {"type": "prometheus", "uid": "${datasource_prometheus}"}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROVISION_DIR = os.path.join(SCRIPT_DIR, "provisioning", "dashboards")

# Single ClickHouse table backs both raw and summary panels; the summary
# `*State` table is queried explicitly where needed.
TABLE_RAW     = "alo.alo_raw"
TABLE_SUMMARY = "alo.alo_summary"
TIME_COL      = "timestamp"

SECTIONS = [
    ("identity_applicative_provider", "Application"),
    ("request_target",                "Target"),
    ("request_operation",             "Operation"),
    ("stress_cost_indicator_names",   "Cost Indicator"),
    ("request_template",              "Template"),
]

_CHEAT_SHEET_PATH = os.path.join(SCRIPT_DIR, "cheat_sheet.md")
with open(_CHEAT_SHEET_PATH, encoding="utf-8") as _f:
    CHEAT_SHEET = _f.read()


PANEL_DESCRIPTIONS = {
    "pie": {
        "Application": "Stress distribution across applicative providers. "
                       "Click a slice to filter the dashboard.",
        "Target": "Stress distribution across target indices. "
                  "Click a slice to filter the dashboard.",
        "Operation": "Stress distribution across operation types "
                     "(search, index, bulk, etc.). Click a slice to filter.",
        "Cost Indicator": "Stress distribution across cost indicator types. "
                          "'unflagged' = requests with no cost indicators.",
        "Template": "Stress distribution across request templates. "
                    "Click a slice to filter the dashboard.",
    },
    "ts": {
        "Application": "Average stress score over time, broken down by applicative provider.",
        "Target": "Average stress score over time, broken down by target index.",
        "Operation": "Average stress score over time, broken down by operation type.",
        "Cost Indicator": "Average stress score over time, broken down by cost indicator.",
        "Template": "Average stress score over time, broken down by request template.",
    },
}


# ΓöÇΓöÇ Dashboard variables ΓåÆ CH columns ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

_VARIABLES = [
    ("cluster",        "Cluster",        "cluster_name"),
    ("application",    "Application",    "identity_applicative_provider"),
    ("target",         "Target",         "request_target"),
    ("operation",      "Operation",      "request_operation"),
    ("username",       "Username",       "identity_username"),
    ("cost_indicator", "Cost Indicator", "stress_cost_indicator_names"),
    ("client_host",    "Client Host",    "identity_client_host"),
    ("template",       "Template",       "request_template"),
]

_FIELD_TO_VAR = {field: name for name, _, field in _VARIABLES}


def _wildcard_predicate(var: str, column: str) -> str:
    """Build a SQL clause that honours Grafana's multi-select ``All`` macro.

    When the variable resolves to the literal ``*`` (i.e. "All"), the
    clause becomes ``TRUE``. Otherwise the value list is interpolated via
    ``${var:singlequote}`` which Grafana expands to a comma-separated list
    of quoted strings.

    The Array column ``stress_cost_indicator_names`` is handled with
    ``hasAny`` because the values live inside the array.
    """
    macro = f"${{{var}:singlequote}}"
    macro_csv = f"${{{var}:csv}}"
    if column == "stress_cost_indicator_names":
        return f"(('{macro_csv}' = '*') OR hasAny({column}, [{macro}]))"
    return f"(('{macro_csv}' = '*') OR {column} IN ({macro}))"


def _build_where(extra: str = "", time_col: str = TIME_COL) -> str:
    """Build the universal WHERE clause for ``alo_raw`` queries."""
    parts = [f"$__timeFilter({time_col})"]
    for var, _, column in _VARIABLES:
        parts.append(_wildcard_predicate(var, column))
    if extra:
        parts.append(extra)
    return " AND ".join(parts)


def _build_where_summary(extra: str = "") -> str:
    """WHERE clause for the summary table (time column is ``time_bucket``)."""
    return _build_where(extra=extra, time_col="time_bucket")


# ΓöÇΓöÇ Aggregate-function rendering ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

def _agg_sql(op: str, column: str | None) -> str:
    """Render a single aggregation in SQL.

    ``op`` is the legacy ES metric name carried over from the previous
    implementation:

    * ``count`` ΓåÆ ``count()``
    * ``sum``/``avg``/``max``/``min`` ΓåÆ ``<op>(<column>)``
    * ``percentile_<N>`` ΓåÆ ``quantile(0.<N>)(<column>)``
    """
    if op == "count":
        return "count()"
    if op.startswith("percentile_"):
        pct = int(op.split("_", 1)[1])
        return f"quantile({pct / 100})({column})"
    return f"{op}({column})"


def _alias_for(op: str, column: str | None, label: str | None = None) -> str:
    if label:
        return label
    if op == "count":
        return "count"
    if op.startswith("percentile_"):
        pct = op.split("_", 1)[1]
        return f"p{pct}_{column or 'value'}"
    return f"{op}_{column or 'value'}"


# ΓöÇΓöÇ Panel builder helpers ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

def _next_id():
    _next_id.counter += 1
    return _next_id.counter


_next_id.counter = 0


def _reset_ids():
    _next_id.counter = 0


def _base_panel(title, panel_type, gridpos, targets=None, options=None,
                field_config=None, transformations=None, description=None):
    panel = {
        "id": _next_id(),
        "title": title,
        "type": panel_type,
        "datasource": DATASOURCE,
        "gridPos": gridpos,
    }
    if description:
        panel["description"] = description
    if targets:
        panel["targets"] = targets
    if options:
        panel["options"] = options
    panel["fieldConfig"] = field_config or {"defaults": {}, "overrides": []}
    if transformations:
        panel["transformations"] = transformations
    return panel


def _ch_target(sql: str, ref_id: str = "A", datasource: dict | None = None,
               *, format_as: str = "time_series",
               alias: str | None = None) -> dict:
    target = {
        "datasource": datasource or DATASOURCE,
        "refId": ref_id,
        "editorType": "sql",
        "queryType": "table" if format_as == "table" else "timeseries",
        # `format` is the legacy numeric field the plugin still honours.
        # 0 = table, 1 = time-series, 2 = logs.
        "format": 1 if format_as == "time_series" else 0,
        "rawSql": sql,
        "meta": {"builderOptions": {}},
    }
    if alias:
        target["alias"] = alias
    return target


# ΓöÇΓöÇ Panel factories ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

def mk_text(title, content, gridpos, description=None):
    panel = _base_panel(title, "text", gridpos, description=description)
    panel["options"] = {"mode": "markdown", "content": content}
    panel.pop("datasource", None)
    panel.pop("targets", None)
    return panel


def mk_cpu_panel(gridpos):
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


_STAT_CALC = {"sum": "sum", "count": "sum", "avg": "mean", "max": "max"}


def mk_stat(title, field, operation, gridpos, query="", description=None):
    """Single-number reduction across the visible time range."""
    sql = (
        f"SELECT {TIME_COL} AS t, {_agg_sql(operation, field)} AS value "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where(extra=query)} "
        f"GROUP BY t ORDER BY t"
    )
    calc = _STAT_CALC.get(operation, "lastNotNull")
    return _base_panel(title, "stat", gridpos,
                       targets=[_ch_target(sql)],
                       options={
                           "reduceOptions": {"calcs": [calc],
                                             "fields": "/^value$/",
                                             "values": False},
                           "colorMode": "value",
                           "graphMode": "none",
                           "textMode": "auto",
                       },
                       description=description)


def _add_filter_link(panel, field, dashboard_uid="alo-main"):
    var_name = _FIELD_TO_VAR.get(field)
    if not var_name:
        return
    panel["fieldConfig"]["defaults"]["links"] = [{
        "title": "Filter by ${__data.fields[0]}",
        "url": f"/d/{dashboard_uid}?${{__url_time_range}}"
               f"&var-{var_name}=${{__data.fields[0]}}",
        "targetBlank": False,
    }]


def _bucket_expression(field: str) -> str:
    """SQL expression that produces one row per dimension value.

    Array columns are unnested via ``arrayJoin`` so the ``stress score by
    cost indicator`` slice splits multi-flag rows into one row per flag.
    """
    if field == "stress_cost_indicator_names":
        return "arrayJoin(stress_cost_indicator_names)"
    return field


def mk_pie(title, field, gridpos, size=8, dashboard_uid="alo-main",
           description=None):
    bucket = _bucket_expression(field)
    sql = (
        f"SELECT {bucket} AS label, sum(stress_score) AS value "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where()} "
        f"GROUP BY label ORDER BY value DESC LIMIT {size}"
    )
    panel = _base_panel(title, "piechart", gridpos,
                       targets=[_ch_target(sql, format_as="table")],
                       options={
                           "reduceOptions": {"calcs": ["lastNotNull"],
                                             "fields": "", "values": True},
                           "pieType": "pie",
                           "legend": {"displayMode": "list",
                                      "placement": "bottom"},
                           "tooltip": {"mode": "multi"},
                       },
                       description=description)
    _add_filter_link(panel, field, dashboard_uid)
    return panel


def mk_timeseries(title, field, gridpos, metric_field="stress_score",
                  metric_op="avg", size=5, series_type="line",
                  fill_opacity=20, summary_fallback=False, unit=None,
                  description=None):
    """Time-series panel.

    When *field* is set, one series per top-N value of that column. When
    *summary_fallback* is True, a second target reads the equivalent
    aggregate from ``alo_summary`` (dashed line) so the chart stays
    populated after raw TTL expiry.
    """
    targets = [_ch_target(_timeseries_sql(field, metric_field, metric_op, size),
                          ref_id="A")]
    overrides: list[dict] = []
    if summary_fallback:
        targets.append(_ch_target(
            _summary_timeseries_sql(field, metric_field, metric_op, size),
            ref_id="B"))
        overrides.append({
            "matcher": {"id": "byFrameRefID", "options": "B"},
            "properties": [
                {"id": "custom.lineStyle",
                 "value": {"fill": "dash", "dash": [10, 10]}},
                {"id": "custom.lineWidth", "value": 1},
            ],
        })

    custom = {"drawStyle": series_type, "fillOpacity": fill_opacity}
    defaults: dict = {"custom": custom}
    if unit:
        defaults["unit"] = unit
    return _base_panel(title, "timeseries", gridpos, targets=targets,
                       options={
                           "legend": {"displayMode": "list",
                                      "placement": "right"},
                           "tooltip": {"mode": "multi"},
                       },
                       field_config={"defaults": defaults,
                                     "overrides": overrides},
                       description=description)


def _timeseries_sql(field: str | None, metric_field: str | None,
                    metric_op: str, size: int) -> str:
    metric_sql = _agg_sql(metric_op, metric_field)
    if field is None:
        return (
            f"SELECT $__timeInterval({TIME_COL}) AS t, "
            f"{metric_sql} AS value "
            f"FROM {TABLE_RAW} "
            f"WHERE {_build_where()} "
            f"GROUP BY t ORDER BY t"
        )
    bucket = _bucket_expression(field)
    return (
        f"SELECT $__timeInterval({TIME_COL}) AS t, "
        f"{bucket} AS series, "
        f"{metric_sql} AS value "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where()} "
        f"  AND {bucket} IN ("
        f"    SELECT {bucket} FROM {TABLE_RAW} "
        f"    WHERE {_build_where()} "
        f"    GROUP BY {bucket} ORDER BY count() DESC LIMIT {size}"
        f"  ) "
        f"GROUP BY t, series ORDER BY t"
    )


_SUMMARY_AGG_OVERRIDES = {
    ("avg", "stress_score"):                ("avgMerge",      "avg_score_state"),
    ("avg", "stress_base"):                 ("avgMerge",      "avg_base_state"),
    ("avg", "stress_multiplier"):           ("avgMerge",      "avg_multiplier_state"),
    ("avg", "stress_cost_indicator_count"): ("avgMerge",      "avg_cost_indicator_count_state"),
    ("avg", "response_es_took_ms"):         ("avgMerge",      "avg_es_took_ms_state"),
    ("avg", "response_gateway_took_ms"):    ("avgMerge",      "avg_gateway_took_ms_state"),
    ("avg", "response_hits"):               ("avgMerge",      "avg_hits_state"),
    ("avg", "response_shards_total"):       ("avgMerge",      "avg_shards_total_state"),
    ("avg", "response_docs_affected"):      ("avgMerge",      "avg_docs_affected_state"),
    ("avg", "request_size_bytes"):          ("avgMerge",      "avg_request_size_bytes_state"),
    ("sum", "stress_score"):                ("sumMerge",      "sum_score_state"),
    ("count", None):                        ("countMerge",    "count_state"),
}


def _summary_timeseries_sql(field: str | None, metric_field: str | None,
                            metric_op: str, size: int) -> str:
    """Equivalent of `_timeseries_sql` but against the summary table."""
    override = _SUMMARY_AGG_OVERRIDES.get((metric_op, metric_field))
    if override:
        agg_fn, state_col = override
        metric_sql = f"{agg_fn}({state_col})"
    else:
        # Fallback: percentiles, max, etc. ΓÇö emit raw aggregate; will be
        # NULL after TTL but no worse than the raw fallback.
        metric_sql = _agg_sql(metric_op, metric_field)

    if field is None:
        return (
            f"SELECT toStartOfHour(time_bucket) AS t, "
            f"{metric_sql} AS value "
            f"FROM {TABLE_SUMMARY} "
            f"WHERE {_build_where_summary()} "
            f"GROUP BY t ORDER BY t"
        )
    bucket = _bucket_expression(field)
    return (
        f"SELECT toStartOfHour(time_bucket) AS t, "
        f"{bucket} AS series, "
        f"{metric_sql} AS value "
        f"FROM {TABLE_SUMMARY} "
        f"WHERE {_build_where_summary()} "
        f"GROUP BY t, series ORDER BY t LIMIT {size} BY t"
    )


def mk_timeseries_multi(title, metrics_spec, gridpos, series_type="line",
                        stacked=False, unit=None, description=None):
    """Multi-metric time series ΓÇö one target per metric."""
    targets = []
    for i, (label, field, op, query) in enumerate(metrics_spec):
        ref = chr(65 + i)
        sql = (
            f"SELECT $__timeInterval({TIME_COL}) AS t, "
            f"{_agg_sql(op, field)} AS value "
            f"FROM {TABLE_RAW} "
            f"WHERE {_build_where(extra=query)} "
            f"GROUP BY t ORDER BY t"
        )
        targets.append(_ch_target(sql, ref_id=ref, alias=label))
    fill = 20 if series_type == "bars" else (50 if stacked else 0)
    custom = {"drawStyle": series_type, "fillOpacity": fill}
    if stacked:
        custom["stacking"] = {"mode": "normal"}
        custom["fillOpacity"] = 50
    defaults: dict = {"custom": custom}
    if unit:
        defaults["unit"] = unit
    return _base_panel(title, "timeseries", gridpos, targets=targets,
                       options={
                           "legend": {"displayMode": "list",
                                      "placement": "right"},
                           "tooltip": {"mode": "multi"},
                       },
                       field_config={"defaults": defaults, "overrides": []},
                       description=description)


def mk_bar(title, field, metric_field, metric_op, metric_label, gridpos,
           size=10, dashboard_uid="alo-main", description=None):
    bucket = _bucket_expression(field)
    sql = (
        f"SELECT {bucket} AS bucket, "
        f"{_agg_sql(metric_op, metric_field)} AS value "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where()} "
        f"GROUP BY bucket ORDER BY value DESC LIMIT {size}"
    )
    panel = _base_panel(title, "barchart", gridpos,
                       targets=[_ch_target(sql, format_as="table")],
                       options={
                           "orientation": "horizontal",
                           "showValue": "always",
                           "legend": {"displayMode": "hidden"},
                           "tooltip": {"mode": "single"},
                       },
                       description=description)
    _add_filter_link(panel, field, dashboard_uid)
    return panel


def mk_stacked_bar(title, bucket_field, metrics_spec, gridpos, size=10,
                   description=None):
    bucket = _bucket_expression(bucket_field)
    select_columns = [f"{bucket} AS bucket"]
    overrides = []
    for label, field, op in metrics_spec:
        alias = _alias_for(op, field, label)
        select_columns.append(f"{_agg_sql(op, field)} AS \"{alias}\"")
    sql = (
        f"SELECT {', '.join(select_columns)} "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where()} "
        f"GROUP BY bucket ORDER BY 1 ASC LIMIT {size}"
    )
    return _base_panel(title, "barchart", gridpos,
                       targets=[_ch_target(sql, format_as="table")],
                       options={
                           "orientation": "horizontal",
                           "showValue": "auto",
                           "stacking": "normal",
                           "legend": {"displayMode": "list",
                                      "placement": "right"},
                           "tooltip": {"mode": "multi"},
                       },
                       field_config={"defaults": {}, "overrides": overrides},
                       description=description)


def mk_table(title, bucket_field, bucket_label, metrics_spec, gridpos,
             size=10, dashboard_uid="alo-main", description=None):
    bucket = _bucket_expression(bucket_field)
    select_columns = [f"{bucket} AS \"{bucket_label}\""]
    sort_alias: str | None = None
    for i, (label, field, op) in enumerate(metrics_spec):
        alias = label
        select_columns.append(f"{_agg_sql(op, field)} AS \"{alias}\"")
        if i == 0:
            sort_alias = alias
    sql = (
        f"SELECT {', '.join(select_columns)} "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where()} "
        f"GROUP BY \"{bucket_label}\" "
        f"ORDER BY \"{sort_alias}\" DESC LIMIT {size}"
    )
    panel = _base_panel(title, "table", gridpos,
                       targets=[_ch_target(sql, format_as="table")],
                       options={
                           "showHeader": True,
                           "sortBy": [{"displayName": sort_alias, "desc": True}],
                       },
                       field_config={"defaults": {}, "overrides": []},
                       description=description)
    _add_filter_link(panel, bucket_field, dashboard_uid)
    return panel


def mk_raw_docs_table(title, columns, gridpos, size=50, query="",
                      sort_field="stress_score", dashboard_uid="alo-main",
                      description=None):
    """Top-N raw documents, returned as a flat table."""
    select = ", ".join(f"{src} AS \"{label}\"" for src, label in columns)
    sql = (
        f"SELECT {select} "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where(extra=query)} "
        f"ORDER BY {sort_field} DESC LIMIT {size}"
    )
    overrides: list[dict] = []
    for src, label in columns:
        var_name = _FIELD_TO_VAR.get(src)
        if not var_name:
            continue
        overrides.append({
            "matcher": {"id": "byName", "options": label},
            "properties": [{"id": "links", "value": [{
                "title": f"Filter by {label}",
                "url": f"/d/{dashboard_uid}?${{__url_time_range}}"
                       f"&var-{var_name}=${{__value.raw}}",
                "targetBlank": False,
            }]}],
        })
    rename_by_name = {src: label for src, label in columns}
    sort_label = rename_by_name.get(sort_field, sort_field)
    return _base_panel(title, "table", gridpos,
                       targets=[_ch_target(sql, format_as="table")],
                       options={
                           "showHeader": True,
                           "sortBy": [{"displayName": sort_label,
                                       "desc": True}],
                       },
                       field_config={"defaults": {}, "overrides": overrides},
                       description=description)


# ΓöÇΓöÇ Templating variables ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

def _make_query_var(name: str, label: str, column: str) -> dict:
    bucket = _bucket_expression(column)
    sql = (
        f"SELECT DISTINCT {bucket} "
        f"FROM {TABLE_RAW} "
        f"WHERE $__timeFilter({TIME_COL}) "
        f"ORDER BY 1 LIMIT 1000"
    )
    return {
        "type": "query",
        "name": name,
        "label": label,
        "datasource": DATASOURCE,
        "query": {"refId": "var", "rawSql": sql, "editorType": "sql"},
        "includeAll": True,
        "allValue": "*",
        "multi": True,
        "sort": 1,
        "refresh": 2,
        "current": {"text": "All", "value": "$__all", "selected": True},
    }


def _wrap_dashboard(uid: str, title: str, description: str,
                    panels: Iterable[dict]) -> dict:
    template_vars: list[dict] = [
        {
            "type": "datasource",
            "name": "datasource",
            "label": "ClickHouse",
            "query": "grafana-clickhouse-datasource",
            "current": {"text": "ClickHouse (ALO)", "value": "alo-clickhouse"},
            "regex": "",
        },
        {
            "type": "datasource",
            "name": "datasource_prometheus",
            "label": "Prometheus",
            "query": "prometheus",
            "current": {"text": "Prometheus (ALO)", "value": "alo-prometheus"},
            "regex": "",
        },
    ]
    template_vars += [_make_query_var(n, label, col)
                      for n, label, col in _VARIABLES]
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
        "panels": list(panels),
        "templating": {"list": template_vars},
        "annotations": {"list": []},
        "editable": True,
    }


def export_dashboards():
    from ._dashboard_builders import (
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
