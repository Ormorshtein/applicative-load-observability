# Tests

```
tests/
├── conftest.py                        # shared pytest config (adds analyzer/ to sys.path)
├── help.md                            # this file
├── unit/                              # fast, offline unit tests (pytest)
│   ├── test_parser.py                 # parser.py — header, path, body, response extraction
│   ├── test_stress.py                 # stress.py — clause counting, cost indicators, stress formulas
│   ├── test_record_builder.py         # record_builder.py — record assembly, raw field extraction
│   └── test_main.py                   # main.py — FastAPI /analyze and /health endpoints
└── integration/                       # live gateway tests (require running stack)
    ├── gateway_resilience.py          # gateway overhead, data integrity, scaling tests
    ├── _resilience.py                 # internal: LatencyTracker, test runners
    └── helpers.py                     # shared: rand_*, Stats, http_request
```

---

## Unit Tests (`tests/unit/`)

Pure-Python tests for the analyzer service. No network, no Docker — runs in < 1 second.

```bash
# Run all unit tests
python -m pytest tests/unit/ -v

# Run a single module
python -m pytest tests/unit/test_parser.py -v

# Run a single test class or test
python -m pytest tests/unit/test_stress.py::TestCalcStress -v
python -m pytest tests/unit/test_stress.py::TestCalcStress::test_search_at_baseline -v
```

### What is covered

| Module | Test file | Key areas |
|--------|-----------|-----------|
| `parser.py` | `test_parser.py` | Basic-auth username decode, applicative_provider fallback chain (x-opaque-id → x-app-name → user-agent), target/operation path parsing, size defaults, template scrubbing, hits/shards/docs_affected/es_took_ms extraction, bulk shard deduplication |
| `stress.py` | `test_stress.py` | `norm()`, `count_clauses()` for every clause type (bool, wildcard/regexp/prefix, fuzzy, nested, knn, script, terms, geo_*, runtime_mappings, aggs at all nesting levels), `evaluate_cost_indicators()` for all 10 indicators (presence + threshold boundaries + multiplicative compounding + detail via dict), `calc_stress()` for all 8 operation formulas including multiplier application vs `_NO_MULTIPLIER_OPS`, unbounded score verification |
| `record_builder.py` | `test_record_builder.py` | `_parse_json_field`, `extract_raw_fields` (full/empty/malformed payloads), `build_record` (nested structure: identity/request/response/clause_counts/cost_indicators/stress groups, size inclusion/exclusion, template, timestamp format, cost indicators as dict, stress rounding, es_took fallback to gateway_took), `partial_error_record` |
| `main.py` | `test_main.py` | `/health` endpoint, `/analyze` happy path (all operation types, nested structure validation, cost indicators), error handling (unparseable body, empty payload, malformed request/response — all return 200) |

### Record structure

The observability record uses nested groups:

```
timestamp
identity.{username, applicative_provider, user_agent, client_host}
request.{method, path, operation, target, template, body, size_bytes, size}
response.{es_took_ms, gateway_took_ms, hits, shards_total, docs_affected, size_bytes}
clause_counts.{bool, bool_must, ..., script}
cost_indicators.{has_script: N, has_wildcard: N, ...}  (dict, empty when none)
stress.{score, multiplier, cost_indicator_count, cost_indicator_names}
```

---

## Stress Tool (`tools/stress/`)

The primary load/stress tool has moved to `tools/stress/`. See
[tools/stress/README.md](../tools/stress/README.md) for full documentation.

```bash
python tools/stress/stress.py --list
python tools/stress/stress.py --workload mixed --threads 20 --duration 60
python tools/stress/stress.py --workload script --rate 500 --threads 10
```

---

## Integration Tests (`tests/integration/`)

Live traffic generators that require `docker-compose up` (gateway + ES + Logstash + analyzer).

### gateway_resilience.py — Gateway Resilience Proof

Three empirical tests that prove the OpenResty gateway is transparent, fault-tolerant,
and scalable. Each test compares gateway traffic (port 9200) against direct ES access
(port 9201, exposed via `docker-compose.yml`).

Good for: CI gating, validating gateway changes, proving Logstash decoupling,
regression-testing proxy overhead.

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
python tests/integration/gateway_resilience.py --skip overhead,scaling    # integrity only
python tests/integration/gateway_resilience.py --skip overhead,integrity  # scaling only
```

| Flag | Default | Description |
|------|---------|-------------|
| `--gateway` | `http://127.0.0.1:9200` | Gateway URL (env: `GATEWAY_URL`) |
| `--direct-es` | `http://127.0.0.1:9201` | Direct ES URL (env: `DIRECT_ES_URL`) |
| `--iterations` | `50` | Iterations per operation in the overhead test |
| `--integrity-docs` | `50` | Docs per phase in the integrity test (100 total) |
| `--scale-workers` | `1,4,8` | Comma-separated worker counts for scaling test |
| `--scale-duration` | `15` | Seconds per round in the scaling test |
| `--max-overhead-p50` | `15.0` | Max acceptable p50 overhead % |
| `--max-overhead-p95` | `25.0` | Max acceptable p95 overhead % |
| `--compose-dir` | *(auto-detected)* | Path to the docker-compose project root |
| `--skip` | *(none)* | Comma-separated tests to skip: `overhead`, `integrity`, `scaling` |
| `--cleanup` | `false` | Delete test indices after run |

#### Test 1: Gateway Overhead (`overhead`)

Compares latency of three operation types — `_search` (match_all), single-doc `PUT`,
and `_bulk` (10 docs) — through the gateway vs direct ES.

- Runs N iterations per operation per path (gateway, then direct)
- Computes p50/p95/p99 percentiles and overhead %
- **Assertion**: p50 overhead < 15%, p95 overhead < 25% (configurable)

Indices created: `resilience-overhead`

#### Test 2: Data Integrity (`integrity`)

Proves that Logstash state has zero effect on data reaching Elasticsearch.

- **Phase A (Logstash up)**: writes 50 docs through gateway, verifies all exist via direct ES with field-by-field `_source` comparison
- **Phase B (Logstash down)**: stops Logstash via `docker compose stop logstash`, writes 50 more docs, verifies all exist, restarts Logstash (guaranteed via `try/finally`)
- Checks `_count` matches expected total (100)

**Note**: this test manages Logstash lifecycle automatically — it will stop and restart
the Logstash container. If the test crashes, Logstash may remain stopped; restart it
manually with `docker compose start logstash`.

Indices created: `resilience-integrity`

#### Test 3: Scaling Overhead (`scaling`)

Measures whether gateway overhead grows disproportionately under load.

- Runs 3 rounds at increasing concurrency (default: 1, 4, 8 workers)
- Each round runs mixed operations (search + index) through both gateway and direct ES simultaneously
- Computes p50 overhead per round
- **Assertion**: overhead ratio at max workers vs 1 worker < 2.0x (linear scaling)

Indices created: `resilience-scaling`

#### Exit Code

Returns **0** if all executed tests pass, **1** if any assertion fails. CI-compatible.

#### Prerequisites

- Full stack running: `docker compose up -d`
- Port 9201 exposed on ES (added to `docker-compose.yml` by default)
- Docker CLI available (integrity test uses `docker compose stop/start`)
