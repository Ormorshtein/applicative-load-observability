"""
ClickHouse schema for the Applicative Load Observability stack.

Single source of truth for the analytics-sink schema. Emits DDL for:

* ``alo_raw`` — flat snake_case columns mirroring ``ObservabilityRecord``.
* ``alo_dead_letter`` — permissive table for events that failed analysis.
* ``alo_summary`` — ``AggregatingMergeTree`` of pre-aggregated state.
* ``alo_summary_mv`` — incremental materialized view from raw → summary.

Cluster topology
~~~~~~~~~~~~~~~~
When ``TableSettings.cluster_enabled`` is true, every table becomes a
local/Distributed pair:

* ``<name>_local`` — ``Replicated*MergeTree`` on each shard, replicated by
  ClickHouse Keeper.
* ``<name>`` — ``Distributed`` engine in front, fanning writes/reads across
  shards using ``cityHash64(cluster_name, request_operation)``.

Clients (Logstash, analyzer, Grafana) always reference the unsuffixed
names. In single-node mode they are the actual tables; in cluster mode
they are the Distributed front. The client code path stays uniform.

Long-term retention
~~~~~~~~~~~~~~~~~~~
Raw rows expire via TTL (default 3 days). The materialized view emits
per-insert ``*State`` rows into the summary table, which retains 120
days. Grafana finalises summary state with ``*Merge`` aggregates.
"""

import os
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class TableSettings:
    """User-tunable retention and topology knobs."""

    database:                 str  = field(default_factory=lambda: os.getenv("CLICKHOUSE_DATABASE", "alo"))
    raw_retention_days:       int  = 3
    summary_retention_days:   int  = 120
    raw_partition_by:         str  = "toYYYYMMDD(timestamp)"
    summary_partition_by:     str  = "toYYYYMM(time_bucket)"

    cluster_enabled:          bool = False
    cluster_name:             str  = "alo_cluster"
    sharding_key:             str  = "cityHash64(cluster_name, request_operation)"


# ── Column inventory ───────────────────────────────────────────────────────
# Order matters: the table is created in this order, which matches the
# flattened ``ObservabilityRecord`` emitted by ``analyzer/record_builder.py``.
_RAW_COLUMNS: list[tuple[str, str]] = [
    ("timestamp",                            "DateTime64(3, 'UTC')"),

    ("identity_username",                    "LowCardinality(String)"),
    ("identity_applicative_provider",        "LowCardinality(String)"),
    ("identity_user_agent",                  "LowCardinality(String)"),
    ("identity_client_host",                 "LowCardinality(String)"),
    ("identity_labels",                      "Map(String, String)"),

    ("request_method",                       "LowCardinality(String)"),
    ("request_path",                         "String"),
    ("request_operation",                    "LowCardinality(String)"),
    ("request_target",                       "LowCardinality(String)"),
    ("request_template",                     "String"),
    ("request_body",                         "String CODEC(ZSTD(3))"),
    ("request_size_bytes",                   "UInt32"),
    ("request_size",                         "UInt32"),
    ("request_geo_vertex_count",             "UInt32"),

    ("response_status",                      "UInt16"),
    ("response_es_took_ms",                  "Float32"),
    ("response_gateway_took_ms",             "Float32"),
    ("response_hits",                        "UInt64"),
    ("response_shards_total",                "UInt32"),
    ("response_docs_affected",               "UInt64"),
    ("response_size_bytes",                  "UInt32"),

    ("clause_counts_bool",                   "UInt16"),
    ("clause_counts_bool_must",              "UInt16"),
    ("clause_counts_bool_should",            "UInt16"),
    ("clause_counts_bool_filter",            "UInt16"),
    ("clause_counts_bool_must_not",          "UInt16"),
    ("clause_counts_terms_values",           "UInt32"),
    ("clause_counts_knn",                    "UInt16"),
    ("clause_counts_fuzzy",                  "UInt16"),
    ("clause_counts_geo_bbox",               "UInt16"),
    ("clause_counts_geo_distance",           "UInt16"),
    ("clause_counts_geo_shape",              "UInt16"),
    ("clause_counts_agg",                    "UInt16"),
    ("clause_counts_wildcard",               "UInt16"),
    ("clause_counts_nested",                 "UInt16"),
    ("clause_counts_runtime_mapping",        "UInt16"),
    ("clause_counts_script",                 "UInt16"),

    ("cost_indicators_has_script",           "UInt8"),
    ("cost_indicators_has_runtime_mapping",  "UInt8"),
    ("cost_indicators_has_wildcard",         "UInt8"),
    ("cost_indicators_has_nested",           "UInt8"),
    ("cost_indicators_has_fuzzy",            "UInt8"),
    ("cost_indicators_has_geo",              "UInt8"),
    ("cost_indicators_has_knn",              "UInt8"),
    ("cost_indicators_excessive_bool",       "UInt8"),
    ("cost_indicators_large_terms_list",     "UInt8"),
    ("cost_indicators_deep_aggs",            "UInt8"),
    ("cost_indicators_unbound_hits",         "UInt8"),

    ("stress_score",                         "Float32"),
    ("stress_base",                          "Float32"),
    ("stress_multiplier",                    "Float32"),
    ("stress_components_took",               "Float32"),
    ("stress_components_shards",             "Float32"),
    ("stress_components_hits",               "Float32"),
    ("stress_components_docs_affected",      "Float32"),
    ("stress_components_bonus",              "Float32"),
    ("stress_cost_indicator_count",          "UInt16"),
    ("stress_cost_indicator_names",          "Array(LowCardinality(String))"),
    ("stress_cost_indicator_multipliers",    "Map(LowCardinality(String), Float64)"),
    ("stress_bonuses",                       "Map(LowCardinality(String), Float64)"),

    ("msearch_request_id",                   "String"),
    ("msearch_batch_size",                   "UInt16"),
    ("msearch_sub_query_index",              "UInt16"),

    ("cluster_name",                         "LowCardinality(String)"),
]


