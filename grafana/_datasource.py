"""Grafana datasource provisioning helpers."""

import os
import textwrap


def _read_cert(es_ca_cert: str) -> str:
    """Return PEM content — read from file if path, else treat as literal."""
    if es_ca_cert and os.path.isfile(es_ca_cert):
        with open(es_ca_cert, encoding="utf-8") as f:
            return f.read()
    return es_ca_cert

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DS_DIR = os.path.join(SCRIPT_DIR, "provisioning", "datasources")
DS_PATH = os.path.join(DS_DIR, "elasticsearch.yml")
PROM_DS_PATH = os.path.join(DS_DIR, "prometheus.yml")


def _ds_tls_block(es_insecure: bool, es_ca_cert: str) -> str:
    lines = []
    if es_insecure:
        lines.append("              tlsSkipVerify: true")
    if es_ca_cert:
        lines.append("              tlsAuthWithCACert: true")
    return ("\n" + "\n".join(lines)) if lines else ""


def _ds_secure_block(es_username: str, es_password: str, es_ca_cert: str) -> str:
    """Generate the secureJsonData block (auth password + CA cert PEM content)."""
    lines = []
    if es_username:
        lines.append(f"              basicAuthPassword: {es_password}")
    cert_pem = _read_cert(es_ca_cert)
    if cert_pem:
        indented = "\n".join(f"                {ln}" for ln in cert_pem.splitlines())
        lines.append(f"              tlsCACert: |\n{indented}")
    if not lines:
        return ""
    return "\n            secureJsonData:\n" + "\n".join(lines)


def _ds_auth_block(es_username: str) -> str:
    if not es_username:
        return ""
    return textwrap.dedent(f"""\

            basicAuth: true
            basicAuthUser: {es_username}""")


def _ds_entry(name: str, uid: str, url: str, database: str, is_default: bool,
              es_username: str, es_password: str,
              es_insecure: bool, es_ca_cert: str) -> str:
    tls = _ds_tls_block(es_insecure, es_ca_cert)
    auth = _ds_auth_block(es_username)
    secure = _ds_secure_block(es_username, es_password, es_ca_cert)
    return textwrap.dedent(f"""\
          - name: {name}
            type: elasticsearch
            uid: {uid}
            access: proxy
            url: {url}
            database: "{database}"
            isDefault: {"true" if is_default else "false"}{auth}{secure}
            jsonData:
              esVersion: "8.0.0"
              timeField: "@timestamp"
              logMessageField: ""
              logLevelField: ""
              maxConcurrentShardRequests: 5
              interval: ""{tls}
            editable: true
    """)


def generate_datasource_yaml(elasticsearch_url: str = "http://elasticsearch:9200",
                             index_pattern: str = "logs-alo.*-*,alo-summary",
                             es_username: str = "",
                             es_password: str = "",
                             es_insecure: bool = False,
                             es_ca_cert: str = "") -> str:
    main = _ds_entry(
        "Elasticsearch (ALO)", "alo-elasticsearch",
        elasticsearch_url, index_pattern, True,
        es_username, es_password, es_insecure, es_ca_cert,
    )
    summary = _ds_entry(
        "Elasticsearch (ALO Summary)", "alo-elasticsearch-summary",
        elasticsearch_url, "alo-summary", False,
        es_username, es_password, es_insecure, es_ca_cert,
    )
    content = textwrap.dedent("""\
        apiVersion: 1

        # Primary datasource queries raw + summary. While raw data exists it
        # outnumbers summary docs ~50:1 (<2% noise). After ILM deletes raw,
        # summary seamlessly provides avg metrics and percentiles at hourly
        # granularity.
        datasources:
    """) + main + summary
    os.makedirs(DS_DIR, exist_ok=True)
    with open(DS_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Generated: {DS_PATH}")
    return DS_PATH


def generate_prometheus_datasource_yaml(prometheus_url=""):
    """Write or remove the Prometheus datasource provisioning file.

    When ``prometheus_url`` is empty, any existing file is removed so
    re-runs without the env var leave a clean state. Mirrors the Helm
    chart's opt-in pattern (``grafana.prometheusUrl``).
    """
    if not prometheus_url:
        if os.path.exists(PROM_DS_PATH):
            os.remove(PROM_DS_PATH)
            print(f"  Removed: {PROM_DS_PATH} (PROMETHEUS_URL unset)")
        else:
            print("  Skipped: prometheus datasource (PROMETHEUS_URL unset)")
        return None

    content = textwrap.dedent(f"""\
        apiVersion: 1

        datasources:
          - name: Prometheus (ALO)
            type: prometheus
            uid: alo-prometheus
            access: proxy
            url: {prometheus_url}
            isDefault: false
            jsonData:
              httpMethod: POST
              timeInterval: "15s"
            editable: true
    """)
    os.makedirs(DS_DIR, exist_ok=True)
    with open(PROM_DS_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Generated: {PROM_DS_PATH}")
    return PROM_DS_PATH
