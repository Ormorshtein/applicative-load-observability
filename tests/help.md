# Tests

```
tests/
├── conftest.py                        # shared pytest config (adds project root to sys.path)
├── help.md                            # this file
├── unit/                              # fast, offline unit tests (pytest)
│   ├── analyzer/
│   │   ├── test_parser.py             # header, path, body, response extraction
│   │   ├── test_clause_counting.py    # clause counting + aggregation depth
│   │   ├── test_cost_indicators.py    # cost indicator evaluation + compounding
│   │   ├── test_stress_formulas.py    # normalize + calc_stress formulas
│   │   ├── test_record_builder.py     # record assembly, raw field extraction
│   │   ├── test_baselines.py          # dynamic baseline refresh logic
│   │   ├── test_decompression.py      # gzip / zlib / base64 body recovery
│   │   └── test_main.py               # FastAPI /analyze, /analyze/bulk, /health
│   ├── clickhouse_setup/
│   │   └── test_schema.py             # DDL generation, TTL, cluster mode, migrations
│   ├── grafana/
│   │   ├── test_dashboard_variables.py  # variable queries, time-range scoping
│   │   └── test_datasource.py           # datasource config (protocol/port/TLS)
│   ├── challenges/
│   │   └── test_infra.py              # DocIdTracker, HealthMonitor, progress bar
│   └── shared/
│       └── test_latency_tracker.py    # LatencyTracker base, percentile math
├── integration/                       # live tests (require a running stack)
│   ├── gateway_resilience.py          # gateway overhead, data integrity, scaling
│   ├── _resilience.py                 # timed_request, 3 test runners
│   ├── verify_grafana_dashboards.py   # Playwright dashboard verification
│   ├── _grafana_debug.py              # Playwright scroll-container helper
│   └── helpers.py                     # rand_*, Stats, LatencyTracker, http_request
└── challenges/                        # interactive load challenges (14 total)
    ├── _challenge_runner.py           # unified runner for all challenges
    ├── _challenge_infra.py            # DocIdTracker, HealthMonitor, worker
    └── challenge_*.py                 # thin entry points
```

`pyproject.toml` sets `testpaths = ["tests/unit"]`, so a bare `pytest` collects only the
unit suite. Integration scripts and challenges are standalone programs, run directly.

---

## Unit tests (`tests/unit/`)

Pure-Python, no network, no Docker — runs in about a second.

```bash
# Everything
pytest

# One component
pytest tests/unit/analyzer/ -v

# One module / class / test
pytest tests/unit/analyzer/test_clause_counting.py -v
pytest tests/unit/analyzer/test_stress_formulas.py::TestCalcStress::test_search_at_baseline -v

# Parallel, or with coverage
pytest -n auto
pytest --cov=analyzer --cov-report=term-missing
```

`-m "not slow"` skips tests that wait on cache TTLs.

### What is covered

| Source | Test file | Key areas |
|--------|-----------|-----------|
| `analyzer/parser/` | `test_parser.py` | Basic-auth username decode, applicative_provider fallback chain (x-app-name → user-agent; x-opaque-id intentionally ignored), `x-alo-*` label extraction, target/operation path parsing, size defaults, template scrubbing, hits/shards/docs_affected/es_took_ms extraction, bulk shard deduplication |
| `analyzer/stress/_clause_counting.py` | `test_clause_counting.py` | `count_clauses()` for every clause type (bool, wildcard/regexp/prefix, fuzzy, nested, knn, script, terms, geo_*, runtime_mappings, aggs at all nesting levels) |
| `analyzer/stress/_cost_indicators.py` | `test_cost_indicators.py` | `evaluate_cost_indicators()` for all 11 indicators — presence, threshold boundaries, `unbound_hits`, multiplicative compounding |
| `analyzer/stress/_formulas.py` | `test_stress_formulas.py` | `normalize()`, `calc_stress()` across the `_STRESS_DISPATCH` table (14 operation keys → 5 formula classes), multiplier application vs `_NO_MULTIPLIER_OPS`, continuous bonuses, unbounded score |
| `analyzer/record_builder/` | `test_record_builder.py` | `_parse_json_field`, `extract_raw_fields` (full/empty/malformed payloads), `build_record` (flat column layout, size inclusion/exclusion, template, timestamp format, stress rounding, bulk shard aggregation), `_msearch` fan-out envelope, body truncation, `partial_error_record` |
| `analyzer/_decompression.py` | `test_decompression.py` | `gzip+b64:` prefix path, latin-1 byte recovery, gzip/zlib magic sniffing, graceful fallback |
| `analyzer/_baselines.py` | `test_baselines.py` | Cache TTL, ClickHouse query result parsing, fallback when CH is unreachable |
| `analyzer/main.py`, `_routes.py` | `test_main.py` | `/health`, `/analyze` happy path (all operation types), `/analyze/bulk` batching and per-item failures, error handling (unparseable body, empty payload, malformed request/response — all return 200) |
| `clickhouse_setup/_schema.py` | `test_schema.py` | Raw/summary/dead-letter DDL, MV definition, TTL clauses and overrides, cluster (Replicated + Distributed) mode, column + index migrations |
| `grafana/` | `test_dashboard_variables.py`, `test_datasource.py` | Variable option queries (time-range scoping, GROUP BY bound, option limit), datasource protocol/port/path/TLS resolution |
| `shared/_stats.py` | `test_latency_tracker.py` | LatencyTracker base, percentile math |

