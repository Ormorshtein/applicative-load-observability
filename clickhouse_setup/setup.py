#!/usr/bin/env python3
"""
Bootstrap the ClickHouse analytics sink for the ALO stack.

Creates (in order, all idempotent):

1.  Database ``alo`` (skip with ``--no-database``).
2.  ``alo_raw`` raw events table (and ``alo_raw_local`` + Distributed front
    when ``--cluster`` is set).
3.  ``alo_dead_letter`` for Logstash dead-letter routing.
4.  ``alo_summary`` AggregatingMergeTree for hourly pre-aggregations.
5.  ``alo_summary_mv`` materialized view that incrementally aggregates raw
    rows into the summary table.

Usage::

    python clickhouse_setup/setup.py
    python clickhouse_setup/setup.py --clickhouse-url https://ch:8443 \\
        --user alo --password xxx --ca-cert /etc/ssl/ch/ca.crt
    python clickhouse_setup/setup.py --cluster alo_cluster   # distributed mode
"""

import argparse
import sys

from ._client import ClickHouseConfig, execute_or_die, wait_clickhouse
from ._schema import TableSettings, _RAW_COLUMN_ADDITIONS, all_ddl


def _build_arg_parser(cfg: ClickHouseConfig, settings: TableSettings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Set up the ClickHouse analytics sink for ALO")

    conn = parser.add_argument_group("connection")
    conn.add_argument("--clickhouse-url", default=cfg.url,
                      help="ClickHouse HTTP URL (default: %(default)s)")
    conn.add_argument("--user", default=cfg.user,
                      help="ClickHouse user (default: %(default)s)")
    conn.add_argument("--password", default=cfg.password,
                      help="ClickHouse password (default: CLICKHOUSE_PASSWORD env)")
    conn.add_argument("--database", default=settings.database,
                      help="Database name (default: %(default)s)")
    conn.add_argument("--ca-cert", default=cfg.ca_cert,
                      help="CA certificate for TLS (default: CLICKHOUSE_CA_CERT env)")
    conn.add_argument("--insecure", action="store_true", default=cfg.insecure,
                      help="Skip TLS verification")
    conn.add_argument("--cluster", default=cfg.cluster,
                      help="Cluster name for distributed mode (empty = single-node)")

    sections = parser.add_argument_group("sections (toggle off with --no-*)")
    _add_bool_flag(sections, "create-database",   True,  "create database")
    _add_bool_flag(sections, "raw-table",         True,  "create alo_raw")
    _add_bool_flag(sections, "dead-letter-table", True,  "create alo_dead_letter")
    _add_bool_flag(sections, "summary-table",     True,  "create alo_summary")
    _add_bool_flag(sections, "materialized-view", True,  "create alo_summary_mv")

    retention = parser.add_argument_group("retention / partitioning")
    retention.add_argument("--raw-retention-days", type=int,
                           default=settings.raw_retention_days,
                           help="TTL on alo_raw (default: %(default)s)")
    retention.add_argument("--summary-retention-days", type=int,
                           default=settings.summary_retention_days,
                           help="TTL on alo_summary (default: %(default)s)")
    retention.add_argument("--raw-ttl", default="",
                           help="Full TTL clause for alo_raw + alo_dead_letter "
                                "(overrides --raw-retention-days). Example: "
                                "\"timestamp + INTERVAL 1 DAY TO VOLUME 'warm', "
                                "timestamp + INTERVAL 7 DAY DELETE\"")
    retention.add_argument("--summary-ttl", default="",
                           help="Full TTL clause for alo_summary "
                                "(overrides --summary-retention-days)")

    tuning = parser.add_argument_group("table tuning")
    tuning.add_argument("--raw-settings", default="",
                        help="Extra SETTINGS for alo_raw as k=v,k=v "
                             "(e.g. storage_policy=hot_warm_cold,index_granularity=4096). "
                             "Merged with the default index_granularity = 8192.")
    tuning.add_argument("--summary-settings", default="",
                        help="Extra SETTINGS for alo_summary as k=v,k=v")
    tuning.add_argument("--sharding-key", default=settings.sharding_key,
                        help="Sharding key for Distributed engine (default: %(default)s)")
    return parser


def _add_bool_flag(group, name: str, default: bool, help_text: str) -> None:
    dest = name.replace("-", "_")
    group.add_argument(f"--{name}", dest=dest, action="store_true",
                       default=default, help=f"{help_text} (default: on)")
    group.add_argument(f"--no-{name}", dest=dest, action="store_false",
                       help=f"skip: {help_text}")


def _parse_kv_pairs(raw: str) -> dict[str, str]:
    """Parse ``k1=v1,k2=v2`` into a dict. Empty input → empty dict."""
    if not raw.strip():
        return {}
    pairs: dict[str, str] = {}
    for chunk in raw.split(","):
        if "=" not in chunk:
            raise ValueError(f"expected k=v, got {chunk!r}")
        key, _, value = chunk.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs


def _settings_from_args(args: argparse.Namespace) -> TableSettings:
    return TableSettings(
        database=               args.database,
        raw_retention_days=     args.raw_retention_days,
        summary_retention_days= args.summary_retention_days,
        cluster_enabled=        bool(args.cluster),
        cluster_name=           args.cluster or "alo_cluster",
        sharding_key=           args.sharding_key,
        raw_ttl_clause=         args.raw_ttl,
        summary_ttl_clause=     args.summary_ttl,
        raw_extra_settings=     _parse_kv_pairs(args.raw_settings),
        summary_extra_settings= _parse_kv_pairs(args.summary_settings),
    )


def _config_from_args(args: argparse.Namespace) -> ClickHouseConfig:
    return ClickHouseConfig(
        url=      args.clickhouse_url,
        user=     args.user,
        password= args.password,
        database= args.database,
        ca_cert=  args.ca_cert,
        insecure= args.insecure,
        cluster=  args.cluster,
    )


_SECTION_LABELS_TO_FLAG: dict[str, str] = {
    "database":              "create_database",
    "alo_raw_local":         "raw_table",
    "alo_raw":               "raw_table",
    "alo_dead_letter_local": "dead_letter_table",
    "alo_dead_letter":       "dead_letter_table",
    "alo_summary_local":     "summary_table",
    "alo_summary":           "summary_table",
    "alo_summary_mv":        "materialized_view",
    **{f"alter_alo_raw_{label}": "raw_table" for label, *_ in _RAW_COLUMN_ADDITIONS},
}


def main() -> None:
    cfg_defaults = ClickHouseConfig()
    settings_defaults = TableSettings()
    args = _build_arg_parser(cfg_defaults, settings_defaults).parse_args()

    cfg = _config_from_args(args)
    settings = _settings_from_args(args)

    print(f"\n  ClickHouse: {cfg.url}")
    print(f"  Database:   {settings.database}")
    if settings.cluster_enabled:
        print(f"  Cluster:    {settings.cluster_name} (distributed mode)")
    else:
        print("  Cluster:    single-node")
    print()

    wait_clickhouse(cfg)

    plan = all_ddl(settings)
    all_ok = True
    for label, ddl in plan:
        flag = _SECTION_LABELS_TO_FLAG[label]
        if not getattr(args, flag):
            print(f"  SKIP: {label}")
            continue
        use_db = label != "database"
        all_ok &= execute_or_die(cfg, label, ddl, use_database=use_db)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
