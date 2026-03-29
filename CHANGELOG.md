# Changelog

## 1.15.0

### Analyzer

- **Geo vertex counting** replaces geo area scoring — counts vertices in `geo_shape`/`geo_polygon` queries for more accurate and predictable stress scoring.
- **Stress score component breakdown** — each observability record now stores the individual `took`, `shards`, `hits`, and `bonus` components that make up the final score.
- **`response.status`** field added to observability records.
- **Proper Python package** — analyzer converted to use relative imports, eliminating stdlib `parser` module shadowing.

### Bug Fixes

- Fixed `scrub_bulk_template` crash when document bodies contain action-like field names (e.g. `{"index": "value"}`).
- Fixed geo vertex counting returning 0 for shapes nested inside `bool` queries.
- Fixed multibyte character corruption in stress tool error snippets (was slicing bytes before UTF-8 decode).

### Dashboard

- **Cluster Usage dashboard** — request rates, latency percentiles, error rates, and volume by operation.
- **Score component breakdown** — table and trend panels added to Cost Indicators dashboard.
- Cost indicator pie chart: `missingBucket` for backward compat with older data, `unflagged` label for new records.
- Fixed usage dashboard latency panels with percentile support.

### Infrastructure

- **`pyproject.toml` with `uv`** — migrated from `requirements.txt`; dev dependencies managed via optional `[dev]` extra.
- **Logstash healthcheck** added; unknown operations routed to dead-letter queue.
- **Docker base images pinned** — uv 0.11.1, OpenResty 1.29.2.2-alpine.
- **CI aligned to Python 3.12** (matching Docker images); standard pre-commit hooks added (`trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-merge-conflict`).
- Grafana/Kibana Dockerfiles narrowed `COPY` scope; `.dockerignore` extended.

### Known Issues

- Kibana legend squashing on template panels in the main dashboard.

### Code Quality

- **`shared/` package** — consolidates HTTP client, data generators, stats utilities; eliminates `importlib` hack in stress tool and challenge scripts.
- **`ndjson()` utility** replaces 11 inline `"\n".join(actions) + "\n"` patterns.
- Dashboard modules split by responsibility (builders + CRUD); challenge runner split into infra + runner.
- Unit tests reorganized into subdirectories mirroring source tree; added tests for challenge infrastructure, latency tracker, and edge cases.
- Developer quickstart added to README; external cheat sheets for dashboard reference.

---

## 1.14.0

### Analyzer

- **Removed `request.size` from stress formula** — ES scores all matched docs regardless of `size`; it only affects the fetch phase (memory/serialization), not CPU. Field still recorded for informational purposes.
- **Reweighted search stress formula** — now `0.50·took + 0.15·shards + 0.35·hits`. Hits weight increased from 15% to 35% to reflect CPU correlation discovered in production.
- **Hits baseline lowered** from 1000 to 500 for better sensitivity.
- **New cost indicator: `unbound_hits`** — flags queries where ES capped hit counting (`hits.total.relation: "gte"`), indicating weak predicate pushdown. 1.3× stress multiplier.
- **Prometheus `/metrics` endpoint** — `prometheus-fastapi-instrumentator` exposes RED metrics, latency histograms, and process stats.

### Dashboard

- **Reorganized layout** — sections now follow investigation flow: Overview → Highest Impact → Stress Trends → Volume & Throughput → Response Times → Sanity Checks.
- **Section headers** — markdown dividers between dashboard sections.
- **Replaced Flagged vs Unflagged pie** with Cost Indicator breakdown (drilldown into has_geo, has_wildcard, etc.).
- **New panels**: Total Hits Over Time, Docs Affected Over Time, Request Size Over Time, Request Volume Over Time (by operation).
- **Multi-cluster filtering** — Cluster dropdown variable in Grafana; Cluster controls panel in Kibana.
- **Disabled `otherBucket`** on all Kibana pie/bar panels (fixes 413 payload errors on high-cardinality fields).
- **Custom labels documented** — `x-alo-*` header naming convention added to README.

