# Applicative Load Observability (ALO)

A transparent observability layer for Elasticsearch clusters. ALO sits as a gateway in
front of your cluster, intercepts every request, and produces **stress-scored
observability records** — enabling you to identify which applications, queries, and
templates cause the most resource contention.

## Architecture

```
Clients ──→ Gateway (OpenResty) ──→ Elasticsearch (monitored, untouched)
                 │ (async, fire-and-forget)
                 ▼
            Logstash ──→ Analyzer (FastAPI) ──→ observability records
                                                       │
                                                       ▼
                                              ClickHouse (alo_raw → alo_summary)
                                                       │
                                                       ▼
                                                    Grafana

        Optional: Prometheus scrapes gateway / analyzer / logstash / ClickHouse
                  → the "Stack Health" dashboard in the same Grafana
```

The gateway proxies all traffic transparently. After each response, it asynchronously
notifies Logstash, which forwards the payload to the analyzer. The analyzer computes a
**stress score**, flags **cost indicators** (scripts, wildcards, deep aggregations, …),
and returns a flat record that Logstash inserts into ClickHouse. Grafana reads from there.

ALO never writes to the monitored Elasticsearch — ClickHouse is the analytics sink.

## Quick Start

```bash
# Point ALO at the Elasticsearch cluster you want to monitor
export ELASTICSEARCH_HOST=my-es.internal:9200

# Start the stack (gateway + logstash + analyzer + ClickHouse + Grafana)
docker compose up -d

# Point your application at the gateway instead of ES directly
# Default: http://localhost:9200 (same port as ES)
```

Compose does **not** run Elasticsearch — bring your own cluster and set
`ELASTICSEARCH_HOST`. See `.env.example` for every tunable.

Once traffic flows, open **Grafana** at http://localhost:3000 (admin/admin) — the
dashboards and the ClickHouse datasource are provisioned automatically.

For the optional monitoring stack (Prometheus + nginx/logstash exporters):

```bash
docker compose --profile prometheus up -d
```

## Key Concepts

**Stress Score** — A synthetic metric quantifying how "heavy" each operation is. Combines
normalized latency, hits, shards, and docs affected with operation-specific weights, plus
logarithmic bonuses for expensive clause counts. See [ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the formulas.

**Cost Indicators** — Eleven flags for expensive patterns: scripts, runtime mappings,
wildcards, nested, fuzzy, geo, kNN, excessive bool clauses, large terms lists, deep
aggregations, and unbounded hit counts. Each applies a multiplier (1.2×–1.5×) to the
stress score, stacking multiplicatively.

**Templates** — Scrubbed query structures with literal values replaced by `?`. Groups
identical logical queries for aggregation regardless of parameter values.

**Custom Labels** — Attach metadata to requests via `x-alo-*` headers (e.g.
`x-alo-team: payments`). Stored in the `identity_labels` Map column
(`identity_labels['team']`). Use hyphens, not underscores — nginx drops underscore
headers by default.

**`_msearch` fan-out** — a multi-search is recorded as one row per sub-query, correlated
by `msearch_request_id`, so template attribution stays meaningful.

## Dashboards

Five dashboards are provisioned automatically in Grafana:

| Dashboard | UID | Purpose |
|-----------|-----|---------|
| **Stress Analysis** | `alo-main` | Overview pies, top templates table, stress trends, volume, response times |
| **Stress Analysis (Hebrew)** | `alo-main-he` | Hebrew-localized version of the above |
| **Cost Indicators** | `alo-cost-indicators` | KPIs, score component breakdown, clause count trends, indicator frequency |
| **Cluster Usage** | `alo-usage` | Request rates, latency percentiles, error rates, data volume, top users |
| **Stack Health** | `alo-health` | ALO's own health — gateway/analyzer/logstash metrics (Prometheus) + dead-letter volume (ClickHouse) |

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | Pipeline design, stress formulas, record schema, ClickHouse schema, env vars |
| [Rationale](docs/RATIONALE.md) | Why the gateway, pipeline, and sink are built the way they are, and what was considered instead |
| [TODO](docs/TODO.md) | Deferred scoring, parsing, and dashboard ideas — pruned and ranked |
| [Helm Deployment](docs/HELM.md) | Kubernetes/OpenShift deployment, ClickHouse + Grafana configuration |
| [Dashboard Cheat Sheet](grafana/cheat_sheet.md) | How to read the dashboards and what to look for |
| [Stress Tool](tools/stress/README.md) | Load generation tool with 11 workload profiles |
| [Benchmarking](tools/stress/benchmarking.md) | Performance testing methodology and resource sizing |
| [Tests](tests/help.md) | Unit, integration, and challenge suites |
| [Product Spec](docs/PRODUCT_SPEC.md) | Original product vision and analysis framework |
| [Contributing](CONTRIBUTING.md) | Branching, code standards, release process |
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
```

### Images

Five images are published from this repo — `analyzer`, `logstash`, `gateway`,
`ch-setup`, `grafana-setup` — all built and pushed by the release workflow on a `v*` tag
push (`.github/workflows/release.yml`). Don't build and push them by hand:

```bash
git tag v2.1.20 && git push origin v2.1.20   # → builds and pushes all five images
```

They land as `oracle1012/applicative-load-observability:<component>-<version>`.
