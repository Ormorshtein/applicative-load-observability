# Gateway Benchmarking & Resource Sizing

This guide explains how to verify the OpenResty/nginx gateway is not a bottleneck
and how to size all pipeline components (gateway, Logstash, analyzer) for a target throughput.

## Why Benchmark?

The gateway sits in the hot path of every request. It proxies to Elasticsearch,
buffers the response, and fires an async POST to the observability pipeline.
We need empirical proof that this extra hop does not degrade throughput or latency.

## Prerequisites

- A running Kubernetes cluster with the ALO Helm chart deployed
- The stress tool image available: `oracle1012/applicative-load-observability:stress-1.15.0`
- `kubectl` configured and pointing at the cluster
- Adjust service names (`alo-gateway`, `alo-elasticsearch`) to match your Helm release

## Approach: Comparative Stress Runs

Run the stress tool twice at identical settings -- once through the gateway,
once directly against Elasticsearch -- and compare throughput and latency.

The stress tool runs as a temporary K8s pod inside the cluster, hitting services
via cluster DNS. This eliminates port-forward noise and gives accurate numbers.

### Key Flags

| Flag | Value | Purpose |
|------|-------|---------|
| `--rate 0` | Unlimited | No rate limiting -- push as fast as possible (ceiling test) |
| `--warmup 10` | 10 seconds | Discard initial measurements to let things stabilize |
| `--duration 120` | 2 minutes | Measured traffic window |

## Step 1 -- Resource Monitoring

Start this in a separate terminal **before** each stress run and leave it running.
It snapshots gateway pod CPU/memory every 5 seconds:

```bash
while true; do
  kubectl top pod -l app.kubernetes.io/component=gateway --no-headers \
    | while read line; do echo "$(date +%H:%M:%S) $line"; done >> gateway-top.log
  sleep 5
done
```

> Adjust the label selector if yours differs: `kubectl get pod --show-labels | grep gateway`

## Step 2 -- Stress Runs

### Round 1 -- Baseline: 30 threads, mixed

```bash
# Through gateway
kubectl run stress-gw-mixed-30 --rm -it \
  --image=oracle1012/applicative-load-observability:stress-1.15.0 \
  --restart=Never -- \
  --workload mixed --rate 0 --threads 30 --duration 120 --warmup 10 \
  --gateway http://alo-gateway:9200

# Direct to ES
kubectl run stress-direct-mixed-30 --rm -it \
  --image=oracle1012/applicative-load-observability:stress-1.15.0 \
  --restart=Never -- \
  --workload mixed --rate 0 --threads 30 --duration 120 --warmup 10 \
  --gateway http://alo-elasticsearch:9200
```

### Round 2 -- High concurrency: 50 threads, mixed

```bash
# Through gateway
kubectl run stress-gw-mixed-50 --rm -it \
  --image=oracle1012/applicative-load-observability:stress-1.15.0 \
  --restart=Never -- \
  --workload mixed --rate 0 --threads 50 --duration 120 --warmup 10 \
  --gateway http://alo-gateway:9200

# Direct to ES
kubectl run stress-direct-mixed-50 --rm -it \
  --image=oracle1012/applicative-load-observability:stress-1.15.0 \
  --restart=Never -- \
  --workload mixed --rate 0 --threads 50 --duration 120 --warmup 10 \
  --gateway http://alo-elasticsearch:9200
```

### Round 3 -- Read-heavy: 40 threads, search

```bash
# Through gateway
kubectl run stress-gw-search-40 --rm -it \
  --image=oracle1012/applicative-load-observability:stress-1.15.0 \
  --restart=Never -- \
  --workload search --rate 0 --threads 40 --duration 120 --warmup 10 \
  --gateway http://alo-gateway:9200

# Direct to ES
kubectl run stress-direct-search-40 --rm -it \
  --image=oracle1012/applicative-load-observability:stress-1.15.0 \
  --restart=Never -- \
  --workload search --rate 0 --threads 40 --duration 120 --warmup 10 \
  --gateway http://alo-elasticsearch:9200
```

### Round 4 -- Write-heavy: 50 threads, bulk

