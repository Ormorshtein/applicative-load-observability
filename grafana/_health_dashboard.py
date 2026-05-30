"""Builds the ALO Stack Health dashboard (Prometheus + ClickHouse).

The dashboard pivots on a single-select ``$cluster`` variable: every panel is
scoped to one cluster and aggregates across that cluster's instances, so the
view stays coherent whether a cluster runs 1 or 50 instances. A collapsed
"Per-Instance Drilldown" row exposes instance-level series on demand.

Metric names are declared once as module constants so they can be corrected in
one place if an exporter renames a series.
"""

from ._dashboards import PROMETHEUS_DS, _reset_ids, mk_text
from ._health_panels import (
    mk_dlq_table,
    mk_dlq_timeseries,
    mk_prom_stat,
    mk_prom_timeseries,
    mk_prom_updown,
)

# ── Metric names ─────────────────────────────────────────────────────────────
# Gateway (nginx-lua-prometheus + nginx-prometheus-exporter)
GW_EVENTS_TOTAL = "alo_gateway_events_total"
GW_EVENTS_DROPPED = "alo_gateway_events_dropped_total"
NGINX_UP = "nginx_up"
NGINX_REQUESTS = "nginx_http_requests_total"
NGINX_ACCEPTED = "nginx_connections_accepted"
NGINX_HANDLED = "nginx_connections_handled"
NGINX_READING = "nginx_connections_reading"
NGINX_WRITING = "nginx_connections_writing"
NGINX_WAITING = "nginx_connections_waiting"

# Analyzer (prometheus-fastapi-instrumentator)
AN_REQUESTS = "http_requests_total"
AN_INPROGRESS = "http_requests_inprogress"
AN_DUR_SUM = "http_request_duration_seconds_sum"
AN_DUR_COUNT = "http_request_duration_seconds_count"
AN_DUR_BUCKET = "http_request_duration_highr_seconds_bucket"
PROC_CPU = "process_cpu_seconds_total"
PROC_MEM = "process_resident_memory_bytes"

# Logstash (kuskoman/logstash-exporter). Pipeline-level flow carries the
# throughput/worker series; node-level flow carries queue backpressure.
LS_INFO_UP = "logstash_info_up"
LS_PIPELINE_UP = "logstash_stats_pipeline_up"
LS_FLOW_INPUT = "logstash_stats_pipeline_flow_input_current"
LS_FLOW_FILTER = "logstash_stats_pipeline_flow_filter_current"
LS_FLOW_OUTPUT = "logstash_stats_pipeline_flow_output_current"
LS_WORKER_UTIL = "logstash_stats_pipeline_flow_worker_utilization_current"
LS_BACKPRESSURE = "logstash_stats_flow_queue_backpressure_current"
LS_QUEUE_EVENTS = "logstash_stats_pipeline_queue_events_count"
LS_PLUGIN_DURATION = "logstash_stats_pipeline_plugin_events_duration"
LS_PLUGIN_OUT = "logstash_stats_pipeline_plugin_events_out"
LS_BULK_ERRORS = "logstash_stats_pipeline_plugin_bulk_requests_errors"
LS_NONRETRYABLE = "logstash_stats_pipeline_plugin_documents_non_retryable_failures"
LS_CPU = "logstash_stats_process_cpu_percent"
LS_FD_OPEN = "logstash_stats_process_open_file_descriptors"
LS_FD_MAX = "logstash_stats_process_max_file_descriptors"
LS_HEAP_USED = "logstash_stats_jvm_mem_heap_used_bytes"
LS_HEAP_MAX = "logstash_stats_jvm_mem_heap_max_bytes"
LS_HEAP_PCT = "logstash_stats_jvm_mem_heap_used_percent"
LS_GC = "logstash_stats_jvm_gc_collection_time_millis_total"
LS_THREADS = "logstash_stats_jvm_threads_count"
LS_THREADS_PEAK = "logstash_stats_jvm_threads_peak_count"