### Record structure

The analyzer emits a **flat, snake_case** object whose keys are `alo_raw` columns — not a
nested document:

```
timestamp, cluster_name
identity_{username, applicative_provider, user_agent, client_host, labels}
request_{method, path, operation, target, template, body, body_truncated,
         size_bytes, size, geo_vertex_count, bulk_doc_count}
response_{status, es_took_ms, gateway_took_ms, hits, shards_total, docs_affected, size_bytes}
clause_counts_{bool, bool_must, …, script}                    # 16 counts
cost_indicators_{has_script, …, unbound_hits}                 # 11 flags, 0/1
stress_{score, base, multiplier, cost_indicator_count, cost_indicator_names,
        cost_indicator_multipliers, bonuses}
stress_components_{took, shards, hits, docs_affected, bulk_doc_count, bonus}
msearch_{request_id, batch_size, sub_query_index}             # _msearch only
```

See [docs/ARCHITECTURE.md §3](../docs/ARCHITECTURE.md) for the full schema.

---

## Stress tool (`tools/stress/`)

The primary load/stress tool lives in `tools/stress/`. See
[tools/stress/README.md](../tools/stress/README.md) for full documentation.

```bash
python tools/stress/stress.py --list
python tools/stress/stress.py --workload mixed --threads 20 --duration 60
python tools/stress/stress.py --workload script --rate 500 --threads 10
```

---

## Integration tests (`tests/integration/`)

### gateway_resilience.py — gateway resilience proof

Three empirical tests that the OpenResty gateway is transparent, fault-tolerant, and
scalable. Each compares traffic through the gateway against direct ES access.

Good for: CI gating, validating gateway changes, proving Logstash decoupling,
regression-testing proxy overhead.

**Prerequisites**

- ALO running: `docker compose up -d`
- A reachable Elasticsearch — one URL through the gateway (`--gateway`) and one bypassing
  it (`--direct-es`). Compose does not run ES and does not expose a direct port, so point
  `--direct-es` at the same cluster `ELASTICSEARCH_HOST` targets.
- Docker CLI available (the integrity test uses `docker compose stop/start`)

```bash
# Run all 3 tests with defaults
python tests/integration/gateway_resilience.py

# Quick smoke test (skip the slow scaling test)
python tests/integration/gateway_resilience.py --skip scaling

# Run with index cleanup afterward
python tests/integration/gateway_resilience.py --cleanup

# Faster run with fewer iterations
python tests/integration/gateway_resilience.py --iterations 20 --integrity-docs 20 --scale-duration 5

# Override thresholds for a slower environment
python tests/integration/gateway_resilience.py --max-overhead-p50 25 --max-overhead-p95 40

# Run a single test
python tests/integration/gateway_resilience.py --skip integrity,scaling   # overhead only
```

