"""Grafana datasource provisioning helpers (ClickHouse)."""

import os
import textwrap
from urllib.parse import urlparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DS_DIR = os.path.join(SCRIPT_DIR, "provisioning", "datasources")
DS_PATH = os.path.join(DS_DIR, "clickhouse.yml")
PROM_DS_PATH = os.path.join(DS_DIR, "prometheus.yml")


def _read_cert(ch_ca_cert: str) -> str:
    """Return PEM content — read from file if path, else treat as literal."""
    if ch_ca_cert and os.path.isfile(ch_ca_cert):
        with open(ch_ca_cert, encoding="utf-8") as f:
            return f.read()
    return ch_ca_cert


def _parse_host(url: str) -> tuple[str, int, bool]:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = parsed.hostname or "clickhouse"
    secure = parsed.scheme == "https"
    port = parsed.port or (8443 if secure else 8123)
    return host, port, secure


def generate_datasource_yaml(clickhouse_url: str = "http://clickhouse:8123",
                             database: str = "alo",
                             native_port: int = 9000,
                             username: str = "default",
                             password: str = "",
                             insecure_skip_verify: bool = False,
                             ch_ca_cert: str = "",
                             protocol: str = "",
                             port: int = 0,
                             path: str = "",
                             secure: bool | None = None) -> str:
    """Write the ClickHouse datasource provisioning YAML.

    ``protocol``/``port``/``secure`` are the primary controls. ``native_port``
    is kept as a backward-compatible alias: ``native_port=0`` (or explicit
    ``protocol="http"``) selects HTTP; any nonzero ``native_port`` with no
    explicit ``protocol`` selects native on that port.
    """
    host, http_port, url_secure = _parse_host(clickhouse_url)
    if not protocol:
        protocol = "native" if native_port else "http"
    if not port:
        port = (native_port if protocol == "native" else 0) or (
            http_port if protocol == "http" else native_port)
    if secure is None:
        secure = url_secure
    path_line = f"\n              path: {path}" if path else ""
    cert_pem = _read_cert(ch_ca_cert)
    tls_auth = f"\n              tlsAuthWithCACert: true" if cert_pem else ""
    if cert_pem:
        indented = "\n".join(f"                {ln}" for ln in cert_pem.splitlines())
        secure_extra = f"\n              tlsCACert: |\n{indented}"
    else:
        secure_extra = ""
    content = textwrap.dedent(f"""\
        apiVersion: 1

        # Single ClickHouse datasource serves both raw and summary tables.
        # Panels select the right table in their SQL.
        datasources:
          - name: ClickHouse (ALO)
            type: grafana-clickhouse-datasource
            uid: alo-clickhouse
            access: proxy
            isDefault: true
            jsonData:
              host: {host}
              port: {port}
              protocol: {protocol}
              secure: {str(secure).lower()}
              tlsSkipVerify: {str(insecure_skip_verify).lower()}{path_line}{tls_auth}
              username: "{username}"
              defaultDatabase: {database}
            secureJsonData:
              password: "{password}"{secure_extra}
            editable: true
    """)
    os.makedirs(DS_DIR, exist_ok=True)
    with open(DS_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Generated: {DS_PATH}")
    return DS_PATH


def generate_prometheus_datasource_yaml(prometheus_url: str = "") -> str | None:
    """Write or remove the Prometheus datasource provisioning file.

    Empty URL ΓåÆ remove any existing file (mirrors ``grafana.prometheusUrl``
    opt-in semantics in Helm).
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