# Elasticsearch (optional, elasticsearch-exporter)
ES_CPU = "elasticsearch_process_cpu_percent"
ES_HEAP_USED = "elasticsearch_jvm_memory_used_bytes"
ES_HEAP_MAX = "elasticsearch_jvm_memory_max_bytes"
ES_GC = "elasticsearch_jvm_gc_collection_seconds_count"
ES_POOL = "elasticsearch_jvm_memory_pool_used_bytes"
ES_TP_QUEUE = "elasticsearch_thread_pool_queue_count"
ES_TP_REJECTED = "elasticsearch_thread_pool_rejected_count"

_RATE = "[$__rate_interval]"
_FULL, _HALF, _THIRD, _QUARTER, _SIXTH = 24, 12, 8, 6, 4
_H = 8
_KPI_H = 4


def _sel(*extra: str) -> str:
    """Cluster-scoped label selector, optionally with extra label matchers."""
    return "{" + ", ".join(['cluster="$cluster"', *extra]) + "}"


# ── Layout helpers ───────────────────────────────────────────────────────────

def _row(title, y, *, collapsed=False, panels=None):
    row = {"type": "row", "title": title, "collapsed": collapsed,
           "gridPos": {"h": 1, "w": _FULL, "x": 0, "y": y}}
    if panels is not None:
        row["panels"] = panels
    return row


def _header(title, y):
    return mk_text(title, f"### {title}", {"x": 0, "y": y, "w": _FULL, "h": 2})


# ── Template variables ───────────────────────────────────────────────────────

def _datasource_var(name, label, plugin, current_text, current_uid):
    return {"type": "datasource", "name": name, "label": label,
            "query": plugin, "regex": "",
            "current": {"text": current_text, "value": current_uid}}


def _cluster_var():
    # `up` is present for every scrape target, so the cluster list is complete
    # even if a given cluster has the gateway or ES exporter disabled.
    query = "label_values(up, cluster)"
    return {"type": "query", "name": "cluster", "label": "Cluster",
            "datasource": PROMETHEUS_DS, "query": query, "definition": query,
            "includeAll": False, "multi": False, "sort": 1, "refresh": 2}


def _instance_var(name, label, metric, extra=""):
    sel = f'{{cluster="$cluster"{("," + extra) if extra else ""}}}'
    query = f"label_values({metric}{sel}, instance)"
    return {"type": "query", "name": name, "label": label,
            "datasource": PROMETHEUS_DS, "query": query, "definition": query,
            "includeAll": True, "allValue": ".*", "multi": True,
            "sort": 1, "refresh": 2}


def _templating():
    return {"list": [
        _datasource_var("datasource_prometheus", "Prometheus", "prometheus",
                        "Prometheus (ALO)", "alo-prometheus"),
        _datasource_var("datasource", "ClickHouse", "grafana-clickhouse-datasource",
                        "ClickHouse (ALO)", "alo-clickhouse"),
        _cluster_var(),
        _instance_var("gateway_instance", "Gateway", NGINX_UP),
        _instance_var("analyzer_instance", "Analyzer", AN_REQUESTS, 'job="analyzer"'),
        _instance_var("logstash_instance", "Logstash", LS_INFO_UP),
        _instance_var("es_instance", "ES Instance", ES_CPU),
    ]}


# ── Panel sections ───────────────────────────────────────────────────────────