```bash
# Through gateway
kubectl run stress-gw-bulk-50 --rm -it \
  --image=oracle1012/applicative-load-observability:stress-1.15.0 \
  --restart=Never -- \
  --workload bulk --rate 0 --threads 50 --duration 120 --warmup 10 \
  --gateway http://alo-gateway:9200

# Direct to ES
kubectl run stress-direct-bulk-50 --rm -it \
  --image=oracle1012/applicative-load-observability:stress-1.15.0 \
  --restart=Never -- \
  --workload bulk --rate 0 --threads 50 --duration 120 --warmup 10 \
  --gateway http://alo-elasticsearch:9200
```

## Step 3 -- Interpreting Results

### Is the gateway a bottleneck?

| Metric | Healthy | Bottleneck Signal |
|--------|---------|-------------------|
| Throughput (ops/s) | Gateway within ~10-15% of direct ES | Gateway >25% lower |
| p95/p99 latency | Similar or slightly higher | Much higher through gateway |
| Error rate | 0% on both | Errors only through gateway |
| Throughput ceiling | Both plateau at same thread count | Gateway plateaus earlier |

If gateway ops/s is within ~15% of direct ES ops/s at the same concurrency,
nginx is not the bottleneck -- ES itself is the limiting factor.

### If it IS a bottleneck

| Symptom | Fix |
|---------|-----|
| Connection limits hit | Increase `workerConnections` (default 4096) |
| CPU saturation | Increase `workerProcesses` or add gateway replicas |
| Lua GC pauses (p99 spikes through gateway only) | Profile Lua memory, check response body sizes |
| Pipeline timeout drag | Reduce `pipelineTimeout` below 1000ms |

## Step 4 -- Record Resource Usage

For each gateway-path stress run, record peak and steady-state values from `kubectl top`:

| Round | Peak CPU | Peak Memory | Steady-state CPU | Steady-state Memory |
|-------|----------|-------------|------------------|---------------------|
| mixed-30 | | | | |
| mixed-50 | | | | |
| search-40 | | | | |
| bulk-50 | | | | |

Use these to calculate resource requests/limits:

| Setting | Formula |
|---------|---------|
| requests.cpu | Steady-state CPU from heaviest workload, rounded up to nearest 50m |
| requests.memory | Steady-state memory + ~20% headroom |
| limits.cpu | Peak CPU + ~25% headroom (prevent throttling on bursts) |
| limits.memory | Peak memory + ~30% headroom (OOM-kill protection) |
| replicas | Add replicas if a single pod hits >70% of its CPU limit at target throughput |

## Resource Sizing Estimates

The estimates below are based on what each component does per request.
Use them as a starting point -- validate with the benchmark procedure above.

### What Each Component Does Per Request

**Gateway (OpenResty/nginx + Lua)**
1. Proxy pass to ES, stream response back (nginx core, very cheap)
2. Buffer response body in Lua (table.insert + concat, O(n) on response size)
3. Fire-and-forget POST to pipeline (background Lua timer, JSON encode + HTTP)

**Logstash (JVM)**
1. Receive JSON event via HTTP input
2. Ruby filter: extract 10 fields into clean payload
3. Synchronous HTTP POST to analyzer (blocks until response, ~2-5ms typical)
4. Ruby filter: replace event with analyzer response, add routing metadata
5. Batch write to Elasticsearch data stream

**Analyzer (Python/FastAPI)**
1. Parse JSON payload
2. Extract fields: path, headers, body, response metrics
3. Scrub request body into template (recursive tree walk)
4. Count query clauses (recursive DFS -- dominant CPU cost, 0.5-2ms typical, up to 20ms for deep queries)
5. Evaluate cost indicators (10 threshold checks)
6. Calculate stress score (weighted formula)
7. Return assembled observability record

### Gateway Sizing

Per-core throughput: ~15-25k ops/s (proxy + Lua overhead + async pipeline POST).

| Target ops/s | Replicas | CPU (req / limit) | Memory (req / limit) | workerConnections |
|-------------|----------|---------------------|----------------------|-------------------|
| 30k | 2 | 500m / 1 | 256Mi / 512Mi | 4096 |
| 60k | 2 | 1 / 2 | 512Mi / 1Gi | 4096 |
| 120k | 4 | 1 / 2 | 512Mi / 1Gi | 8192 |
| 200k+ | 6 | 1 / 2 | 512Mi / 1Gi | 8192 |

### Logstash Sizing