### Infrastructure

- **Removed Metricbeat** — replaced by Prometheus exporters.
- **Removed legacy `xpack.monitoring`** from Logstash.
- **Fixed dead letter index template** — priority bumped to 200 (was conflicting with built-in `logs` template at 100).
- **Gateway stub_status** on port 9145 for nginx-prometheus-exporter.

---

## Helm Chart 0.5.0

### Helm

- **Intuitive dashboard switching** — new top-level `dashboardUI` (kibana / grafana / none) replaces scattered toggles.
- **Removed Metricbeat** — replaced by Prometheus exporters for stack monitoring.
- **Prometheus exporter sidecars** — `gateway.exporter.enabled` and `logstash.exporter.enabled` add nginx-prometheus-exporter and logstash-exporter sidecars. Optional `elasticsearch.exporter.enabled` adds elasticsearch-exporter.
- **ALO Health Grafana dashboard** — 4-row, 21-panel dashboard: gateway (connections, drops), analyzer (RED metrics, latency histograms), logstash (events, worker util, JVM/GC, output errors), and Elasticsearch (collapsed, cluster health, search/index rate, JVM, disk).
- **ServiceMonitor CRDs** — `serviceMonitors.enabled` deploys ServiceMonitor resources for Prometheus Operator autodiscovery (gateway, logstash, analyzer, elasticsearch).
- **Analyzer Prometheus instrumentation** — `prometheus-fastapi-instrumentator` exposes `/metrics` with request rate, latency histograms, error rates, and process metrics.
- **Docker Compose prometheus profile** — `docker compose --profile prometheus up` adds Prometheus, nginx-exporter, logstash-exporter, and elasticsearch-exporter services.
- **Validation** — enabling both Kibana and Grafana without `dashboardUI` now fails with a clear error at template render time.
- Added `stub_status` server block to gateway nginx config (internal port 9145, used by the exporter sidecar).

---

## 1.13.0

### Analyzer

- **`request.body` stored as raw JSON string** instead of parsed object — Kibana no longer flattens the body into unreadable dot-notation arrays (`request.body.query.bool.filter.term.category`). Now displays as a clean JSON string.
- ES index template mapping changed from `object (disabled)` to `keyword (no doc_values)` for `request.body`.

### Dashboard

- **New "Top 10 Heaviest Operations" panel** — shows the individual requests with highest stress scores, with their full request bodies. Works with all dashboard variable filters (application, template, cost indicator, etc.). Added to both Grafana and Kibana dashboards.
- Moved stress score column to the left in the "Sample Request Bodies" drilldown panel for faster scanning.
- Updated Dashboard Guide cheat sheet with new panel reference.

### Helm

- Synced Grafana dashboard JSON files with Docker Compose source (picks up all recent fixes: template variables, split count queries for Grafana 11.6, pie chart fixes, drilldown row, raw_document table).
- Bumped all image tags to 1.13.0.

### Kibana setup

- Refactored `_create_drilldown_search` into generic `_create_saved_search` function reused by both the sample bodies and heaviest operations panels.

---

## 1.12.0

### Analyzer

- **ES 8.13–8.15 bulk `took` nanosecond workaround** — the `took` field in `_bulk` responses is sometimes reported in nanoseconds instead of milliseconds. The analyzer detects this by comparing `es_took_ms` against `gateway_took_ms`; if the ratio exceeds 1000× (impossible for legitimate values), the value is divided by 1,000,000. Only applies to `_bulk` operations.
- Fixed `parse_hits` crash when `hits.total` is null (`track_total_hits: false`)
- Fixed `normalize()` division by zero from misconfigured baselines
- Fixed timestamp to include real milliseconds instead of hardcoded `.000`
- Upgraded baseline refresh logging from DEBUG to WARNING with traceback
- Added `stress.bonuses` to ES index mapping (prevents strict mapping rejection)