def _kpi_row(y):
    """Six aggregated KPI tiles — replace the old per-instance gauge wall."""
    pct = {"unit": "percent"}
    tiles = [
        ("Worker Utilization", f"avg({LS_WORKER_UTIL}{_sel()})",
         {**pct, "thresholds": [(None, "green"), (70, "yellow"), (90, "red")]},
         "Average Logstash worker utilization across the cluster. Near 100% = saturated."),
        ("Max JVM Heap", f"max({LS_HEAP_PCT}{_sel()})",
         {**pct, "thresholds": [(None, "green"), (70, "yellow"), (85, "red")]},
         "Worst-case Logstash JVM heap in the cluster."),
        ("Backpressure", f"max({LS_BACKPRESSURE}{_sel()})",
         {"thresholds": [(None, "green"), (1, "yellow"), (10, "red")]},
         "Worst-case queue backpressure (0 = healthy, >0 = input blocked)."),
        ("Open FDs", f"max({LS_FD_OPEN}{_sel()} / {LS_FD_MAX}{_sel()}) * 100",
         {**pct, "thresholds": [(None, "green"), (70, "yellow"), (90, "red")]},
         "Worst-case file-descriptor usage. Approaching 100% = Logstash will crash."),
        ("Analyzer Load", f"sum({AN_INPROGRESS}{_sel()})",
         {"thresholds": [(None, "green"), (50, "yellow"), (150, "red")]},
         "Total in-flight analyzer requests across the cluster."),
        ("Gateways Up", f"count({NGINX_UP}{_sel()} == 1)",
         {"thresholds": [(None, "red"), (1, "green")]},
         "Healthy gateway instances in the cluster."),
    ]
    panels = []
    for i, (title, expr, opts, desc) in enumerate(tiles):
        panels.append(mk_prom_stat(
            title, expr, {"x": i * _SIXTH, "y": y, "w": _SIXTH, "h": _KPI_H},
            unit=opts.get("unit"), thresholds=opts.get("thresholds"),
            description=desc))
    return panels


def _pipeline_section(y):
    def plugin_time(p):
        sel = _sel(f'plugin="{p}"')
        return (f"sum(rate({LS_PLUGIN_DURATION}{sel}{_RATE})) / "
                f"sum(rate({LS_PLUGIN_OUT}{sel}{_RATE}))")
    return [
        mk_prom_timeseries("Pipeline Flow Rates", [
            (f"sum by (cluster) ({LS_FLOW_INPUT}{_sel()})", "Input"),
            (f"sum by (cluster) ({LS_FLOW_FILTER}{_sel()})", "Filter"),
            (f"sum by (cluster) ({LS_FLOW_OUTPUT}{_sel()})", "Output"),
        ], {"x": 0, "y": y, "w": _HALF, "h": _H}, unit="ops",
            description="Events/sec at each pipeline stage, summed across the "
                        "cluster. If input >> output the pipeline is bottlenecked."),
        mk_prom_timeseries("Queue Depth", [
            (f"sum by (cluster) ({LS_QUEUE_EVENTS}{_sel()})", "Queue depth"),
        ], {"x": _HALF, "y": y, "w": _HALF, "h": _H},
            description="Events waiting in Logstash queues across the cluster. "
                        "Growing = input faster than processing capacity."),
        mk_prom_timeseries("Plugin Time per Event", [
            (plugin_time("http"), "HTTP filter (analyzer)"),
            (plugin_time("elasticsearch"), "ES output"),
            (plugin_time("ruby"), "Ruby filters"),
        ], {"x": 0, "y": y + _H, "w": _HALF, "h": _H}, unit="s",
            description="Avg seconds per event by plugin — shows whether the "
                        "analyzer HTTP filter or the ES output is the bottleneck."),
        mk_prom_timeseries("Output Errors", [
            (f"sum(rate({LS_BULK_ERRORS}{_sel()}{_RATE}))", "bulk errors/s"),
            (f"sum(rate({LS_NONRETRYABLE}{_sel()}{_RATE}))", "non-retryable/s"),
        ], {"x": _HALF, "y": y + _H, "w": _HALF, "h": _H},
            thresholds=[(None, "green"), (1, "red")],
            description="Elasticsearch bulk errors and non-retryable document "
                        "failures. Sustained growth means data loss."),
    ]