_RAW_ORDER_BY = ("cluster_name", "request_operation",
                 "identity_applicative_provider", "timestamp")

_SUMMARY_DIMENSIONS: list[tuple[str, str]] = [
    ("time_bucket",                    "DateTime"),
    ("request_template",               "String"),
    ("request_operation",              "LowCardinality(String)"),
    ("identity_applicative_provider",  "LowCardinality(String)"),
    ("request_target",                 "LowCardinality(String)"),
    ("cluster_name",                   "LowCardinality(String)"),
]

# (column_name, agg_function, input_type) — drives both summary table and MV.
_SUMMARY_AGGS: list[tuple[str, str, str]] = [
    ("count_state",                     "count",                       ""),
    ("sum_score_state",                 "sum",                         "Float32"),
    ("avg_score_state",                 "avg",                         "Float32"),
    ("avg_base_state",                  "avg",                         "Float32"),
    ("avg_multiplier_state",            "avg",                         "Float32"),
    ("avg_cost_indicator_count_state",  "avg",                         "UInt16"),
    ("avg_es_took_ms_state",            "avg",                         "Float32"),
    ("avg_gateway_took_ms_state",       "avg",                         "Float32"),
    ("avg_hits_state",                  "avg",                         "UInt64"),
    ("avg_shards_total_state",          "avg",                         "UInt32"),
    ("avg_docs_affected_state",         "avg",                         "UInt64"),
    ("avg_request_size_bytes_state",    "avg",                         "UInt32"),
    ("pct_es_took_ms_state",            "quantiles(0.5, 0.95, 0.99)",  "Float32"),
    ("pct_gateway_took_ms_state",       "quantiles(0.5, 0.95, 0.99)",  "Float32"),
    ("pct_score_state",                 "quantiles(0.5, 0.95, 0.99)",  "Float32"),
]

# Source columns each MV aggregation pulls from ``alo_raw``.
_MV_SOURCE: dict[str, str] = {
    "count_state":                    "",
    "sum_score_state":                "stress_score",
    "avg_score_state":                "stress_score",
    "avg_base_state":                 "stress_base",
    "avg_multiplier_state":           "stress_multiplier",
    "avg_cost_indicator_count_state": "stress_cost_indicator_count",
    "avg_es_took_ms_state":           "response_es_took_ms",
    "avg_gateway_took_ms_state":      "response_gateway_took_ms",
    "avg_hits_state":                 "response_hits",
    "avg_shards_total_state":         "response_shards_total",
    "avg_docs_affected_state":        "response_docs_affected",
    "avg_request_size_bytes_state":   "request_size_bytes",
    "pct_es_took_ms_state":           "response_es_took_ms",
    "pct_gateway_took_ms_state":      "response_gateway_took_ms",
    "pct_score_state":                "stress_score",
}


