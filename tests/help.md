# Tests — Load & Stress Tools

This directory contains two complementary tools for exercising the observability gateway.

## load_test.py — Realistic Mixed Traffic

Simulates a realistic production-like workload with a weighted mix of ES operations
(search, index, bulk, update, delete, aggregations, geo, scripts, etc.).
All operations target a single `loadtest` index.

Good for: end-to-end smoke testing, throughput benchmarking, verifying the full pipeline
under general load.

### Usage

```bash
# Defaults: 60s duration, 10 workers, 200 seed docs
python tests/load_test.py

# Custom run
python tests/load_test.py --duration 120 --workers 20 --seed 500

# Against a different gateway
python tests/load_test.py --gateway http://my-host:9200
```

### Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--gateway` | `http://localhost:9200` | Gateway base URL |
| `--duration` | `60` | Test duration in seconds |
| `--workers` | `10` | Number of concurrent workers |
| `--seed` | `200` | Number of documents to seed before the test |

### Behavior

- Creates a `loadtest` index with a full mapping (text, keyword, float, geo_point, date)
- Seeds documents via `_bulk`
- Workers pick operations from a weighted distribution (simple search 20%, bool search 15%, index 15%, bulk 8%, etc.)
- Prints a live progress line and a final stats table
- **Deletes the index on completion** (always cleans up)

---

## stress_scenarios.py — Focused Stress Isolation

Runs **one stress dimension at a time** with low-stress noise traffic alongside it.
Each scenario has its own index (`stress-{name}`) and distinct `X-App-Name` headers
(`stress-{name}` vs `noise-{name}`), making it easy to filter in Kibana and verify that
the observability pipeline correctly identifies the stress source.

Good for: validating stress scoring, testing individual complexity dimensions,
dashboard verification, targeted debugging.

### Usage

```bash
# List all available scenarios
python tests/stress_scenarios.py --list

# Run a single scenario for 30 seconds
python tests/stress_scenarios.py --scenario script-heavy

# Run multiple scenarios
python tests/stress_scenarios.py --scenario script-heavy,agg-explosion

# Run all scenarios sequentially (with 10s pause between each)
python tests/stress_scenarios.py --scenario all

# Full custom run
python tests/stress_scenarios.py --scenario all --duration 60 --stress-workers 6 --noise-workers 3 --pause 15

# Clean up indices after run
python tests/stress_scenarios.py --scenario nested-deep --cleanup
```

### Parameters

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

### Available Scenarios

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

### Behavior

- Creates a `stress-{name}` index per scenario with the same mapping as `load_test.py`
- Seeds 500 documents per scenario
- Stress workers fire the heavy operation as fast as possible
- Noise workers send lightweight ops (`match_all` size:5, single-doc PUT, `term` query) with 50ms sleeps
- Some ES errors (400s) are expected — e.g., `nested-deep` queries reference unmapped nested paths — but the gateway still forwards the request body to NiFi for complexity scoring
- Prints live progress, a per-scenario stats table, and Kibana filter instructions
- Indices are **kept by default** for dashboard inspection; use `--cleanup` to remove them

### Kibana Verification

After running a scenario, the terminal prints the filters to use:

```
Kibana filter:  target: stress-script-heavy
Stress app:     applicative_provider: stress-script-heavy
Noise app:      applicative_provider: noise-script-heavy
```

Use these in the "Applicative Load Observability" dashboard to confirm the stress source
dominates and noise stays minimal.