def _gateway_section(y):
    return [
        mk_prom_updown("Gateways UP",
                       f"count({NGINX_UP}{_sel()} == 1)",
                       f"count({NGINX_UP}{_sel()})",
                       {"x": 0, "y": y, "w": _QUARTER, "h": _H},
                       description="Healthy vs total gateway instances over time."),
        mk_prom_timeseries("Request Rate", [
            (f"sum(rate({NGINX_REQUESTS}{_sel()}{_RATE}))", "total req/s"),
        ], {"x": _QUARTER, "y": y, "w": _QUARTER, "h": _H}, unit="reqps",
            description="Total gateway request rate across the cluster."),
        mk_prom_timeseries("Connection States", [
            (f"sum by (cluster) ({NGINX_READING}{_sel()})", "reading"),
            (f"sum by (cluster) ({NGINX_WRITING}{_sel()})", "writing"),
            (f"sum by (cluster) ({NGINX_WAITING}{_sel()})", "waiting"),
        ], {"x": _HALF, "y": y, "w": _QUARTER, "h": _H}, stacked=True,
            fill_opacity=30,
            description="Connection states summed across the cluster. High "
                        "'reading' = slow clients; high 'writing' = slow upstream."),
        mk_prom_timeseries("Dropped Connections", [
            (f"sum(rate({NGINX_ACCEPTED}{_sel()}{_RATE})) - "
             f"sum(rate({NGINX_HANDLED}{_sel()}{_RATE}))", "dropped/s"),
        ], {"x": _HALF + _QUARTER, "y": y, "w": _QUARTER, "h": _H},
            thresholds=[(None, "green"), (1, "red")],
            description="Accepted minus handled across the cluster. Should be "
                        "zero; non-zero means a worker_connections limit was hit."),
        mk_prom_timeseries("Events Dropped by Reason", [
            (f"sum by (reason) (rate({GW_EVENTS_DROPPED}{_sel()}{_RATE}))", "{{reason}}"),
        ], {"x": 0, "y": y + _H, "w": _HALF, "h": _H},
            thresholds=[(None, "green"), (1, "red")],
            description="Events the gateway dropped (pipeline notification "
                        "failure), broken down by reason."),
        mk_prom_timeseries("Event Delivery Rate", [
            (f"sum(rate({GW_EVENTS_TOTAL}{_sel()}{_RATE}))", "total events/s"),
            (f"sum(rate({GW_EVENTS_DROPPED}{_sel()}{_RATE}))", "dropped/s"),
        ], {"x": _HALF, "y": y + _H, "w": _HALF, "h": _H},
            description="Total events processed vs dropped per second. "
                        "Healthy = dropped is zero."),
    ]


def _analyzer_section(y):
    analyze = 'handler="/analyze"'
    total_rate = f"sum(rate({AN_REQUESTS}{_sel(analyze)}{_RATE}))"
    sel_4xx = _sel(analyze, 'status=~"4xx"')
    sel_5xx = _sel(analyze, 'status=~"5xx"')
    sel_an_job = _sel('job="analyzer"')

    def quantile(q):
        return (f"histogram_quantile({q}, sum by (le) "
                f"(rate({AN_DUR_BUCKET}{_sel()}{_RATE})))")
    return [
        mk_prom_timeseries("Request Rate", [
            (total_rate, "analyze req/s"),
        ], {"x": 0, "y": y, "w": _THIRD, "h": _H}, unit="reqps",
            description="Analyzer /analyze request rate across the cluster."),
        mk_prom_timeseries("Error Rate", [
            (f"sum(rate({AN_REQUESTS}{sel_4xx}{_RATE})) / {total_rate}", "4xx %"),
            (f"sum(rate({AN_REQUESTS}{sel_5xx}{_RATE})) / {total_rate}", "5xx %"),
        ], {"x": _THIRD, "y": y, "w": _THIRD, "h": _H}, unit="percentunit",
            thresholds=[(None, "green"), (0.01, "red")],
            description="Fraction of non-2xx /analyze responses. The analyzer "
                        "should always return 200 — any errors signal a real issue."),
        mk_prom_timeseries("Latency (P50 / P95 / P99)", [
            (quantile(0.50), "p50"),
            (quantile(0.95), "p95"),
            (quantile(0.99), "p99"),
        ], {"x": 2 * _THIRD, "y": y, "w": _THIRD, "h": _H}, unit="s",
            fill_opacity=0,
            description="Request-duration percentiles aggregated across the cluster."),
        mk_prom_timeseries("CPU Usage", [
            (f"avg(rate({PROC_CPU}{sel_an_job}{_RATE})) * 100", "avg cpu %"),
        ], {"x": 0, "y": y + _H, "w": _HALF, "h": _H}, unit="percent",
            description="Average analyzer process CPU across the cluster."),
        mk_prom_timeseries("Memory Usage", [
            (f"sum({PROC_MEM}{sel_an_job})", "resident"),
        ], {"x": _HALF, "y": y + _H, "w": _HALF, "h": _H}, unit="bytes",
            description="Total analyzer resident memory across the cluster."),
    ]


