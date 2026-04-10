# Applicative Load Observability (ALO)

A transparent observability layer for Elasticsearch clusters. ALO sits as a gateway in front of your cluster, intercepts every request, and produces **stress-scored observability records** — enabling you to identify which applications, queries, and templates cause the most resource contention.

## Architecture

```
Clients ──→ Gateway (OpenResty) ──→ Elasticsearch
                 │ (async, fire-and-forget)
                 ▼
            Logstash ──→ Analyzer (FastAPI) ──→ Observability Records
                                                       │
                                                       ▼
                                              ES Data Streams
                                                       │
                                               ┌───────┴───────┐
                                               ▼               ▼
                                            Kibana          Grafana
```

The gateway proxies all traffic transparently. After each response, it asynchronously notifies Logstash, which forwards the payload to the analyzer. The analyzer computes a **stress score**, identifies **cost indicators** (scripts, wildcards, deep aggregations, etc.), and writes the observability record into Elasticsearch data streams. Dashboards in Kibana or Grafana visualize the results.

## Quick Start

```bash
# Start the full stack (ES 8.13 + gateway + logstash + analyzer + Kibana + Grafana)
docker compose up -d

# Point your application at the gateway instead of ES directly
# Default: http://localhost:9200 (same port as ES)
```

Once traffic flows, open:
- **Kibana**: http://localhost:5601 (ALO dashboards auto-provisioned)
- **Grafana**: http://localhost:3000 (admin/admin)

## Key Concepts

**Stress Score** — A synthetic metric quantifying how "heavy" each operation is. Combines normalized latency, hits, shards, and docs affected with operation-specific weights. See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for formulas.

**Cost Indicators** — Flags on queries that use expensive patterns: scripts, runtime mappings, wildcards, deep aggregations, fuzzy, kNN, etc. Each fires a multiplier (1.2x-1.5x) on the stress score, stacking multiplicatively.

**Templates** — Scrubbed query structures with literal values replaced by `?`. Groups identical logical queries for aggregation regardless of parameter values.

**Custom Labels** — Attach metadata to requests via `x-alo-*` headers (e.g., `x-alo-team: payments`). Stored as `labels.*` fields for dashboard filtering.

## Dashboards

Three dashboards are provisioned automatically in both Kibana and Grafana:

| Dashboard | Purpose |
|-----------|---------|
| **Stress Analysis** | Overview pies, top templates table, stress trends, volume, response times |
| **Cost Indicators** | KPIs, score component breakdown, clause count trends, indicator frequency |
| **Cluster Usage** | Request rates, latency percentiles, error rates, data volume, top users |

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | Pipeline design, stress formulas, record schema, env vars |
| [Helm Deployment](docs/HELM.md) | Kubernetes/OpenShift deployment, Grafana setup |
| [Stress Tool](tools/stress/README.md) | Load generation tool with 11 workload profiles |
| [Benchmarking](tools/stress/benchmarking.md) | Performance testing methodology and resource sizing |
| [Product Spec](docs/PRODUCT_SPEC.md) | Original product vision and analysis framework |
| [Changelog](CHANGELOG.md) | Release history |

## Developer Quickstart

```bash
# Install dependencies
uv pip install -e ".[dev]"

# Lint & format
ruff check .
ruff format .

# Type check
mypy analyzer/

# Run tests
pytest                           # unit tests (tests/unit/)
pytest --cov=analyzer            # with coverage
pytest -n auto                   # parallel via pytest-xdist

# Pre-commit hooks
pip install pre-commit
pre-commit install

# Build all Docker images
docker build -t oracle1012/applicative-load-observability:analyzer-1.18.0 -f analyzer/Dockerfile .
docker build -t oracle1012/applicative-load-observability:logstash-1.18.0 -f logstash/Dockerfile .
docker build -t oracle1012/applicative-load-observability:gateway-1.18.0 -f gateway/Dockerfile gateway/
docker build -t oracle1012/applicative-load-observability:kibana-setup-1.18.0 -f kibana/Dockerfile kibana/
docker build -t oracle1012/applicative-load-observability:grafana-setup-1.18.0 -f grafana/Dockerfile grafana/
docker build -t oracle1012/applicative-load-observability:stress-1.18.0 -f tools/stress/Dockerfile .
```
