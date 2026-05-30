"""
Grafana dashboard JSON builders for ALO (ClickHouse datasource).

Public helpers (``mk_stat``, ``mk_pie``, ``mk_timeseries`` ...) keep the same
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

_CHEAT_SHEET_HE_PATH = os.path.join(SCRIPT_DIR, "cheat_sheet_he.html")
CHEAT_SHEET_HE: str = (
    open(_CHEAT_SHEET_HE_PATH, encoding="utf-8").read()
    if os.path.exists(_CHEAT_SHEET_HE_PATH)
    else CHEAT_SHEET
)


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
    """Build a SQL clause that honours Grafana's multi-select All.

    Uses $__conditionalAll which renders 1=1 when the variable is set to All
    ($__all), and the actual condition otherwise. This avoids IN () parse
    errors in ClickHouse when no values are selected.

    The Array column stress_cost_indicator_names uses hasAny instead of IN.
    """
    macro = f"${{{var}:singlequote}}"
    if column == "stress_cost_indicator_names":
        return f"$__conditionalAll(hasAny({column}, [{macro}]), ${var})"
    return f"$__conditionalAll({column} IN ({macro}), ${var})"


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
               alias: str | None = None,
               legend_format: str | None = None) -> dict:
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
    if legend_format:
        target["legendFormat"] = legend_format
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
            "expr": 'elasticsearch_process_cpu_percent{cluster=~"$cluster"}',
            "legendFormat": "{{cluster}}",
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
            },
            "overrides": [],
        },
    }


_STAT_CALC = {"sum": "sum", "count": "sum", "avg": "mean", "max": "max"}


def mk_stat(title, field, operation, gridpos, query="", description=None):
    """Single-number reduction across the visible time range."""
    sql = (
        f"SELECT {_agg_sql(operation, field)} AS value "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where(extra=query)}"
    )
    return _base_panel(title, "stat", gridpos,
                       targets=[_ch_target(sql, format_as="table")],
                       options={
                           "reduceOptions": {"calcs": ["lastNotNull"],
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
        "url": f"/d/${{__dashboard.uid}}?${{__url_time_range}}"
               f"&var-{var_name}=${{__data.fields[0]}}",
        "targetBlank": False,
    }]


def _add_pie_filter_link(panel, field, dashboard_uid="alo-main"):
    """Datalink for pie charts after rowsToFields: slice label = ${__field.name}."""
    var_name = _FIELD_TO_VAR.get(field)
    if not var_name:
        return
    panel["fieldConfig"]["defaults"]["links"] = [{
        "title": "Filter by ${__field.name}",
        "url": f"/d/${{__dashboard.uid}}?${{__url_time_range}}"
               f"&var-{var_name}=${{__field.name}}",
        "targetBlank": False,
    }]


def _bucket_expression(field: str) -> str:
    """SQL expression that produces one row per dimension value.

    Array columns are unnested via ``arrayJoin``. Empty arrays (unflagged
    requests) are replaced with a synthetic ``['unflagged']`` so they still
    contribute a visible slice instead of being dropped by the join.
    """
    if field == "stress_cost_indicator_names":
        return ("arrayJoin(if(empty(stress_cost_indicator_names), "
                "['unflagged'], stress_cost_indicator_names))")
    return field


def mk_pie(title, field, gridpos, size=8, dashboard_uid="alo-main",
           description=None):
    bucket = _bucket_expression(field)
    if field == "request_template":
        label_expr = f"COALESCE(nullIf(LEFT(toString({bucket}), 60), ''), '(no template)')"
    else:
        label_expr = f"COALESCE(nullIf(toString({bucket}), ''), '(unknown)')"
    sql = (
        f"SELECT {label_expr} AS label, sum(stress_score) AS __val "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where()} "
        f"GROUP BY label ORDER BY __val DESC LIMIT {size}"
    )
    panel = _base_panel(title, "piechart", gridpos,
                       targets=[_ch_target(sql, format_as="table")],
                       options={
                           "reduceOptions": {"calcs": ["sum"],
                                             "fields": "",
                                             "values": False},
                           "pieType": "pie",
                           "legend": {"displayMode": "list",
                                      "placement": "bottom",
                                      "values": ["value", "percent"]},
                           "tooltip": {"mode": "multi"},
                       },
                       transformations=[
                           {"id": "partitionByValues",
                            "options": {"fields": ["label"], "keepFields": False}},
                           {"id": "renameByRegex",
                            "options": {"regex": "^__val (.+)$", "renamePattern": "$1"}},
                       ],
                       description=description)
    _add_pie_filter_link(panel, field, dashboard_uid)
    return panel


def mk_timeseries(title, field, gridpos, metric_field="stress_score",
                  metric_op="avg", size=5, series_type="line",
                  fill_opacity=20, summary_fallback=False, unit=None,
                  description=None):
    """Time-series panel.

    When *field* is set the CH plugin returns narrow ``(t, series, value)``
    format. The plugin does NOT auto-split by the string column, so we use
    ``format_as="table"`` + a ``partitionByValues`` Grafana transformation to
    produce one frame per series value.

    When *summary_fallback* is True a second target reads ``alo_summary``
    (dashed) so the chart stays populated after raw TTL expiry.
    """
    overrides: list[dict] = []
    transformations: list[dict] = []

    if field is None:
        col_alias = _alias_for(metric_op, metric_field)
        targets = [_ch_target(_timeseries_sql(None, metric_field, metric_op, size),
                              ref_id="A", legend_format=col_alias)]
        if summary_fallback:
            # Plain identifier alias — no spaces/parens — so the CH plugin
            # sets a distinct field name and avoids auto-refId prefix on A.
            summary_alias = f"{col_alias}_summary"
            targets.append(_ch_target(
                _summary_timeseries_sql(None, metric_field, metric_op, size,
                                        alias_override=summary_alias),
                ref_id="B", legend_format=summary_alias))
            # Grafana 11 prefixes all multi-frame series with refId ("a X").
            # displayName override wins over the auto-prefix for both A and B.
            overrides.append({
                "matcher": {"id": "byName", "options": col_alias},
                "properties": [{"id": "displayName", "value": col_alias}],
            })
            overrides.append({
                "matcher": {"id": "byName", "options": summary_alias},
                "properties": [
                    {"id": "custom.lineStyle",
                     "value": {"fill": "dash", "dash": [10, 10]}},
                    {"id": "custom.lineWidth", "value": 1},
                    {"id": "displayName", "value": f"{col_alias} (summary)"},
                ],
            })
    else:
        # Narrow table format — partitionByValues splits frames by series value.
        # renameByRegex strips the "value " prefix Grafana 11 prepends when the
        # value field name is "value" and the frame also carries a name.
        targets = [_ch_target(_timeseries_sql(field, metric_field, metric_op, size),
                              ref_id="A", format_as="table")]
        if summary_fallback:
            targets.append(_ch_target(
                _summary_timeseries_sql(field, metric_field, metric_op, size),
                ref_id="B", format_as="table"))
        transformations = [
            {"id": "partitionByValues",
             "options": {"fields": ["series"], "keepFields": False}},
            {"id": "renameByRegex",
             "options": {"regex": "^value (.+)$", "renamePattern": "$1"}},
        ]

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
                       transformations=transformations or None,
                       description=description)


def _timeseries_sql(field: str | None, metric_field: str | None,
                    metric_op: str, size: int) -> str:
    metric_sql = _agg_sql(metric_op, metric_field)
    if field is None:
        col_alias = _alias_for(metric_op, metric_field)
        return (
            f"SELECT $__timeInterval({TIME_COL}) AS t, "
            f"{metric_sql} AS \"{col_alias}\" "
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
                            metric_op: str, size: int,
                            alias_override: str | None = None) -> str:
    """Equivalent of `_timeseries_sql` but against the summary table."""
    override = _SUMMARY_AGG_OVERRIDES.get((metric_op, metric_field))
    if override:
        agg_fn, state_col = override
        metric_sql = f"{agg_fn}({state_col})"
    else:
        # Fallback: percentiles, max, etc. — emit raw aggregate; will be
        # NULL after TTL but no worse than the raw fallback.
        metric_sql = _agg_sql(metric_op, metric_field)

    if field is None:
        col_alias = alias_override or _alias_for(metric_op, metric_field)
        return (
            f"SELECT toStartOfHour(time_bucket) AS t, "
            f"{metric_sql} AS \"{col_alias}\" "
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
        f"  AND {bucket} IN ("
        f"    SELECT {bucket} FROM {TABLE_SUMMARY} "
        f"    WHERE {_build_where_summary()} "
        f"    GROUP BY {bucket} ORDER BY {metric_sql} DESC LIMIT {size}"
        f"  ) "
        f"GROUP BY t, series ORDER BY t"
    )


def mk_timeseries_multi(title, metrics_spec, gridpos, series_type="line",
                        stacked=False, unit=None, description=None):
    """Multi-metric time series — all metrics in one wide query."""
    extra_filters = " AND ".join(
        q for _, _, _, q in metrics_spec if q
    ) or ""
    cols = ", ".join(
        f"{_agg_sql(op, field)} AS \"{label}\""
        for label, field, op, _ in metrics_spec
    )
    sql = (
        f"SELECT $__timeInterval({TIME_COL}) AS t, {cols} "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where(extra=extra_filters)} "
        f"GROUP BY t ORDER BY t"
    )
    targets = [_ch_target(sql, ref_id="A")]
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


def mk_timeseries_grouped(title, field1, field2, gridpos, size=10,
                          series_type="line", fill_opacity=20, unit=None,
                          description=None):
    """Time-series with one series per (field1 / field2) combination.

    Emits ``field1/field2`` as series labels (e.g. ``search/200``).
    Only the top-N most frequent combinations are shown.
    """
    combined = f"concat({field1}, '/', toString({field2}))"
    sql = (
        f"SELECT $__timeInterval({TIME_COL}) AS t, "
        f"{combined} AS series, "
        f"count() AS value "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where()} "
        f"  AND {combined} IN ("
        f"    SELECT {combined} FROM {TABLE_RAW} "
        f"    WHERE {_build_where()} "
        f"    GROUP BY {combined} ORDER BY count() DESC LIMIT {size}"
        f"  ) "
        f"GROUP BY t, series ORDER BY t"
    )
    custom = {"drawStyle": series_type, "fillOpacity": fill_opacity}
    defaults: dict = {"custom": custom}
    if unit:
        defaults["unit"] = unit
    return _base_panel(title, "timeseries", gridpos,
                       targets=[_ch_target(sql, ref_id="A", format_as="table")],
                       options={
                           "legend": {"displayMode": "list", "placement": "right"},
                           "tooltip": {"mode": "multi"},
                       },
                       field_config={"defaults": defaults, "overrides": []},
                       transformations=[
                           {"id": "partitionByValues",
                            "options": {"fields": ["series"], "keepFields": False}},
                           {"id": "renameByRegex",
                            "options": {"regex": "^value (.+)$",
                                        "renamePattern": "$1"}},
                       ],
                       description=description)


def mk_bar(title, field, metric_field, metric_op, metric_label, gridpos,
           size=10, dashboard_uid="alo-main", description=None):
    bucket = _bucket_expression(field)
    sql = (
        f"SELECT {bucket} AS bucket, "
        f"{_agg_sql(metric_op, metric_field)} AS \"{metric_label}\" "
        f"FROM {TABLE_RAW} "
        f"WHERE {_build_where()} "
        f"GROUP BY bucket ORDER BY \"{metric_label}\" DESC LIMIT {size}"
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
    _DATETIME_COLS = {"timestamp"}
    _ARRAY_COLS = {"stress_cost_indicator_names"}

    def _col_expr(src, label):
        if src in _DATETIME_COLS:
            return f"formatDateTime({src}, '%Y-%m-%d %H:%M:%S') AS \"{label}\""
        if src in _ARRAY_COLS:
            return f"arrayStringConcat({src}, ', ') AS \"{label}\""
        return f"{src} AS \"{label}\""

    select = ", ".join(_col_expr(src, label) for src, label in columns)
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
                "url": f"/d/${{__dashboard.uid}}?${{__url_time_range}}"
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

# Columns present in alo_summary — use it for variable queries (fast, pre-agg).
# Others fall back to alo_raw with a memory cap.
# Columns in alo_summary — tiny pre-aggregated table, safe without time filter.
# Others fall back to alo_raw scoped to last 7 days to limit scan.
_SUMMARY_COLUMNS = {
    "cluster_name", "identity_applicative_provider",
    "request_target", "request_operation", "request_template",
}


def _make_query_var(name: str, label: str, column: str) -> dict:
    bucket = _bucket_expression(column)
    if column in _SUMMARY_COLUMNS:
        sql = (
            f"SELECT DISTINCT {bucket} FROM {TABLE_SUMMARY} "
            f"ORDER BY 1 LIMIT 1000"
        )
    else:
        sql = (
            f"SELECT DISTINCT {bucket} FROM {TABLE_RAW} "
            f"WHERE {TIME_COL} > now() - INTERVAL 7 DAY "
            f"ORDER BY 1 LIMIT 500"
        )
    return {
        "type": "query",
        "name": name,
        "label": label,
        "datasource": DATASOURCE,
        "query": sql,
        "definition": sql,
        "includeAll": True,
        "multi": True,
        "sort": 1,
        "refresh": 2,
        "current": {"text": "All", "value": "$__all", "selected": True},
    }


def _wrap_dashboard(uid: str, title: str, description: str,
                    panels: Iterable[dict],
                    links: list[dict] | None = None) -> dict:
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
        "name": "filters",
        "label": "Filters",
        "datasource": DATASOURCE,
    })
    return {
        "uid": uid,
        "title": title,
        "description": description,
        "tags": ["alo", "observability"],
        "timezone": "browser",
        "schemaVersion": 40,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-15m", "to": "now"},
        "panels": list(panels),
        "templating": {"list": template_vars},
        "annotations": {"list": []},
        "links": links or [],
        "editable": True,
    }


# Helm bakes dashboards into a ConfigMap from these files (see
# helm/alo/templates/grafana/configmap-dashboards.yaml). Generate them from the
# same builders so the chart never drifts from the provisioning directory.
HELM_FILES_DIR = os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", "helm", "alo", "files"))


def export_dashboards():
    from ._dashboard_builders import (
        build_cost_indicators_dashboard,
        build_main_dashboard,
        build_main_dashboard_he,
        build_usage_dashboard,
    )
    from ._health_dashboard import build_health_dashboard

    os.makedirs(PROVISION_DIR, exist_ok=True)
    helm_ok = os.path.isdir(HELM_FILES_DIR)

    for builder, filename in [
        (build_main_dashboard, "alo-main.json"),
        (build_main_dashboard_he, "alo-main-he.json"),
        (build_cost_indicators_dashboard, "alo-cost-indicators.json"),
        (build_usage_dashboard, "alo-usage.json"),
        (build_health_dashboard, "alo-health.json"),
    ]:
        dashboard = builder()
        payload = json.dumps(dashboard, indent=2)
        path = os.path.join(PROVISION_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"  Exported: {path}")
        if helm_ok:
            helm_path = os.path.join(HELM_FILES_DIR, f"grafana-{filename}")
            with open(helm_path, "w", encoding="utf-8") as f:
                f.write(payload)
            print(f"  Exported: {helm_path}")

    return PROVISION_DIR


if __name__ == "__main__":
    export_dashboards()
