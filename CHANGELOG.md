# Changelog

## 1.7.0

### Gateway memory hardening

- Fixed OOM (exit 137): changed `workerProcesses` from `auto` to `2` — `auto` sees host cores, not cgroup limits, spawning too many workers for the 512Mi memory limit
- Capped response and request body buffering at 64KB in `body_filter_by_lua_block` — previously the full response (potentially tens of MB for search/scroll) was accumulated in memory before the cap was applied in the log phase. True `response_size_bytes` tracked via counter, unaffected by the cap
- Explicit `ngx.ctx` cleanup — `resp_chunks` freed after concat, `resp_body` freed after timer extraction, releases memory immediately instead of waiting for request context GC
- Installed `lua-resty-openssl` via OPM — eliminates per-worker `resty.openssl.x509.chain not found` warnings from `lua-resty-http` v0.17.2

### Dead-letter ILM

- Added `alo-dead-letter-lifecycle` ILM policy with 7-day retention
- Added `alo-dead-letter` index template that auto-applies the policy to `alo-dead-letter*` indices
- Dead-letter data is diagnostic — short retention keeps the cluster clean

### Gateway health check

- Added `/health` endpoint that sends a `HEAD` request to Elasticsearch with a 3-second timeout
- Returns `200 {"status":"ok"}` when ES is reachable, `503 {"status":"unavailable"}` when not
- Switched Kubernetes readiness and liveness probes from TCP socket to HTTP `/health`
- Health checks do not trigger the observability pipeline (separate nginx location block)

### Unit test improvements

- 184 → 201 tests
- Added 7 tests for `scrub_bulk_template` (previously zero coverage)
- Added 5 tests for `parse_operation` edge cases: `HEAD`, `POST _doc`, `_count`, `_validate`, `_msearch`
- Added 3 tests in `test_record_builder`: non-query ops get zero clause counts, `get` operation, `_count` gets clause counts
- Added 2 tests in `test_stress_formulas`: `get` uses doc_write formula, `get` applies multiplier
- Fixed bulk test to use proper NDJSON `request_body_raw` (was using search body — tested nothing)
- Replaced tautological assertions in `test_main.py` with concrete value checks

### Documentation

- Updated ARCHITECTURE.md: gateway health check, `init_worker_by_lua_block`, upstream error handling, operation dispatch rules (GET/HEAD → `get`), composable index templates with ILM, dead-letter lifecycle, failure handling table, environment variables
- Created this changelog

---

## 1.6.0

### Gateway optimizations

- Fixed O(n²) response body buffering → O(n) `table.insert` + `table.concat`
- Added `init_worker_by_lua_block` to cache environment variables (pipeline URL, ES auth, NiFi auth) once per worker
- Fixed `$host` → `$proxy_host` header (fixes 401 behind HAProxy edge termination)
- Added `@upstream_error` location with structured JSON error responses and logging
- Added `lua_max_pending_timers 65536` and `lua_max_running_timers 4096`
- Added `client_body_buffer_size 2m` and `client_max_body_size 10m`
- Added configurable `proxy_ssl_verify_depth` (default 3) for multi-level TLS chains
- Added `proxy_connect_timeout` (default 10s)
- Disabled `access_log` (observability data goes through the pipeline, not nginx logs)
- Fixed double `tonumber()` on `upstream_response_time`

### Logstash optimizations

- Added `keepalive => true` to HTTP filter for TCP connection reuse to analyzer
- Removed unused `target_headers` capture (was captured then immediately discarded)

### Analyzer fixes

- Fixed `parse_operation` dispatch: GET/HEAD now correctly return `get` instead of `_search`
- Added `_METHOD_DISPATCH` for proper HTTP method → operation mapping
- Fixed `scrub_bulk_template` return type to include extracted targets
- Removed duplicate NDJSON parsing (`_extract_bulk_target`)
- Clause counting now skipped for non-query operations
- Removed dead code `parse_client_host`

### Config sync (Docker ↔ Helm)

- Synced all gateway Lua changes between `gateway/nginx.conf.template` and Helm configmap
- Synced Logstash pipeline changes between `logstash/pipeline/observability.conf` and Helm configmap

---

## 1.5.0

### Pipeline review

- Initial pipeline inefficiency audit and fixes
- Added benchmarking documentation (`docs/gateway-benchmarking.md`) with resource sizing estimates

---

## 1.4.0

- Initial Helm chart with gateway, logstash, analyzer, kibana, elasticsearch
- Stress tool for benchmarking
- Cost indicators and stress scoring