| Flag | Default | Description |
|------|---------|-------------|
| `--gateway` | `http://127.0.0.1:9200` | Gateway URL (env: `GATEWAY_URL`) |
| `--direct-es` | `http://127.0.0.1:9201` | Direct ES URL (env: `DIRECT_ES_URL`) |
| `--iterations` | `50` | Iterations per operation in the overhead test |
| `--integrity-docs` | `50` | Docs per phase in the integrity test (100 total) |
| `--scale-workers` | `1,4,8` | Comma-separated worker counts for the scaling test |
| `--scale-duration` | `15` | Seconds per round in the scaling test |
| `--max-overhead-p50` | `15.0` | Max acceptable p50 overhead % |
| `--max-overhead-p95` | `25.0` | Max acceptable p95 overhead % |
| `--compose-dir` | *(project root)* | Path to the docker-compose project root |
| `--skip` | *(none)* | Comma-separated tests to skip: `overhead`, `integrity`, `scaling` |
| `--cleanup` | `false` | Delete test indices after the run |

Auth/TLS flags (`--username`, `--password`, `--ca-cert`, `--insecure`) come from the
shared `add_auth_args` helper and honour the `ES_*` environment variables.

#### Test 1: gateway overhead (`overhead`)

Compares latency of three operation types — `_search` (match_all), single-doc `PUT`, and
`_bulk` (10 docs) — through the gateway vs direct ES.

- N iterations per operation per path (gateway, then direct)
- p50/p95/p99 percentiles and overhead %
- **Assertion**: p50 overhead < 15 %, p95 overhead < 25 % (configurable)

Indices created: `resilience-overhead`

#### Test 2: data integrity (`integrity`)

Proves Logstash state has zero effect on data reaching Elasticsearch.

- **Phase A (Logstash up)**: writes 50 docs through the gateway, verifies all exist via
  direct ES with field-by-field `_source` comparison
- **Phase B (Logstash down)**: stops Logstash via `docker compose stop logstash`, writes
  50 more docs, verifies all exist, restarts Logstash (guaranteed via `try/finally`)
- Checks `_count` matches the expected total (100)

**Note**: this test stops and restarts the Logstash container. If it crashes, restart it
manually with `docker compose start logstash`.

Indices created: `resilience-integrity`

#### Test 3: scaling overhead (`scaling`)

Measures whether gateway overhead grows disproportionately under load.

- 3 rounds at increasing concurrency (default 1, 4, 8 workers)
- Each round runs mixed operations (search + index) through both paths simultaneously
- **Assertion**: overhead ratio at max workers vs 1 worker < 2.0× (linear scaling)

Indices created: `resilience-scaling`

#### Exit code

**0** if all executed tests pass, **1** if any assertion fails. CI-compatible.

### verify_grafana_dashboards.py — dashboard verification

Playwright script that logs into Grafana, visits each dashboard, scrolls to trigger
lazy-loaded panels, screenshots them, checks every expected panel title renders, and
counts "No data" and error indicators. Writes a machine-readable JSON report; excluded
panels (e.g. Prometheus-backed ones without Prometheus running) are reported but don't
fail the run.

```bash
python tests/integration/verify_grafana_dashboards.py --version v2.1.20
python tests/integration/verify_grafana_dashboards.py --dashboards alo-main,alo-usage
```

| Flag | Default | Description |
|------|---------|-------------|
| `--version` | `dev` | Label for the run — controls the screenshot subdirectory |
| `--base-url` | `http://localhost:3000` | Grafana base URL |
| `--user` / `--password` | `admin` / `admin` | Grafana admin credentials |
| `--dashboards` | all | Comma-separated dashboard UIDs |
| `--time-from` | *(script default)* | Grafana time-range start |
| `--wait-extra` | *(script default)* | Extra seconds to wait after networkidle |

Requires `playwright` (and its browsers) in the interpreter you run it with — it is not
part of the `dev` extra.

---

## Challenges (`tests/challenges/`)

Fourteen interactive load scenarios, each hammering a specific pathology (mega bulk,
micro bulk, geo sweep, hidden CPU, stealth traffic, overfetch, terms lookup, unfiltered
aggs, volume flood, shadow flood, forced refresh, broad match, geo sort, mixed ops). They
seed data, drive traffic, and print what should show up on the dashboards.

```bash
python tests/challenges/challenge_mega_bulk.py
python tests/challenges/challenge_geo_sweep.py --scale 4
```

All of them share `_challenge_runner.main_cli`:

| Flag | Default | Description |
|------|---------|-------------|
| `--gateway` | `http://127.0.0.1:9200` | Gateway base URL (env: `GATEWAY_URL`) |
| `--seed` | `10000` | Seed documents |
| `--max-docs` | `50000` | Stop writing after N docs |
| `--scale` | `1` | Worker multiplier for larger clusters |

Plus the shared auth/TLS flags.
