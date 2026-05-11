#!/usr/bin/env python3
"""
Set up the Applicative Load Observability stack.

ES resources (ILM, mappings, index templates, summary transform) and Kibana
saved objects (data view, saved searches, dashboards) can each be toggled
independently via --<section> / --no-<section> flags. All sections default to
enabled, so running with no flags applies everything.

Usage:
    python kibana/setup.py                             # apply everything
    python kibana/setup.py --rebuild                   # rebuild Kibana objects via API + re-export
    python kibana/setup.py --no-dashboards             # skip Kibana dashboard import
    python kibana/setup.py --no-data-view --no-saved-searches --no-dashboards  # ES only
    python kibana/setup.py --no-ilm --no-component-template --no-index-templates \
                           --no-summary-template --no-transform  # Kibana only
"""

import argparse
import sys

from _client import (
    StackConfig,
    ensure_component_template,
    ensure_ilm,
    ensure_index_templates,
    ensure_summary_template,
    ensure_summary_transform,
    wait_es,
    wait_kibana,
)
from _dashboards import (
    DASHBOARD_ID, CI_DASHBOARD_ID,
    USAGE_DASHBOARD_ID, do_import, do_rebuild,
)
from _index_template import IndexSettings, apply_index_settings


def _add_section_flag(parser: argparse.ArgumentParser, name: str, help_text: str) -> None:
    parser.add_argument(
        f"--{name}", action=argparse.BooleanOptionalAction, default=True,
        help=help_text)


def main() -> None:
    defaults = StackConfig()
    parser = argparse.ArgumentParser(
        description="Set up the ALO stack (ES resources + Kibana dashboards)")

    conn = parser.add_argument_group("connection")
    conn.add_argument(
        "--kibana", default=defaults.kibana_url,
        help="Kibana URL (default: %(default)s)")
    conn.add_argument(
        "--elasticsearch", default=defaults.elasticsearch_url,
        help="Elasticsearch URL (default: %(default)s)")
    conn.add_argument(
        "--username", default=defaults.username,
        help="Elasticsearch/Kibana username (default: ES_USERNAME env)")
    conn.add_argument(
        "--password", default=defaults.password,
        help="Elasticsearch/Kibana password (default: ES_PASSWORD env)")
    conn.add_argument(
        "--es-ca-cert", default=defaults.es_ca_cert,
        help="CA certificate for Elasticsearch TLS (default: ES_CA_CERT env)")
    conn.add_argument(
        "--es-insecure", action="store_true", default=defaults.es_insecure,
        help="Skip Elasticsearch TLS verification")
    conn.add_argument(
        "--kibana-ca-cert", default=defaults.kibana_ca_cert,
        help="CA certificate for Kibana TLS (default: KIBANA_CA_CERT env)")
    conn.add_argument(
        "--kibana-insecure", action="store_true", default=defaults.kibana_insecure,
        help="Skip Kibana TLS verification")

    es_sec = parser.add_argument_group("ES resource sections (default: all enabled)")
    _add_section_flag(es_sec, "ilm", "PUT ILM policies")
    _add_section_flag(es_sec, "component-template", "PUT component template (field mappings)")
    _add_section_flag(es_sec, "index-templates", "PUT composable index templates")
    _add_section_flag(es_sec, "summary-template", "PUT summary index template")
    _add_section_flag(es_sec, "transform", "Recreate and start summary transform")

    kb_sec = parser.add_argument_group("Kibana object sections (default: all enabled)")
    _add_section_flag(kb_sec, "data-view", "Create alo-data-view saved object")
    _add_section_flag(kb_sec, "saved-searches", "Create saved searches")
    _add_section_flag(kb_sec, "dashboards", "Import/rebuild ALO dashboards")
    kb_sec.add_argument(
        "--rebuild", action="store_true",
        help="Rebuild dashboards via API and re-export ndjson (requires --dashboards)")

    idx = IndexSettings()
    perf = parser.add_argument_group("index performance settings")
    perf.add_argument(
        "--shards", type=int, default=idx.shards,
        help="Number of primary shards (default: %(default)s)")
    perf.add_argument(
        "--replicas", type=int, default=idx.replicas,
        help="Number of replicas (default: %(default)s)")
    perf.add_argument(
        "--refresh-interval", default=idx.refresh_interval,
        help="Index refresh interval (default: %(default)s)")
    perf.add_argument(
        "--raw-retention", default=idx.raw_retention,
        help="Raw data retention before ILM delete (default: %(default)s)")
    perf.add_argument(
        "--rollover-max-age", default=idx.rollover_max_age,
        help="Max index age before rollover (default: %(default)s)")
    perf.add_argument(
        "--summary-retention", default=idx.summary_retention,
        help="Summary transform retention (default: %(default)s)")
    args = parser.parse_args()

    apply_index_settings(IndexSettings(
        shards=args.shards,
        replicas=args.replicas,
        refresh_interval=args.refresh_interval,
        raw_retention=args.raw_retention,
        rollover_max_age=args.rollover_max_age,
        summary_retention=args.summary_retention,
    ))

    cfg = StackConfig(
        kibana_url=args.kibana,
        elasticsearch_url=args.elasticsearch,
        username=args.username,
        password=args.password,
        es_ca_cert=args.es_ca_cert,
        es_insecure=args.es_insecure,
        kibana_ca_cert=args.kibana_ca_cert,
        kibana_insecure=args.kibana_insecure,
    )

    run_es = any([args.ilm, args.component_template, args.index_templates,
                  args.summary_template, args.transform])
    run_kibana = any([args.data_view, args.saved_searches, args.dashboards])

    print(f"\n  Elasticsearch: {cfg.elasticsearch_url}")
    if run_kibana:
        print(f"  Kibana:        {cfg.kibana_url}")
    print()

    all_ok = True

    if run_es:
        wait_es(cfg)
        if args.ilm:
            all_ok &= ensure_ilm(cfg)
        if args.component_template:
            all_ok &= ensure_component_template(cfg)
        if args.index_templates:
            all_ok &= ensure_index_templates(cfg)
        if args.summary_template:
            all_ok &= ensure_summary_template(cfg)
        if args.transform:
            all_ok &= ensure_summary_transform(cfg)

    if run_kibana:
        if not run_es:
            wait_es(cfg)
        wait_kibana(cfg)
        if args.rebuild:
            print("  Mode: rebuild\n")
            ok = do_rebuild(cfg,
                            data_view=args.data_view,
                            saved_searches=args.saved_searches,
                            dashboards=args.dashboards)
        else:
            print("  Mode: import\n")
            ok = do_import(cfg, dashboards=args.dashboards)
        all_ok &= ok

        if ok and args.dashboards:
            print(f"\n  Main dashboard:            {cfg.kibana_url}/app/dashboards#/view/{DASHBOARD_ID}")
            print(f"  Cost indicators dashboard: {cfg.kibana_url}/app/dashboards#/view/{CI_DASHBOARD_ID}")
            print(f"  Cluster usage dashboard:   {cfg.kibana_url}/app/dashboards#/view/{USAGE_DASHBOARD_ID}\n")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