Per-pipeline-worker throughput: ~200-400 events/s (dominated by synchronous analyzer round-trip).
Pipeline workers default to CPU count. JVM heap adds fixed memory overhead (512m-1g).

| Target ops/s | Replicas | CPU (req / limit) | Memory (req / limit) | Notes |
|-------------|----------|---------------------|----------------------|-------|
| 30k | 2 | 1 / 2 | 1Gi / 2Gi | JVM heap 512m each |
| 60k | 3 | 1 / 2 | 1Gi / 2Gi | |
| 120k | 5 | 2 / 3 | 1.5Gi / 2.5Gi | Bump `pipeline.workers` to match CPU |
| 200k+ | 8 | 2 / 3 | 1.5Gi / 2.5Gi | Consider `batch.size: 250` |

### Analyzer Sizing

Per-core throughput: ~200-400 req/s (CPU-bound Python, limited by GIL per uvicorn worker).
Scale horizontally with more pods rather than more CPU per pod.

| Target ops/s | Replicas | CPU (req / limit) | Memory (req / limit) | Notes |
|-------------|----------|---------------------|----------------------|-------|
| 30k | 4 | 500m / 1 | 128Mi / 256Mi | ~2 uvicorn workers per pod |
| 60k | 6 | 500m / 1 | 128Mi / 256Mi | |
| 120k | 10 | 1 / 2 | 256Mi / 512Mi | ~4 workers per pod |
| 200k+ | 16 | 1 / 2 | 256Mi / 512Mi | Or fewer pods with more CPU + workers |

### Combined Footprint

Total cluster resources needed at each throughput level:

| Target ops/s | Total Pods | Total CPU (requests) | Total Memory (requests) |
|-------------|------------|----------------------|-------------------------|
| 30k | 8 | 4 cores | 3.3Gi |
| 60k | 11 | 6 cores | 4.5Gi |
| 120k | 19 | 17 cores | 11Gi |
| 200k+ | 30 | 26 cores | 17Gi |

> These exclude Elasticsearch itself, which is typically the actual limiting factor.

### Key Constraints by Component

| Component | Bottleneck | Why |
|-----------|-----------|-----|
| Gateway | Cheapest | nginx event loop is extremely efficient; Lua work is fire-and-forget |
| Logstash | Memory-hungry | JVM heap (512m-1g) + 256MB in-memory queue per replica |
| Analyzer | Pod-hungry | CPU-bound Python with GIL; must scale horizontally |

## Known Optimizations (Not Yet Implemented)

### Extract response fields in gateway Lua instead of forwarding full body

**Impact: High** -- affects all three components, biggest potential throughput gain.

Currently the full ES response body (potentially megabytes for large search results or
bulk responses) traverses the entire pipeline: gateway → Logstash → analyzer. The analyzer
only extracts ~5 integer fields from it:

- `took` (int)
- `hits.total.value` (int)
- `_shards.total` (int)
- `updated` / `deleted` (int, for by-query ops)
- `len(items)` + per-item shard dedup (for bulk)

The fix is to extract these fields in the gateway's `log_by_lua_block` using `cjson.decode`,
send a small `response_meta` dict instead of the raw body, and update the analyzer to read
pre-extracted values. This would cut pipeline data transfer by 90%+ for typical responses.

**Why it's deferred:** Touches all three components (gateway Lua, Logstash Ruby filter,
analyzer Python) plus unit tests. No data loss -- the response body is never stored in the
final observability record.

### Add connection pooling for pipeline POST

**Impact: High** -- eliminates per-request TCP connection overhead in gateway.

The gateway creates a new `resty.http` client and TCP connection for every pipeline POST.
At high throughput this means tens of thousands of TCP connection setups/teardowns per second.
Switching from `request_uri()` to `connect()` + `request()` + `set_keepalive()` would reuse
connections across requests.

### Batch analyzer calls in Logstash

**Impact: High** -- the synchronous per-event HTTP filter is Logstash's binding constraint.

The Logstash `http` filter makes a blocking POST to the analyzer for each event. Each pipeline
worker processes events serially through this filter. With a 3ms round-trip, a single worker
tops out at ~333 events/s. Batching multiple events per analyzer call (e.g., a `/analyze_batch`
endpoint) would amortize the HTTP overhead and dramatically increase per-worker throughput.