def _logstash_section(y):
    sel_gc_old = _sel('type="old"')
    sel_gc_young = _sel('type="young"')
    return [
        mk_prom_updown("Pipelines UP",
                       f"count({LS_PIPELINE_UP}{_sel()} == 1)",
                       f"count({LS_PIPELINE_UP}{_sel()})",
                       {"x": 0, "y": y, "w": _HALF, "h": _H},
                       description="Healthy vs total Logstash pipelines over time."),
        mk_prom_timeseries("CPU Usage", [
            (f"avg({LS_CPU}{_sel()})", "avg cpu %"),
        ], {"x": _HALF, "y": y, "w": _HALF, "h": _H}, unit="percent",
            description="Average Logstash process CPU across the cluster."),
        mk_prom_timeseries("JVM Heap", [
            (f"sum({LS_HEAP_USED}{_sel()})", "used"),
            (f"sum({LS_HEAP_MAX}{_sel()})", "max"),
        ], {"x": 0, "y": y + _H, "w": _HALF, "h": _H}, unit="bytes",
            description="Logstash JVM heap used vs max, summed across the cluster."),
        mk_prom_timeseries("GC Pressure", [
            (f"sum(rate({LS_GC}{sel_gc_old}{_RATE}))", "old gc ms/s"),
            (f"sum(rate({LS_GC}{sel_gc_young}{_RATE}))", "young gc ms/s"),
        ], {"x": _HALF, "y": y + _H, "w": _HALF, "h": _H}, unit="ms",
            description="GC time rate. Sustained old-gen GC is the #1 cause of "
                        "Logstash freezes."),
        mk_prom_timeseries("JVM Threads", [
            (f"sum({LS_THREADS}{_sel()})", "current"),
            (f"sum({LS_THREADS_PEAK}{_sel()})", "peak"),
        ], {"x": 0, "y": y + 2 * _H, "w": _FULL, "h": _H},
            description="Logstash JVM thread count summed across the cluster."),
    ]


def _es_panels(y):
    sel_tp = _sel('type=~"search|write"')
    return [
        mk_prom_timeseries("ES CPU", [
            (f"avg({ES_CPU}{_sel()})", "avg cpu %"),
        ], {"x": 0, "y": y, "w": _HALF, "h": _H}, unit="percent",
            description="Average Elasticsearch process CPU across the cluster."),
        mk_prom_timeseries("ES JVM Heap", [
            (f"sum({ES_HEAP_USED}{_sel()})", "used"),
            (f"sum({ES_HEAP_MAX}{_sel()})", "max"),
        ], {"x": _HALF, "y": y, "w": _HALF, "h": _H}, unit="bytes",
            description="Elasticsearch JVM heap used vs max across the cluster."),
        mk_prom_timeseries("ES GC Rate", [
            (f"sum by (gc) (rate({ES_GC}{_sel()}{_RATE}))", "{{gc}}"),
        ], {"x": 0, "y": y + _H, "w": _HALF, "h": _H},
            description="Elasticsearch garbage-collection rate by collector."),
        mk_prom_timeseries("ES Thread Pool Queues", [
            (f"sum by (type) ({ES_TP_QUEUE}{sel_tp})", "{{type}}"),
        ], {"x": _HALF, "y": y + _H, "w": _HALF, "h": _H},
            description="Queued search/write operations. Growing queues = ES is "
                        "the bottleneck."),
        mk_prom_timeseries("ES Rejected Operations", [
            (f"sum by (type) (rate({ES_TP_REJECTED}{sel_tp}{_RATE}))", "{{type}} rejected/s"),
        ], {"x": 0, "y": y + 2 * _H, "w": _FULL, "h": _H},
            thresholds=[(None, "green"), (1, "red")],
            description="Rejected thread-pool tasks per second. Non-zero = ES is "
                        "overloaded and dropping work."),
    ]


