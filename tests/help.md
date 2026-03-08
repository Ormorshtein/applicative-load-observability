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
    ├── load_test.py                   # realistic mixed-traffic load generator
    └── stress_scenarios.py            # focused single-dimension stress scenarios
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

## Integration Tests (`tests/integration/`)

Live traffic generators that require `docker-compose up` (gateway + ES + Logstash + analyzer).

### load_test.py — Realistic Mixed Traffic

Simulates a production-like workload with a weighted mix of ES operations
(search, index, bulk, update, delete, aggregations, geo, scripts, etc.).
All operations target a single `loadtest` index.

Good for: end-to-end smoke testing, throughput benchmarking, verifying the full pipeline
under general load.

```bash
# Defaults: 60s duration, 10 workers, 200 seed docs
python tests/integration/load_test.py

# Custom run
python tests/integration/load_test.py --duration 120 --workers 20 --seed 500

# Against a different gateway
python tests/integration/load_test.py --gateway http://my-host:9200
```

| Flag | Default | Description |
|------|---------|-------------|
| `--gateway` | `http://localhost:9200` | Gateway base URL |
| `--duration` | `60` | Test duration in seconds |
| `--workers` | `10` | Number of concurrent workers |
| `--seed` | `200` | Number of documents to seed before the test |

**Behavior:**
- Creates a `loadtest` index with a full mapping (text, keyword, float, geo_point, date)
- Seeds documents via `_bulk`
- Workers pick operations from a weighted distribution (simple search 20%, bool search 15%, index 15%, bulk 8%, etc.)
- Prints a live progress line and a final stats table
- **Deletes the index on completion** (always cleans up)

---

### stress_scenarios.py — Focused Stress Isolation

Runs **one stress dimension at a time** with low-stress noise traffic alongside it.
Each scenario has its own index (`stress-{name}`) and distinct `X-App-Name` headers
(`stress-{name}` vs `noise-{name}`), making it easy to filter in Kibana and verify that
the observability pipeline correctly identifies the stress source.

Good for: validating stress scoring, testing individual complexity dimensions,
dashboard verification, targeted debugging.

```bash
# List all available scenarios
python tests/integration/stress_scenarios.py --list

# Run a single scenario for 30 seconds
python tests/integration/stress_scenarios.py --scenario script-heavy

# Run multiple scenarios
python tests/integration/stress_scenarios.py --scenario script-heavy,agg-explosion

# Run all scenarios sequentially (with 10s pause between each)
python tests/integration/stress_scenarios.py --scenario all

# Full custom run
python tests/integration/stress_scenarios.py --scenario all --duration 60 --stress-workers 6 --noise-workers 3 --pause 15

# Clean up indices after run
python tests/integration/stress_scenarios.py --scenario nested-deep --cleanup

# Mix mode — run multiple scenarios in parallel
python tests/integration/stress_scenarios.py --scenario script-heavy,agg-explosion --mix
python tests/integration/stress_scenarios.py --scenario script-heavy,wildcard-swarm,bulk-massive --mix --duration 60
python tests/integration/stress_scenarios.py --scenario all --mix   # all 8 at once
```

| Flag | Default | Description |
|------|---------|-------------|
| `--scenario` | *(required)* | Scenario name, `all`, or comma-separated list |
| `--list` | — | List available scenarios and exit |
| `--duration` | `30` | Duration per scenario in seconds |
| `--stress-workers` | `4` | Concurrent workers sending stressful operations |
| `--noise-workers` | `2` | Concurrent workers sending low-stress operations |
| `--gateway` | `http://localhost:9200` | Gateway base URL |
| `--cleanup` | `false` | Delete stress indices after run |
| `--pause` | `10` | Seconds to wait between scenarios (in `all`/multi mode) |
| `--mix` | `false` | Run selected scenarios in parallel instead of sequentially |

#### Available Scenarios

| Scenario | What it Pushes | Expected Complexity |
|---|---|---|
| `script-heavy` | 3-4 `script_fields` + `script_score` (clause weight 6) | ~24+ |
| `nested-deep` | 4-5 stacked `nested` query clauses (weight 5) | ~25+ |
| `wildcard-swarm` | 6-7 `wildcard`/`regexp`/`prefix` clauses (weight 4) | ~28+ |
| `agg-explosion` | 3-level deep nested aggregations (weight 3) | ~30+ |
| `runtime-abuse` | 3 `runtime_mappings` with embedded scripts (weight 5+6) | ~30+ |
| `geo-complex` | 2 `geo_distance` + 2 `geo_bounding_box` queries | ~10-17 |
| `bulk-massive` | 300-500 doc `_bulk` batches (volume-driven stress) | stress > 1.0 |
| `ubq-carpet-bomb` | `_update_by_query` with `match_all` + script on all docs | stress > 2.0 |

#### Behavior

- Creates a `stress-{name}` index per scenario with the same mapping as `load_test.py`
- Seeds 500 documents per scenario
- Stress workers fire the heavy operation as fast as possible
- Noise workers send lightweight ops (`match_all` size:5, single-doc PUT, `term` query) with 50ms sleeps
- Some ES errors (400s) are expected — e.g., `nested-deep` queries reference unmapped nested paths — but the gateway still forwards the request body for complexity scoring
- Prints live progress, a per-scenario stats table, and Kibana filter instructions
- Indices are **kept by default** for dashboard inspection; use `--cleanup` to remove them
- **Mix mode** (`--mix`): runs all selected scenarios simultaneously with separate stats per scenario — useful for testing how different stress dimensions interact and compete

#### Kibana Verification

After running a scenario, the terminal prints the filters to use:

```
Kibana filter:  request.target: stress-script-heavy
Stress app:     identity.applicative_provider: stress-script-heavy
Noise app:      identity.applicative_provider: noise-script-heavy
```

Use these in the "Applicative Load Observability" dashboard to confirm the stress source
dominates and noise stays minimal.