# ── DDL helpers ────────────────────────────────────────────────────────────

def _local_suffix(s: TableSettings, name: str) -> str:
    return f"{name}_local" if s.cluster_enabled else name


def _on_cluster(s: TableSettings) -> str:
    return f" ON CLUSTER '{s.cluster_name}'" if s.cluster_enabled else ""


def _replicated(s: TableSettings, engine: str, args: str = "") -> str:
    if not s.cluster_enabled:
        return engine if not args else f"{engine}({args})"
    path = "'/clickhouse/tables/{shard}/" + engine.lower() + "_PLACEHOLDER'"
    replica = "'{replica}'"
    inner = f"{path}, {replica}"
    if args:
        inner = f"{inner}, {args}"
    return f"Replicated{engine}({inner})"


def _format_columns(columns: Iterable[tuple[str, str]]) -> str:
    width = max(len(name) for name, _ in columns)
    return ",\n".join(f"    {name.ljust(width)}  {type_}" for name, type_ in columns)


def _summary_state_columns(s: TableSettings) -> list[tuple[str, str]]:
    cols: list[tuple[str, str]] = []
    for name, agg, input_type in _SUMMARY_AGGS:
        if agg == "count":
            cols.append((name, "AggregateFunction(count)"))
        elif agg.startswith("quantiles"):
            cols.append((name, f"AggregateFunction({agg}, {input_type})"))
        else:
            cols.append((name, f"AggregateFunction({agg}, {input_type})"))
    return cols


# ── DDL builders ───────────────────────────────────────────────────────────

def database_ddl(s: TableSettings) -> str:
    return f"CREATE DATABASE IF NOT EXISTS {s.database}{_on_cluster(s)}"


def raw_table_ddl(s: TableSettings) -> str:
    table = _local_suffix(s, "alo_raw")
    engine = _raw_engine(s, table)
    columns = _format_columns(_RAW_COLUMNS)
    order_by = ", ".join(_RAW_ORDER_BY)
    return (
        f"CREATE TABLE IF NOT EXISTS {s.database}.{table}{_on_cluster(s)}\n"
        f"(\n{columns}\n)\n"
        f"ENGINE = {engine}\n"
        f"PARTITION BY {s.raw_partition_by}\n"
        f"ORDER BY ({order_by})\n"
        f"TTL toDateTime(timestamp) + INTERVAL {s.raw_retention_days} DAY DELETE\n"
        f"SETTINGS index_granularity = 8192"
    )


def raw_distributed_ddl(s: TableSettings) -> str | None:
    if not s.cluster_enabled:
        return None
    return _distributed_ddl(s, "alo_raw")


def dead_letter_table_ddl(s: TableSettings) -> str:
    table = _local_suffix(s, "alo_dead_letter")
    engine = _dead_letter_engine(s, table)
    columns = _format_columns([
        ("timestamp",      "DateTime64(3, 'UTC') DEFAULT now64(3)"),
        ("cluster_name",   "LowCardinality(String)"),
        ("error",          "String"),
        ("raw",            "String CODEC(ZSTD(3))"),
        ("request_path",   "String"),
        ("request_method", "LowCardinality(String)"),
        ("request_body",   "String CODEC(ZSTD(3))"),
    ])
    return (
        f"CREATE TABLE IF NOT EXISTS {s.database}.{table}{_on_cluster(s)}\n"
        f"(\n{columns}\n)\n"
        f"ENGINE = {engine}\n"
        f"PARTITION BY toYYYYMMDD(timestamp)\n"
        f"ORDER BY (cluster_name, timestamp)\n"
        f"TTL toDateTime(timestamp) + INTERVAL {s.raw_retention_days} DAY DELETE"
    )


def dead_letter_distributed_ddl(s: TableSettings) -> str | None:
    if not s.cluster_enabled:
        return None
    return _distributed_ddl(s, "alo_dead_letter")