def _drilldown_panels(y):
    """Per-instance series, capped with topk so 50 instances stay readable."""
    ls = 'instance=~"$logstash_instance"'
    an = 'instance=~"$analyzer_instance"'
    gw = 'instance=~"$gateway_instance"'
    return [
        mk_prom_timeseries("Logstash Worker Utilization (per instance)", [
            (f"topk(10, {LS_WORKER_UTIL}{_sel(ls)})", "{{instance}}"),
        ], {"x": 0, "y": y, "w": _HALF, "h": _H}, unit="percent",
            description="Top 10 Logstash instances by worker utilization."),
        mk_prom_timeseries("Logstash JVM Heap (per instance)", [
            (f"topk(10, {LS_HEAP_PCT}{_sel(ls)})", "{{instance}}"),
        ], {"x": _HALF, "y": y, "w": _HALF, "h": _H}, unit="percent",
            description="Top 10 Logstash instances by JVM heap usage."),
        mk_prom_timeseries("Analyzer In-Progress (per instance)", [
            (f"topk(10, {AN_INPROGRESS}{_sel(an)})", "{{instance}}"),
        ], {"x": 0, "y": y + _H, "w": _HALF, "h": _H},
            description="Top 10 analyzer instances by in-flight requests."),
        mk_prom_timeseries("Gateway Request Rate (per instance)", [
            (f"topk(10, sum by (instance) (rate({NGINX_REQUESTS}{_sel(gw)}{_RATE})))", "{{instance}}"),
        ], {"x": _HALF, "y": y + _H, "w": _HALF, "h": _H}, unit="reqps",
            description="Top 10 gateway instances by request rate."),
    ]


# ── Assembly ─────────────────────────────────────────────────────────────────

def build_health_dashboard() -> dict:
    _reset_ids()
    panels: list[dict] = []
    y = 0

    panels.append(_header("Cluster Health", y)); y += 2
    panels.extend(_kpi_row(y)); y += _KPI_H

    panels.append(_row("Logstash Pipeline Throughput", y)); y += 1
    panels.extend(_pipeline_section(y)); y += 2 * _H

    panels.append(_row("Gateway (Nginx)", y)); y += 1
    panels.extend(_gateway_section(y)); y += 2 * _H

    panels.append(_row("Analyzer (FastAPI)", y)); y += 1
    panels.extend(_analyzer_section(y)); y += 2 * _H

    panels.append(_row("Logstash Resources", y)); y += 1
    panels.extend(_logstash_section(y)); y += 3 * _H

    panels.append(_row("Dead Letter Queue", y)); y += 1
    panels.append(mk_dlq_timeseries(
        {"x": 0, "y": y, "w": _FULL, "h": _H},
        description="Documents in the dead-letter table for this cluster. "
                    "Growth means the analyzer produced unindexable records."))
    y += _H
    panels.append(mk_dlq_table(
        {"x": 0, "y": y, "w": _FULL, "h": 10},
        description="Recent dead-letter documents for this cluster — what was "
                    "rejected and why."))
    y += 10

    # Collapsed: Elasticsearch (optional exporter) and per-instance drilldown.
    panels.append(_row("Elasticsearch (optional — requires elasticsearch-exporter)",
                       y, collapsed=True, panels=_es_panels(y + 1)))
    y += 1
    panels.append(_row("Per-Instance Drilldown", y,
                       collapsed=True, panels=_drilldown_panels(y + 1)))
    y += 1

    return {
        "uid": "alo-health",
        "title": "ALO — Stack Health",
        "description": "Per-cluster operational health of the ALO pipeline: "
                       "gateway, analyzer, and logstash.",
        "tags": ["alo", "health", "prometheus"],
        "timezone": "browser",
        "schemaVersion": 40,
        "version": 1,
        "refresh": "15s",
        "graphTooltip": 1,
        "time": {"from": "now-30m", "to": "now"},
        "panels": panels,
        "templating": _templating(),
        "annotations": {"list": []},
        "links": [{
            "title": "Stress Analysis", "url": "/d/alo-main", "icon": "dashboard",
            "tooltip": "Jump to ALO Stress Analysis dashboard", "type": "link",
        }],
        "editable": True,
    }
