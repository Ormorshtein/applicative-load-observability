# Stress Tool

Controllable, high-throughput stress testing for the observability gateway.
Drives Elasticsearch traffic at a target rate with real-time latency
percentiles — similar in spirit to `cassandra-stress`.

## Quick Start

```bash
# List available workloads
python tools/stress/stress.py --list

# Mixed traffic, 20 threads, unlimited rate, 60 seconds
python tools/stress/stress.py --workload mixed --threads 20 --duration 60

# Script-heavy stress, capped at 500 ops/s
python tools/stress/stress.py --workload script --rate 500 --threads 10 --duration 120

# Maximize bulk throughput — 50 threads, no rate limit
python tools/stress/stress.py --workload bulk --rate 0 --threads 50 --duration 120

# With warmup (metrics reset after the warmup phase)
python tools/stress/stress.py --workload mixed --threads 20 --duration 60 --warmup 10
```

## Workload Profiles

### Composite workloads

| Workload | Description |
|----------|-------------|
| `mixed` | Balanced mix of search + write operations (14 weighted op types) |
| `search` | Search-only traffic — all search variants (simple, bool, agg, wildcard, nested, geo, script) |
| `write` | Write-only traffic — index, create, bulk, update, update_by_query, delete, delete_by_query |

### Single-dimension stress profiles

Each hammers ONE specific ES stress dimension as hard as possible. "Indicators tripped"
lists the cost indicators the profile is designed to fire — each one multiplies the stress
score (1.2×–1.5×), and the underlying clause counts also feed logarithmic bonuses added to
the base score. See [docs/ARCHITECTURE.md §2.3–2.4](../../docs/ARCHITECTURE.md).

| Workload | What it pushes | Indicators tripped |
|----------|----------------|--------------------|
| `script` | 3 `script_fields` + a `script_score` query | `has_script` (×1.5) |
| `nested` | 4–5 stacked `nested` queries | `has_nested` (×1.3) |
| `wildcard` | 6–7 `wildcard` / `regexp` / `prefix` clauses | `has_wildcard` (×1.3) |
| `agg` | 3-level deep nested aggregations | `deep_aggs` (×1.3) once ≥10 agg nodes |
| `runtime` | 3 `runtime_mappings` with scripts | `has_runtime_mapping` (×1.5), `has_script` (×1.5) |
| `geo` | 2 `geo_distance` + 2 `geo_bounding_box` | `has_geo` (×1.2) — bbox is counted but excluded from the indicator |
| `bulk` | 300–500 doc `_bulk` batches | none — `_bulk` scores on volume only |
| `ubq` | `_update_by_query` with `match_all` + script | `has_script` (×1.5), plus `docs_affected` volume |

Actual scores depend on the baselines in force (static or dynamically calibrated from
recent traffic), so treat relative ordering between profiles as the signal, not absolute
numbers.

## CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--workload` | *(required unless `--list`)* | Workload profile name |
| `--list` | — | List available workloads and exit |
| `--rate` | `0` | Target ops/sec; 0 = unlimited (max throughput) |
| `--threads` | `10` | Number of concurrent worker threads |
| `--duration` | `60` | Test duration in seconds |
| `--warmup` | `0` | Warmup seconds (metrics reset afterwards) |
| `--seed` | `500` | Documents to seed before the test |
| `--index` | `stress-{workload}` | Custom Elasticsearch index name |
| `--app-name` | `stress-{workload}` | Custom `X-App-Name` header, for dashboard filtering |
| `--gateway` | `http://127.0.0.1:9200` | Gateway base URL (env: `GATEWAY_URL`) |
| `--cleanup` | `false` | Delete the stress index after the run |
| `--username` | — | Elasticsearch username (env: `ES_USERNAME`) |
| `--password` | — | Elasticsearch password (env: `ES_PASSWORD`) |
| `--ca-cert` | — | CA certificate path for TLS (env: `ES_CA_CERT`) |
| `--insecure` | `false` | Skip TLS verification (env: `ES_INSECURE`) |

## Rate Limiting

The `--rate` flag uses a token-bucket algorithm:

- `--rate 0` — **unlimited**: every thread fires as fast as possible. Use this to
  find the cluster's ceiling.
- `--rate 500` — **throttled**: at most 500 operations per second, distributed across all
  threads. Use this to test behavior at a precise load level.

**Tip:** Start with `--rate 0` and a moderate thread count to establish a baseline, then
use `--rate N` to drive specific throughput targets. Increase `--threads` when threads are
the bottleneck (each thread blocks on HTTP round-trips).

## Output

### Live progress (updated every second)

```
  [42s / 60s]  threads: 20  |  1,234 ops/s (target: 2,000)  |  total: 51,828  |  errors: 0.1%
```

### Final report

```
================================================================================
  Stress: mixed  (60.0s)
================================================================================
  Total ops:          74,040
  Throughput:        1,234.0 ops/s
  Errors:                 8
================================================================================
  Operation                Count    Err       p50      p95      p99      Max
  ----------------------------------------------------------------------------
  _bulk                    5,923      0    5.2ms   18.7ms   32.1ms   89.0ms
  _create                  3,702      0    1.5ms    5.8ms   11.2ms   23.0ms
  _search                 44,424      0    2.1ms    8.3ms   15.2ms   45.0ms
  index                   11,106      0    1.8ms    6.1ms   12.3ms   28.0ms
  ...
  ----------------------------------------------------------------------------
  TOTAL                   74,040      8
================================================================================
```

## Finding the traffic in Grafana

After a run the tool prints the exact filter values:

```
  Grafana filters:
    request_target:                 stress-mixed
    identity_applicative_provider:  stress-mixed
```

Use them in the **Stress Analysis** dashboard's Target / Application variables to isolate
the traffic the tool generated. Ad-hoc queries against ClickHouse use the same columns:

```sql
SELECT request_operation, count(), avg(stress_score)
FROM alo.alo_raw
WHERE request_target = 'stress-mixed'
GROUP BY request_operation
ORDER BY 3 DESC;
```

## Architecture

```
tools/stress/
├── stress.py              # entry point — CLI, orchestration, live display
├── _engine.py             # RateLimiter, DocIdTracker, seed, worker loop
├── _metrics.py            # LatencyTracker, percentile math, report formatting
├── _workloads.py          # base Workload class + mixed/search/write profiles
├── _stress_profiles.py    # 8 single-dimension stress profiles
└── _helpers.py            # re-exports from tests/integration/helpers.py
```

All workloads share `tests/integration/helpers.py` (random data generators, HTTP client,
auth/TLS configuration) via `_helpers.py`.