def summary_table_ddl(s: TableSettings) -> str:
    table = _local_suffix(s, "alo_summary")
    engine = _summary_engine(s, table)
    columns = _format_columns(_SUMMARY_DIMENSIONS + _summary_state_columns(s))
    order_by = ", ".join(name for name, _ in _SUMMARY_DIMENSIONS)
    return (
        f"CREATE TABLE IF NOT EXISTS {s.database}.{table}{_on_cluster(s)}\n"
        f"(\n{columns}\n)\n"
        f"ENGINE = {engine}\n"
        f"PARTITION BY {s.summary_partition_by}\n"
        f"ORDER BY ({order_by})\n"
        f"TTL toDateTime(time_bucket) + INTERVAL {s.summary_retention_days} DAY DELETE"
    )


def summary_distributed_ddl(s: TableSettings) -> str | None:
    if not s.cluster_enabled:
        return None
    return _distributed_ddl(s, "alo_summary")


def summary_mv_ddl(s: TableSettings) -> str:
    src = _local_suffix(s, "alo_raw")
    dest = _local_suffix(s, "alo_summary")
    select_parts: list[str] = [
        "toStartOfHour(timestamp) AS time_bucket",
        "request_template",
        "request_operation",
        "identity_applicative_provider",
        "request_target",
        "cluster_name",
    ]
    for name, agg, _ in _SUMMARY_AGGS:
        source_col = _MV_SOURCE[name]
        if agg == "count":
            select_parts.append(f"countState() AS {name}")
        elif agg.startswith("quantiles"):
            # quantiles(0.5, 0.95, 0.99) → quantilesState(0.5, 0.95, 0.99)(col)
            params = agg[len("quantiles"):]
            select_parts.append(f"quantilesState{params}({source_col}) AS {name}")
        else:
            select_parts.append(f"{agg}State({source_col}) AS {name}")

    select_sql = ",\n    ".join(select_parts)
    group_by = ", ".join(name for name, _ in _SUMMARY_DIMENSIONS)
    return (
        f"CREATE MATERIALIZED VIEW IF NOT EXISTS "
        f"{s.database}.alo_summary_mv{_on_cluster(s)}\n"
        f"TO {s.database}.{dest} AS\n"
        f"SELECT\n    {select_sql}\n"
        f"FROM {s.database}.{src}\n"
        f"WHERE request_operation != 'unknown'\n"
        f"GROUP BY {group_by}"
    )


# ── Engine selection ──────────────────────────────────────────────────────

def _raw_engine(s: TableSettings, table: str) -> str:
    if not s.cluster_enabled:
        return "MergeTree"
    path = f"'/clickhouse/tables/{{shard}}/{table}'"
    return f"ReplicatedMergeTree({path}, '{{replica}}')"


def _dead_letter_engine(s: TableSettings, table: str) -> str:
    return _raw_engine(s, table)


def _summary_engine(s: TableSettings, table: str) -> str:
    if not s.cluster_enabled:
        return "AggregatingMergeTree"
    path = f"'/clickhouse/tables/{{shard}}/{table}'"
    return f"ReplicatedAggregatingMergeTree({path}, '{{replica}}')"


def _distributed_ddl(s: TableSettings, base: str) -> str:
    return (
        f"CREATE TABLE IF NOT EXISTS {s.database}.{base}{_on_cluster(s)}\n"
        f"AS {s.database}.{base}_local\n"
        f"ENGINE = Distributed("
        f"'{s.cluster_name}', '{s.database}', '{base}_local', {s.sharding_key})"
    )


# ── Public DDL plan ───────────────────────────────────────────────────────

def all_ddl(s: TableSettings) -> list[tuple[str, str]]:
    """Return labelled DDL statements in execution order."""
    plan: list[tuple[str, str | None]] = [
        ("database",              database_ddl(s)),
        ("alo_raw_local",         raw_table_ddl(s)),
        ("alo_raw",               raw_distributed_ddl(s)),
        ("alo_dead_letter_local", dead_letter_table_ddl(s)),
        ("alo_dead_letter",       dead_letter_distributed_ddl(s)),
        ("alo_summary_local",     summary_table_ddl(s)),
        ("alo_summary",           summary_distributed_ddl(s)),
        ("alo_summary_mv",        summary_mv_ddl(s)),
    ]
    return [(label, ddl) for label, ddl in plan if ddl]