### Dashboard

- Added **Top 10 Cost Indicators by Stress Score** table below the templates table
- Replaced Stress Trend line chart with **Flagged vs Unflagged** donut pie (new `mk_pie_filters` builder)

### Helm

- Added configurable **init container resource limits** (`initResources`) with minimal defaults (50m/32Mi request, 100m/64Mi limit) — fixes quota-based deployment failures
- Updated `values.schema.json` with `initResources`

### Infrastructure

- **Dead letter converted to data stream** — `logs-alo.dead_letter-*` now uses data stream pattern with proper ILM, matching the rest of the pipeline
- Fixed 401 errors in dashboard import/export by adding auth headers and SSL context to raw `urlopen` calls that bypassed `kibana_request`

### Clean code

- Split `run_challenge()` into setup, interactive loop, and command handlers
- Added type hints across `_trivial_runner.py`
- Removed stale 64KB body cap references from ARCHITECTURE.md

### Documentation

- Documented ES bulk `took` nanosecond workaround in ARCHITECTURE.md

---

## 1.11.0

### Stress scoring overhaul

- **Continuous bonuses for all clause types** — 9 clause types (bool, agg, wildcard, nested, fuzzy, geo, knn, script, terms_values) now add a logarithmic bonus to the base stress score when their count exceeds a threshold: `min(0.10 × ln(1 + excess), 0.50)`. Previously only bool clauses had a bonus; all other types were invisible below their cost indicator threshold.
- **Switched latency metric from `gateway_took_ms` to `es_took_ms`** — `gateway_took_ms` inflates uniformly under cluster saturation (connection pool exhaustion, TCP queueing), drowning the signal from genuinely expensive queries. `es_took_ms` is pure ES processing time with better discrimination under load.
- **`stress.bonuses` in ES record** — new dict field showing which bonuses fired and their values, for score debugging. Empty `{}` for normal queries.
- **Fixed dynamic baseline bug** — `_baselines.py` was querying P50 of `response.gateway_took_ms` but formulas now use `es_took_ms`; corrected to query `response.es_took_ms`.
- **`calc_stress` signature change** — takes full `clause_counts` dict instead of individual `bool_clause_total` param; returns `(score, bonuses)` tuple instead of float.

### Documentation

- Added latency metric rationale (why `es_took_ms`, not `gateway_took_ms`)
- Added dynamic baselines section (P50 from recent traffic, cache TTL, query window, fallback behaviour)
- Added continuous bonuses table with all 9 clause types, thresholds, and formula
- Added `response_size_bytes` future consideration with specific cases and deferral reasoning
- Updated record schema with `stress.bonuses` field

---

## 1.10.0

### Dynamic baselines

- Added `_baselines.py` — P50-based baselines from recent search traffic in ES, cached with configurable TTL (default 60s) and query window (default 1h)
- Only `took_ms` and `shards_total` refresh dynamically; `hits`, `size`, `docs_affected` remain static
- Falls back to static defaults when ES is unreachable or has no data
- Static overrides via `STRESS_BASELINE_*` env vars always take precedence
- Supports full ES connection config: `ELASTICSEARCH_URL`, `ES_USERNAME`, `ES_PASSWORD`, `ES_CA_CERT`, `ES_INSECURE`
- Added `dynamicBaselines` and `stressBaselines` to Helm values schema

### Analyzer changes

- Moved raw field parsing from Logstash ruby filters into the Python analyzer (`record_builder.py`) — gateway now sends raw Nginx variables, analyzer handles all extraction
- Removed `response.body` from ES index mapping (was stored but never queried, wasted storage)
- Removed request body size limits, bumped gateway memory allocation

### Dashboard

- Added Avg Stress column to Top 10 Templates table

---

## 1.9.0

### Gateway transparency

