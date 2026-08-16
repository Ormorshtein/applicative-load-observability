"""Unit tests for grafana/_datasource.py — ClickHouse datasource YAML builder."""

import os

import pytest

from grafana import _datasource
from grafana._datasource import generate_datasource_yaml


def _field(path: str, name: str) -> str | None:
    """Pull a scalar ``name: value`` field out of the generated YAML without
    adding a PyYAML dependency just for tests — the file is simple enough
    that a line scan is exact."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith(f"{name}:"):
                return stripped.split(":", 1)[1].strip()
    return None


@pytest.fixture(autouse=True)
def isolate_generated_file(tmp_path, monkeypatch):
    """generate_datasource_yaml() always writes to a fixed repo path — redirect
    it to a tmp dir so tests don't mutate the committed provisioning file."""
    monkeypatch.setattr(_datasource, "DS_DIR", str(tmp_path))
    monkeypatch.setattr(_datasource, "DS_PATH", os.path.join(str(tmp_path), "clickhouse.yml"))


class TestGenerateDatasourceYaml:
    def test_default_is_native_9000(self):
        path = generate_datasource_yaml()
        assert _field(path, "protocol") == "native"
        assert _field(path, "port") == "9000"

    def test_explicit_http_protocol_and_port(self):
        path = generate_datasource_yaml(clickhouse_url="http://clickhouse:80",
                                        protocol="http", port=80)
        assert _field(path, "protocol") == "http"
        assert _field(path, "port") == "80"

    def test_native_port_zero_is_backward_compatible_http_alias(self):
        path = generate_datasource_yaml(native_port=0)
        assert _field(path, "protocol") == "http"
        assert _field(path, "port") == "8123"

    def test_path_only_emitted_when_set(self):
        path = generate_datasource_yaml(protocol="http", port=80, path="/ch")
        assert _field(path, "path") == "/ch"

        path = generate_datasource_yaml()
        assert _field(path, "path") is None

    def test_secure_override(self):
        path = generate_datasource_yaml(clickhouse_url="http://clickhouse:8123",
                                        secure=True)
        assert _field(path, "secure") == "true"
