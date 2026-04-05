#!/usr/bin/env python3
"""
Set up the Applicative Load Observability stack:
  - Elasticsearch index template (mapping + settings)
  - Kibana data view and dashboards

By default, imports the pre-built dashboard.ndjson.
Use --rebuild to recreate everything from scratch via the API and re-export.

Usage:
    python kibana/setup.py                         # import dashboard.ndjson
    python kibana/setup.py --rebuild               # recreate via API + re-export
    python kibana/setup.py --kibana http://host:5601 --elasticsearch https://host:9200
    python kibana/setup.py --username elastic --password secret --es-ca-cert /path/to/ca.crt
    python kibana/setup.py --es-insecure --kibana-insecure   # skip TLS verification
"""

import argparse
import sys

from _client import (
    StackConfig,
    ensure_es_resources,
    wait_es,
    wait_kibana,
)
from _dashboards import (
    DASHBOARD_ID, CI_DASHBOARD_ID,
    USAGE_DASHBOARD_ID, do_import, do_rebuild,
)


def main() -> None:
    defaults = StackConfig()
    parser = argparse.ArgumentParser(
        description="Set up the ALO stack (ES template + Kibana dashboards)")
    parser.add_argument(
        "--kibana", default=defaults.kibana_url,
        help="Kibana URL (default: %(default)s)")
    parser.add_argument(
        "--elasticsearch", default=defaults.elasticsearch_url,
        help="Elasticsearch URL (default: %(default)s)")
    parser.add_argument(
        "--username", default=defaults.username,
        help="Elasticsearch/Kibana username (default: ES_USERNAME env)")
    parser.add_argument(
        "--password", default=defaults.password,
        help="Elasticsearch/Kibana password (default: ES_PASSWORD env)")
    parser.add_argument(
        "--es-ca-cert", default=defaults.es_ca_cert,
        help="CA certificate for Elasticsearch TLS (default: ES_CA_CERT env)")
    parser.add_argument(
        "--es-insecure", action="store_true", default=defaults.es_insecure,
        help="Skip Elasticsearch TLS verification")
    parser.add_argument(
        "--kibana-ca-cert", default=defaults.kibana_ca_cert,
        help="CA certificate for Kibana TLS (default: KIBANA_CA_CERT env)")
    parser.add_argument(
        "--kibana-insecure", action="store_true", default=defaults.kibana_insecure,
        help="Skip Kibana TLS verification")
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Recreate all objects via API and re-export dashboard.ndjson")
    args = parser.parse_args()

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

    print(f"\n  Kibana:        {cfg.kibana_url}")
    print(f"  Elasticsearch: {cfg.elasticsearch_url}\n")

    wait_es(cfg)
    wait_kibana(cfg)
    ensure_es_resources(cfg)

    if args.rebuild:
        print("  Mode: rebuild\n")
        ok = do_rebuild(cfg)
    else:
        print("  Mode: import\n")
        ok = do_import(cfg)

    if ok:
        print(f"\n  Main dashboard:            {cfg.kibana_url}/app/dashboards#/view/{DASHBOARD_ID}")
        print(f"  Cost indicators dashboard: {cfg.kibana_url}/app/dashboards#/view/{CI_DASHBOARD_ID}")
        print(f"  Cluster usage dashboard:   {cfg.kibana_url}/app/dashboards#/view/{USAGE_DASHBOARD_ID}\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
