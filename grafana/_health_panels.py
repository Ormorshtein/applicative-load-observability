"""Panel factories for the ALO Stack Health dashboard.

Unlike the analysis dashboards (ClickHouse, built in ``_dashboards.py``), the
health dashboard is Prometheus-first: it watches the operational health of the
gateway, analyzer, and logstash fleet. Two dead-letter-queue panels read
ClickHouse instead.

Every PromQL query is **cluster-scoped** (``{cluster="$cluster"}``) and
aggregates across instances (``sum``/``avg``/``max`` ``by (cluster)``), so a
cluster running 50 logstash instances still renders a bounded number of series
instead of one line per instance. A collapsed per-instance drilldown keeps
instance-level detail available on demand.

These helpers reuse the panel scaffolding (``_base_panel``, ``_next_id``,
``_ch_target``) and datasource references (``DATASOURCE``, ``PROMETHEUS_DS``)
from ``_dashboards.py`` so panel JSON stays consistent across dashboards.
"""

from ._dashboards import (
    DATASOURCE,
    PROMETHEUS_DS,
    _base_panel,
    _ch_target,
)

_REF_IDS = "ABCDEFGHIJ"


def _thresholds(steps: list[tuple[float | None, str]]) -> dict:
    """Render a Grafana threshold config from ``(value, color)`` pairs."""
    return {"mode": "absolute",
            "steps": [{"value": value, "color": color} for value, color in steps]}


def _prom_target(expr: str, legend: str = "", ref_id: str = "A") -> dict:
    return {"datasource": PROMETHEUS_DS, "expr": expr,
            "legendFormat": legend, "refId": ref_id}


# ── Prometheus panels ────────────────────────────────────────────────────────

def mk_prom_timeseries(title, exprs, gridpos, *, unit=None, stacked=False,
                       fill_opacity=10, thresholds=None, decimals=None,
                       overrides=None, description=None):
    """Time-series panel from a list of ``(promql, legend)`` pairs.

    ``thresholds`` (a list of ``(value, color)``) also draws a threshold line,
    used for "should always be zero" panels (dropped connections, errors).
    """
    targets = [_prom_target(expr, legend, _REF_IDS[i])
               for i, (expr, legend) in enumerate(exprs)]
    custom = {"drawStyle": "line", "lineWidth": 2,
              "fillOpacity": fill_opacity, "spanNulls": False}
    if stacked:
        custom["stacking"] = {"mode": "normal"}
    defaults: dict = {"custom": custom}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    if thresholds:
        defaults["thresholds"] = _thresholds(thresholds)
        custom["thresholdsStyle"] = {"mode": "line"}
    panel = _base_panel(title, "timeseries", gridpos, targets=targets,
                        options={"legend": {"displayMode": "list",
                                            "placement": "bottom"},
                                 "tooltip": {"mode": "multi"}},
                        field_config={"defaults": defaults,
                                      "overrides": overrides or []},
                        description=description)
    panel["datasource"] = PROMETHEUS_DS
    return panel


def mk_prom_stat(title, expr, gridpos, *, unit=None, thresholds=None,
                 decimals=None, description=None):
    """Single-value KPI tile (replaces the old per-instance gauges).

    With single-select ``$cluster`` plus an aggregation wrapper the query
    returns one value, so the tile stays readable no matter how many instances
    the cluster runs. Threshold steps colour the tile.
    """
    defaults: dict = {}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    if thresholds:
        defaults["thresholds"] = _thresholds(thresholds)
    panel = _base_panel(title, "stat", gridpos,
                        targets=[_prom_target(expr)],
                        options={"reduceOptions": {"calcs": ["lastNotNull"],
                                                   "fields": "", "values": False},
                                 "colorMode": "value",
                                 "graphMode": "area",
                                 "textMode": "auto",
                                 "justifyMode": "auto"},
                        field_config={"defaults": defaults, "overrides": []},
                        description=description)
    panel["datasource"] = PROMETHEUS_DS
    return panel


def mk_prom_updown(title, up_expr, total_expr, gridpos, *, description=None):
    """Healthy-instance count vs total, with the total drawn as a dashed line."""
    overrides = [{
        "matcher": {"id": "byName", "options": "total"},
        "properties": [
            {"id": "custom.lineStyle",
             "value": {"fill": "dash", "dash": [10, 10]}},
            {"id": "color", "value": {"fixedColor": "white", "mode": "fixed"}},
        ],
    }]
    return mk_prom_timeseries(
        title, [(up_expr, "up"), (total_expr, "total")], gridpos,
        unit="short", decimals=0, fill_opacity=20,
        overrides=overrides, description=description)


# ── ClickHouse dead-letter-queue panels ──────────────────────────────────────

# Single-select $cluster — substituted as a bare value, so quote it in SQL.
_CLUSTER_PREDICATE = "cluster_name = '${cluster}'"


def mk_dlq_timeseries(gridpos, *, description=None):
    sql = (
        "SELECT toStartOfInterval(timestamp, INTERVAL $__interval_s second) AS time, "
        "count() AS \"DLQ docs\" FROM alo.alo_dead_letter "
        f"WHERE $__timeFilter(timestamp) AND {_CLUSTER_PREDICATE} "
        "GROUP BY time ORDER BY time"
    )
    return _base_panel(
        "DLQ Document Count", "timeseries", gridpos,
        targets=[_ch_target(sql, format_as="time_series")],
        options={"legend": {"displayMode": "list", "placement": "bottom"},
                 "tooltip": {"mode": "single"}},
        field_config={"defaults": {
            "custom": {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 10,
                       "thresholdsStyle": {"mode": "line"}},
            "thresholds": _thresholds([(None, "green"), (1, "red")]),
        }, "overrides": []},
        description=description)


def mk_dlq_table(gridpos, *, size=20, description=None):
    sql = (
        "SELECT timestamp AS Time, error AS Error, request_path AS Path, "
        "request_method AS Method FROM alo.alo_dead_letter "
        f"WHERE $__timeFilter(timestamp) AND {_CLUSTER_PREDICATE} "
        f"ORDER BY timestamp DESC LIMIT {size}"
    )
    width = {"Error": 500, "Time": 160, "Path": 200, "Method": 80}
    overrides = [{
        "matcher": {"id": "byName", "options": name},
        "properties": [{"id": "custom.width", "value": value}],
    } for name, value in width.items()]
    return _base_panel(
        "DLQ Documents (Recent)", "table", gridpos,
        targets=[_ch_target(sql, format_as="table")],
        options={"showHeader": True,
                 "sortBy": [{"displayName": "Time", "desc": True}]},
        field_config={"defaults": {"custom": {"align": "auto"}},
                      "overrides": overrides},
        description=description)