- Removed error interception — ES error responses now pass through to clients transparently instead of being replaced with gateway error JSON
- Synced Helm configmap with Docker template: removed body_filter cap divergence

### Index mapping

- Added `response.body` to index mapping as stored-only field (later removed in 1.10.0)

---

## 1.8.0

### Gateway networking

- Added HTTPS SNI support and `insecureSkipVerify` for gateway ES upstream
- Renamed `gateway.auth.enabled` to `gateway.auth.injectAuth` for clarity (previous name was ambiguous — it controls whether the gateway overrides client auth, not whether auth exists)
- Fixed `proxy_pass` to use upstream block for keepalive connection pooling
- Fixed upstream disable and stale keepalive issues
- Simplified pipeline POST: `cjson.encode(ctx)` instead of manually re-listing fields
- Removed gateway health check and readiness/liveness probes (caused more problems than they solved in environments with intermittent ES connectivity)
- Added health check error logging and configurable error log level
- Synced `values.schema.json` with renamed fields

---

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
- Stress tool with rate limiting, latency percentiles, and 11 workload profiles
- Cost indicators and stress scoring

---

## 1.3.0

### Stress tool and deployment fixes

- Added stress tool Docker image
- Pinned Python dependencies
- Added configurable gateway tunables (worker connections, pipeline timeout)
- Fixed gateway Host header, added error visibility to stress tool and nginx
- Added nginx env directives to preserve env vars for Lua workers
- Removed invalid `xpack.monitoring.elasticsearch.ssl.enabled` setting

---

## 1.2.0

### Multi-cluster and enterprise deployment

- Added auth and TLS support to integration tests
- Fixed logstash.yml mount path to config/ directory
- Used FQDN for internal pipeline URLs (OpenResty DNS fix)
- Added OpenShift Route support for all services
- Added trivial challenge scenarios (overfetch, unfiltered aggs, broad match, volume flood, geo sweep, geo sort, micro bulk, mega bulk, forced refresh, terms lookup, hidden CPU)
- Fixed gateway/logstash/metricbeat ES auth+TLS
- Added values.schema.json
- Made Helm chart airgap-ready: pinned NiFi, configurable test images
- Added TLS and auth support to kibana setup for ECK clusters
- Hardened gateway for OpenShift: non-root temp paths, DNS auto-detect, ES TLS CA

---

## 1.1.0

### Data streams and multi-cluster

- Converted ALO index to data streams (`logs-alo.<operation>-<namespace>`)
- Added ILM per operation category with component template (search 90d, write 30d, default 60d, dead-letter 7d)
- Added `cluster_name` constant_keyword for multi-cluster filtering
- Replaced Cost Indicator pie with Overall Stress Trend on dashboard

### Challenges

- Added challenge v2 (ops) and v3 (stealth)
- Added bool clause complexity bonus to stress score
- Added gateway resilience tests

---

## 1.0.0

### Initial release

- Full observability pipeline: OpenResty gateway → Logstash → Python analyzer → Elasticsearch
- Gateway: transparent proxy with fire-and-forget async notification, zero client impact
- Analyzer: FastAPI service — parses requests/responses, counts clause types, calculates stress score
- Stress scoring: per-operation weighted formulas (search, bulk, by_query, update, doc_write)
- Cost indicators: 10 binary indicators (script, runtime mapping, wildcard, nested, fuzzy, geo, knn, excessive bool, large terms, deep aggs) with multiplicative stress multiplier
- 16 clause type counts stored per record
- Kibana dashboards with cheat sheet, stress trends, top templates, cost indicator breakdown
- NiFi pipeline (later replaced by Logstash in 1.6.0)
- Metricbeat for stack monitoring (toggleable)
- Docker Compose for full-stack local deployment
- Environment variable configuration throughout (12-factor)
- Module split: `stress.py`, `parser.py`, `record_builder.py`, `main.py`
- Comprehensive unit test suite
