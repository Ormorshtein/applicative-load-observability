# Architecture — Applicative Load Observability

## 1. Overview

This system wraps any Elasticsearch deployment with a transparent observability pipeline. Every request that passes through the gateway is analyzed for load, stress-scored, and written to a dedicated observability index — with zero impact on the client and zero risk of cascading failure.

```
┌─────────────┐     ┌──────────────────────────────────────┐
│   Client    │────▶│               GATEWAY                │
│ (any app)   │◀────│   Nginx / OpenResty (pure proxy)     │
└─────────────┘     │                                      │
                    │  1. Forward request → Elasticsearch  │
                    │  2. Return ES response to client     │
                    │  3. ngx.timer.at(0) → Logstash       │
                    └──────────────┬───────────────────────┘
                                   │ fire-and-forget POST
                                   │ drop if Logstash down
                                   ▼
                    ┌──────────────────────────┐     ┌──────────────────────────────┐
                    │        LOGSTASH          │     │       ANALYZER SERVICE       │
                    │                          │     │       (Python / FastAPI)     │
                    │  http input (:8080)      │     │                              │
                    │       ↓                  │     │  - parse headers             │
                    │  http filter ─POST─────────────▶  - parse path + body        │
                    │       ↓      ◀─JSON record────────  - calc stress score      │
                    │  elasticsearch output    │     │  - return observability rec  │
                    │                          │     └──────────────────────────────┘
                    └──────────────┬───────────┘
                                   │ write
                                   ▼
                    ┌──────────────────────────┐
                    │      ELASTICSEARCH       │
                    │  index: applicative-     │
                    │  load-observability      │
                    └──────────────────────────┘
```

---

## 2. Components

### 2.1 Gateway

**Technology:** Nginx / OpenResty (Lua)

**Philosophy:** The gateway is a pure proxy. It does zero parsing and zero analytical logic. Its only responsibilities are:
1. Forward every request to Elasticsearch verbatim
2. Return the ES response to the client immediately
3. After the response is sent, fire a single async HTTP POST to the pipeline with raw data

All extraction, parsing, and analysis happens downstream in Python.

**How the async notification works:**
- `body_filter_by_lua_block` accumulates response chunks using `table.insert` + `table.concat` (O(n) instead of O(n²) string concatenation) into `ngx.ctx.resp_body`
- `log_by_lua_block` fires `ngx.timer.at(0, notify_pipeline, ctx)` — this runs after the response is already sent to the client
- `notify_pipeline` uses `lua-resty-http` to POST JSON to the pipeline (URL configured via `PIPELINE_URL` env var)
- The entire call is wrapped in `pcall` — any error is silently dropped
- `resty.http` and `cjson` modules are loaded lazily inside the timer callback (cosocket API is unavailable in `init_worker_by_lua_block`)

**Worker initialization (`init_worker_by_lua_block`):**
- Caches environment variables (`PIPELINE_URL`, ES auth credentials, NiFi auth) into `_G.*` globals once per worker
- Auth headers (Basic or ApiKey) are pre-computed at init time to avoid per-request overhead

**Health check endpoint (`/health`):**
- Sends a `HEAD` request to Elasticsearch with a 3-second timeout
- Returns `200 {"status":"ok"}` if ES responds with status < 500
- Returns `503 {"status":"unavailable"}` if ES is down or unreachable
- Used by Kubernetes readiness and liveness probes (HTTP, not TCP)
- Does **not** trigger the observability pipeline (separate location block)

**Upstream error handling (`@upstream_error`):**
- Catches 502/503/504 from Elasticsearch
- Logs structured error details (upstream addr, status, connect/response times)
- Returns a JSON error body to the client instead of a default nginx error page

**What Nginx sends to Logstash (raw variables, no processing):**

```json
{
  "method":              "POST",
  "path":                "/products/_search",
  "headers": {
    "authorization":     "Basic YWxpY2U6cGFzc3dvcmQ=",
    "x-opaque-id":       "search-api",
    "x-app-name":        "search-api",
    "user-agent":        "elasticsearch-py/8.13.0 (Python/3.11.0; linux)",
    "content-type":      "application/json"
  },
  "request_body":        "{\"query\":{\"match_all\":{}}}",
  "response_body":       "{\"took\":42,\"hits\":{\"total\":{\"value\":1500},\"hits\":[]}}",
  "response_status":     200,
  "gateway_took_ms":     42,
  "request_size_bytes":  284,
  "response_size_bytes": 1920,
  "client_host":         "10.0.0.5"
}
```

| Field | Nginx variable |
|-------|----------------|
| `method` | `ngx.var.request_method` |
| `path` | `ngx.var.uri` |
| `headers` | `ngx.req.get_headers()` serialized as-is |
| `request_body` | `ngx.req.get_body_data()` |
| `response_body` | accumulated in `body_filter_by_lua_block` |
| `response_status` | `ngx.status` |
| `gateway_took_ms` | `upstream_response_time * 1000` — full round-trip as measured by Nginx (network + ES queue + execution) |
| `request_size_bytes` | `$content_length` |
| `response_size_bytes` | `#ngx.ctx.resp_body` |
| `client_host` | `ngx.var.remote_addr` |

**Drop behavior:**
- Pipeline **down** → connect fails within timeout → pcall catches → drop
- No local queue, no retry, no buffer

---

### 2.2 Logstash Pipeline

**Technology:** Logstash 8.13.0 with `logstash-filter-http` plugin

**Responsibility:** Receives raw events from the gateway, calls the analyzer, writes the result to Elasticsearch.

**Pipeline stages:**

| Stage | Plugin | Configuration |
|-------|--------|---------------|
| Input | `http` | Port configurable via `LOGSTASH_HTTP_PORT` (default 8080), JSON codec |
| Filter | `ruby` | Builds clean JSON payload from gateway fields, stores in `@metadata` |
| Filter | `http` | POST to analyzer (URL configurable via `ANALYZER_URL`, default `http://analyzer:8000/analyze`); `keepalive => true` for TCP connection reuse |
| Filter | `ruby` | Replaces Logstash event fields with analyzer response, extracts operation for data stream routing |
| Output | `elasticsearch` | Events tagged `_httprequestfailure` → `alo-dead-letter` index; successful events → `logs-alo.{operation}-{cluster}` data streams |

The ruby filter extracts only the gateway fields (`method`, `path`, `headers`, `request_body`, `response_body`, `client_host`, `gateway_took_ms`, `request_size_bytes`, `response_size_bytes`) into a clean JSON payload, stripping Logstash metadata (`@version`, `@timestamp`, `event`, etc.) before sending to the analyzer.

---

### 2.3 Analyzer Service

**Technology:** Python, FastAPI

**Endpoint:** `POST /analyze`

**Philosophy:** Single responsibility — receive a raw Nginx payload, extract all meaningful fields, return a structured observability record. Stateless, pure, no I/O beyond HTTP.

#### Identity Extraction

*From HTTP headers:*

| Field | Header | Logic |
|-------|--------|-------|
| `identity.username` | `Authorization` | `Basic` → base64 decode → split `:` → first part |
| `identity.applicative_provider` | `x-opaque-id` / `x-app-name` / `user-agent` | `x-opaque-id` (strip `/pod-suffix`) → `x-app-name` → `user-agent` (up to first `/`) → `""` |
| `identity.user_agent` | `user-agent` | Raw value |

*From the Nginx payload (network level, not a header):*

| Field | Source | Logic |
|-------|--------|-------|
| `identity.client_host` | `ngx.var.remote_addr` | TCP peer IP address — cannot be spoofed via headers |

#### Path Parsing

| Field | Logic |
|-------|-------|
| `request.target` | First path segment not starting with `_`. Wildcards and multi-index patterns kept verbatim (e.g. `logs-*`, `index1,index2`). Defaults to `_all`. |
| `request.operation` | ES endpoint name extracted from path. For `_doc`, `method` in the record distinguishes index (PUT) from delete (DELETE). |

**Operation rules:**

| Condition | `request.operation` |
|-----------|-------------|
| path contains `_doc`, method `GET` or `HEAD` | `get` |
| path contains `_doc`, method `PUT` or `POST` | `index` |
| path contains `_doc`, method `DELETE` | `delete` |
| path contains `_`-prefixed segment (not `_doc`) | segment name (`_search`, `_bulk`, `_create`, `_update`, `_count`, `_validate`, …) |
| no `_`-prefixed segment, method `GET`/`HEAD` | `get` |
| no `_`-prefixed segment, method `PUT`/`POST` | `index` |
| no `_`-prefixed segment, method `DELETE` | `delete` |

#### Request Body Extraction

| Field | Logic |
|-------|-------|
| `request.size` | `body.get("size", 10)` — extracted and stored **only when `request.operation == "_search"`**; omitted for all other operations (ES ignores `size` on non-search requests) |
| `request.template` | Body with all scalar leaf values replaced by `"?"`, then `json.dumps(sort_keys=True)` |

#### Cost Indicators

Recursively walks the full query body and counts all structurally expensive patterns. Raw counts are stored under `clause_counts` in the observability record. Instead of computing a weighted `query_complexity` sum (which would require production data to justify per-clause weights), the analyzer checks binary conditions ("cost indicators") and produces a `stress.multiplier` applied after the base stress score.

The `cost_indicators` field is a dictionary mapping each active indicator name to the clause count that triggered it, enabling drill-down analysis without inspecting the raw clause count fields.

**Raw clause counts** (stored under `clause_counts.*`):

| Field | What is counted |
|-------|----------------|
| `clause_counts.bool` | Number of `bool` nodes anywhere in the query tree |
| `clause_counts.bool_must` | Total number of clauses across all `bool.must` arrays |
| `clause_counts.bool_should` | Total number of clauses across all `bool.should` arrays |
| `clause_counts.bool_filter` | Total number of clauses across all `bool.filter` arrays |
| `clause_counts.bool_must_not` | Total number of clauses across all `bool.must_not` arrays |
| `clause_counts.terms_values` | Total number of values across all `terms: {field: [...]}` queries |
| `clause_counts.knn` | Number of `knn` vector similarity queries |
| `clause_counts.fuzzy` | Number of `fuzzy` clauses |
| `clause_counts.geo_bbox` | Number of `geo_bounding_box` / `geo_grid` clauses |
| `clause_counts.geo_distance` | Number of `geo_distance` clauses |
| `clause_counts.geo_shape` | Number of `geo_shape` / `geo_polygon` clauses |
| `clause_counts.agg` | Total number of aggregation definitions at all nesting levels in `aggs` / `aggregations` (recursive) |
| `clause_counts.wildcard` | Number of `wildcard`, `regexp`, and `prefix` clauses |
| `clause_counts.nested` | Number of `nested` clauses |
| `clause_counts.runtime_mapping` | Number of fields defined in `runtime_mappings` |
| `clause_counts.script` | Number of `script` occurrences anywhere in the query body |

**Presence indicators** (fires if clause type exists at all):

| Indicator | Condition | Multiplier | Rationale |
|-----------|-----------|------------|-----------|
| `has_script` | `script >= 1` | ×1.5 | Per-doc Painless execution, no caching, gated by `allow_expensive_queries` |
| `has_runtime_mapping` | `runtime_mapping >= 1` | ×1.5 | ES docs: same per-doc cost as scripts |
| `has_wildcard` | `wildcard >= 1` (includes regexp, prefix) | ×1.3 | Full term-dictionary scan, gated by `allow_expensive_queries` |
| `has_nested` | `nested >= 1` | ×1.3 | Sub-query per nested object, distributed join |
| `has_fuzzy` | `fuzzy >= 1` | ×1.2 | Levenshtein automata construction, non-trivial even though bounded by fuzziness param |
| `has_geo` | `geo_distance + geo_shape >= 1` | ×1.2 | Per-doc haversine/polygon intersection. Excludes `geo_bbox` (cheap range check) |
| `has_knn` | `knn >= 1` | ×1.2 | HNSW graph traversal + vector distance |

**Threshold indicators** (fires when count exceeds threshold):

| Indicator | Condition | Multiplier | Rationale |
|-----------|-----------|------------|-----------|
| `excessive_bool` | `bool_must + bool_should + bool_filter + bool_must_not >= 50` | ×1.3 | Query bloat — many clauses (even individually cheap) compound into expensive queries; hand-written queries rarely exceed 10 total bool children |
| `large_terms_list` | `terms_values >= 500` | ×1.2 | Bulk ID lookups, bypasses terms query cache |
| `deep_aggs` | `agg >= 10` | ×1.3 | Heap accumulation, cardinality explosion at each sub-agg level |

Thresholds configurable via env vars (like existing `STRESS_BASELINE_*` pattern):
`COST_INDICATOR_BOOL_THRESHOLD`, `COST_INDICATOR_TERMS_THRESHOLD`, `COST_INDICATOR_AGGS_THRESHOLD`

**Cost indicators output:**

The `cost_indicators` field is a dictionary mapping each active indicator name to the clause count that triggered it:

```json
{
  "cost_indicators": {
    "has_script": 3,
    "has_wildcard": 2
  },
  "stress": {
    "score":                1.87,
    "multiplier":           1.95,
    "cost_indicator_count": 2,
    "cost_indicator_names": ["has_script", "has_wildcard"]
  }
}
```

When no indicators fire, `cost_indicators` is an empty dict `{}`.

**Multiplier mechanics:**

```
stress.multiplier = product(indicator.multiplier for each active indicator)
```

- No indicators → 1.0× (no change)
- Script + wildcard → 1.5 × 1.3 = 1.95×
- Script + nested + geo → 1.5 × 1.3 × 1.2 = 2.34×
- Max theoretical (all 10 indicators) ≈ 7.0× — rare in practice, 2-3 indicators typical

Why multiplicative: expensive features genuinely compound (wildcard inside nested is worse than either alone). System is for observability, not rate-limiting — explosion is a feature.

#### Response Body Extraction

| Field | Logic |
|-------|-------|
| `response.es_took_ms` | `response_body.took` — ES's own cluster-side execution time in ms (0 if absent) |
| `response.hits` | `response_body.hits.total.value` (0 if absent) |
| `response.shards_total` | `response_body._shards.total` (0 if absent) |
| `response.docs_affected` | bulk: `len(items)` / update_by_query: `updated` / delete_by_query: `deleted` / else: 0 |

---

### 2.4 Stress Score

Calculated by `stress.py`. All missing fields default to 0. No upper bound — extreme operations produce extreme scores intentionally.

**Baselines:**

| Input | Baseline | Rationale |
|-------|----------|-----------|
| `es_took_ms` | 100 ms | ES's own execution time — slow-log default starts at 500ms; healthy queries are <100ms |
| `hits` | 10 000 docs | Reasonable result set; scoring + sorting scales with hits |
| `shards_total` | 5 shards | Typical primary count; each shard is CPU + JVM overhead |
| `size` | 100 docs | 10× ES default of 10; drives fetch-phase heap — `_search` formula only |
| `docs_affected` | 500 docs | Bulk/update/delete volume |

**Normalisation:**

```
norm(value, baseline) = value / baseline
```

No clamping — values above 1.0 are valid and expected. A query at 2× the baseline contributes 2.0, not 1.0. The stress score has no upper bound by design: extreme operations should produce extreme scores.

**Formulas:**

Each formula computes a `base` score as a weighted sum of normalised inputs, then applies the `stress.multiplier` from cost indicators (see §2.3). The multiplier defaults to 1.0 when no indicators fire.

*`_search`:*
```
base = 0.55·norm(es_took_ms, 100)
     + 0.20·norm(shards_total, 5)
     + 0.15·norm(hits, 10000)
     + 0.10·norm(size, 100)
stress.score = base × stress.multiplier
```

*`_bulk`:*
```
stress.score = 0.45·norm(es_took_ms, 100)
             + 0.55·norm(docs_affected, 500)
```

*`_update_by_query` / `_delete_by_query`:*
```
base = 0.40·norm(es_took_ms, 100)
     + 0.35·norm(docs_affected, 500)
     + 0.25·norm(shards_total, 5)
stress.score = base × stress.multiplier
```

*`_update`:*
```
base = 0.60·norm(es_took_ms, 100)
     + 0.40·norm(shards_total, 5)
stress.score = base × stress.multiplier
```
For partial-doc updates (no script), no indicators fire and `stress.multiplier` is 1.0, so the formula reduces to latency + shards.

*`_create` / `index` / `delete`:*
```
stress.score = 0.70·norm(es_took_ms, 100)
             + 0.30·norm(shards_total, 5)
```
Single-document writes. No query body → no cost indicators → no multiplier. All three share this formula as a baseline; see Future Ideas for per-operation weight refinement.

> All weights, indicator multipliers, and thresholds are best-effort initial values grounded in ES documentation
> and benchmarks. They must be tuned with real production data over time.

---

## 3. Observability Record Schema

The record uses a structured nested layout grouping related fields:

```json
{
  "timestamp": "2026-03-07T10:00:00.000Z",

  "identity": {
    "username":             "alice",
    "applicative_provider": "search-api",
    "user_agent":           "elasticsearch-py/8.13.0 (Python/3.11.0; linux)",
    "client_host":          "10.0.0.5"
  },

  "request": {
    "method":     "POST",
    "path":       "/products/_search",
    "operation":  "_search",
    "target":     "products",
    "template":   "{\"query\":{\"match\":{\"title\":\"?\"}},\"size\":\"?\"}",
    "body":       {"query": {"match": {"title": "shoes"}}, "size": 10},
    "size_bytes": 284,
    "size":       10
  },

  "response": {
    "es_took_ms":    42,
    "gateway_took_ms": 67,
    "hits":          1500,
    "shards_total":  5,
    "docs_affected": 0,
    "size_bytes":    1920
  },

  "clause_counts": {
    "bool": 0, "bool_must": 0, "bool_should": 0,
    "bool_filter": 0, "bool_must_not": 0,
    "terms_values": 0, "knn": 0, "fuzzy": 0,
    "geo_bbox": 0, "geo_distance": 0, "geo_shape": 0,
    "agg": 0, "wildcard": 0, "nested": 0,
    "runtime_mapping": 0, "script": 0
  },

  "cost_indicators": {},

  "stress": {
    "score":                0.87,
    "multiplier":           1.0,
    "cost_indicator_count": 0,
    "cost_indicator_names": []
  }
}
```

**With cost indicators active:**

```json
{
  "cost_indicators": {
    "has_script":  3,
    "has_wildcard": 2
  },
  "stress": {
    "score":                1.87,
    "multiplier":           1.95,
    "cost_indicator_count": 2,
    "cost_indicator_names": ["has_script", "has_wildcard"]
  }
}
```

**Field groups:**

| Group | Fields | Purpose |
|-------|--------|---------|
| `identity.*` | username, applicative_provider, user_agent, client_host | Who sent the request |
| `request.*` | method, path, operation, target, template, body, size_bytes, size | What was requested |
| `response.*` | es_took_ms, gateway_took_ms, hits, shards_total, docs_affected, size_bytes | What ES returned |
| `clause_counts.*` | 16 clause type counts | Raw structural complexity |
| `cost_indicators` | Dict of indicator name → triggering count | Which expensive patterns and how many |
| `stress.*` | score, multiplier, cost_indicator_count, cost_indicator_names | Computed stress assessment |

---

## 4. Elasticsearch Index Templates & ILM

The system uses **composable index templates** with a shared component template (`alo-mappings`), three operation-category templates, and a dead-letter template. All are created automatically by `kibana/setup.py`.

**Component template (`alo-mappings`):**
- **Strict mapping** — only known fields are accepted; no dynamic field creation
- **`request.body`** — stored as `"enabled": false` (in `_source` but not indexed, preventing mapping explosion)
- **`cost_indicators.*`** — each indicator is an explicitly mapped integer field
- **`stress.cost_indicator_names`** — keyword array for Kibana terms aggregation

**Composable index templates:**

| Template | Pattern | ILM Policy | Retention | Priority |
|----------|---------|------------|-----------|----------|
| `alo-search-operations` | `logs-alo.{search ops}-*` | `alo-search-lifecycle` | 90 days | 200 |
| `alo-write-operations` | `logs-alo.{write ops}-*` | `alo-write-lifecycle` | 30 days | 200 |
| `alo-default` | `logs-alo.*-*` | `alo-default-lifecycle` | 60 days | 150 |
| `alo-dead-letter` | `alo-dead-letter*` | `alo-dead-letter-lifecycle` | 7 days | 100 |

All ILM policies use hot→delete phases. Hot phase rolls over at 1 day or 50 GB. The dead-letter index captures events that failed analyzer processing (`_httprequestfailure` tag) for debugging — short retention since these are diagnostic, not analytical data.

---

## 5. Failure Handling

| Scenario | Component | Behavior |
|----------|-----------|----------|
| Pipeline down | Gateway | Connect fails within timeout → pcall → drop |
| Lua timer error | Gateway | pcall → silent drop, client unaffected |
| ES upstream down | Gateway | `/health` returns 503, readiness probe fails, pod removed from service |
| ES upstream error | Gateway | `@upstream_error` logs details, returns JSON error to client |
| Analyzer down | Logstash | http filter failure → `_httprequestfailure` tag → `alo-dead-letter` index |
| ES write fails | Logstash | elasticsearch output retries with backoff |
| Malformed body | Analyzer | Returns 200 with partial record, best-effort |

**Rule:** failures in the observability pipeline never propagate upstream. The client always gets its ES response.

---

## 6. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Nginx/OpenResty as gateway | Battle-tested, C-speed proxying, no bottleneck risk |
| Nginx does zero parsing | All logic in Python — easier to test, change, reason about |
| Nginx sends raw headers | No Lua logic for auth/provider extraction — Python handles it |
| Fire-and-forget after response | Zero client latency impact |
| Drop > degrade | No queue in gateway, instant drop if Logstash is unavailable |
| Logstash as pipeline | HTTP input + filter + ES output — config-driven, no custom code |
| Analyzer is stateless + pure | Single endpoint, trivially testable, no dependencies |
| Template by scalar-scrubbing | Language-agnostic, no query schema knowledge required |
| `applicative_provider` fallback chain | Works with ES conventions (X-Opaque-Id) and custom headers |
| Stress score has no upper bound | Extreme operations should show extreme scores |
| Nested document structure | Related fields grouped (identity, request, response, clause_counts, stress) for clarity and prevention of field-name collisions |
| Strict ES mapping with index template | Prevents mapping explosion from dynamic `request.body` sub-fields |
| Single docker-compose | Full stack runs with one command |
| Environment-variable configuration | All service URLs, ports, and hostnames are configurable via env vars with sensible defaults — works across Docker Compose, Helm, and manual deployments |

---

## 7. Repository Structure

```
applicative-load-observability/
├── README.md                        # product spec
├── docker-compose.yml               # full-stack orchestration
├── docs/
│   ├── ARCHITECTURE.md              # this file
│   └── dashboard-wireframes.html    # visual dashboard mockup
│
├── gateway/
│   ├── nginx.conf.template          # Nginx config template (envsubst at startup)
│   ├── entrypoint.sh                # Resolves env vars and starts OpenResty
│   └── Dockerfile                   # FROM openresty/openresty:alpine
│
├── analyzer/
│   ├── main.py                      # FastAPI — POST /analyze
│   ├── parser.py                    # all extraction logic (pure functions)
│   ├── record_builder.py            # builds observability record from raw payload
│   ├── stress.py                    # stress score + cost indicators calculation
│   ├── requirements.txt             # fastapi, uvicorn
│   └── Dockerfile                   # FROM python:3.12-slim
│
├── logstash/
│   ├── Dockerfile                   # FROM logstash:8.13.0 + logstash-filter-http
│   ├── logstash.yml                 # Logstash settings
│   ├── pipelines.yml                # pipeline configuration
│   └── pipeline/
│       └── observability.conf       # http input → http filter (analyzer) → elasticsearch output
│
├── kibana/
│   ├── setup.py                     # ES template + Kibana dashboard setup
│   ├── dashboard.ndjson             # main dashboard export
│   └── dashboard-cost-indicators.ndjson  # cost indicators dashboard export
│
└── tests/
    ├── conftest.py                  # shared pytest config
    ├── help.md                      # test documentation
    ├── unit/                        # fast offline unit tests
    │   ├── test_parser.py
    │   ├── test_clause_counting.py
    │   ├── test_cost_indicators.py
    │   ├── test_stress_formulas.py
    │   ├── test_record_builder.py
    │   └── test_main.py
    └── integration/                 # live gateway tests
        └── gateway_resilience.py
```

**To run the full stack:**

```bash
docker-compose up --build
```

Clients connect to `localhost:9200` (gateway) instead of Elasticsearch directly.

**Custom deployment (Helm, manual, etc.):**

Override any of the environment variables below. Docker Compose defaults work out of the box.

| Variable | Default | Used by | Purpose |
|----------|---------|---------|---------|
| `ELASTICSEARCH_URL` | `http://elasticsearch:9200` | Logstash, Kibana | Elasticsearch connection URL |
| `ELASTICSEARCH_HOST` | `elasticsearch:9200` | Gateway | Upstream host:port for nginx proxy |
| `ANALYZER_URL` | `http://analyzer:8000/analyze` | Logstash | Analyzer service endpoint |
| `PIPELINE_URL` | `http://logstash:8080/` | Gateway | Pipeline HTTP input endpoint |
| `LOGSTASH_HTTP_PORT` | `8080` | Logstash | Port for Logstash HTTP input |
| `GATEWAY_PORT` | `9200` | Gateway | Port the gateway listens on |
| `DNS_RESOLVER` | `127.0.0.11` | Gateway | DNS resolver (auto-detected from `/etc/resolv.conf` in K8s) |
| `CLUSTER_NAME` | `default` | Logstash | Cluster name added to observability records |
| `LOGSTASH_TIMEOUT_MS` | `1000` | Gateway | Timeout for pipeline POST (ms) |
| `WORKER_CONNECTIONS` | `4096` | Gateway | Max concurrent connections per nginx worker |

---

## 8. Future Implementation Ideas

- Cost indicator threshold and multiplier tuning — current thresholds (`bool children >= 50`, `terms >= 500`, `aggs >= 10`) and multiplier values (1.2–1.5) are initial estimates. Once production data is available, analyse indicator firing rates and correlation with `response.es_took_ms` to validate and adjust these values.
- `search_type` classification (`agg` / `knn` / `geo` / `text` / `simple`) — applies to `_search`, `_update_by_query`, and `_delete_by_query` (all carry a query body). Deferred because naive top-level detection (e.g. "body has `query.geo_*`") misclassifies queries where the expensive clause is nested inside a `bool`. Since cost indicators already capture these signals recursively and correctly, adding a shallow `search_type` label would produce inconsistent dashboard data. Requires recursive detection with a priority order (most expensive type wins).
- Per-operation write weights — current formulas treat `_create`, `_doc` PUT, and `_doc` DELETE identically. In reality their read depth differs: `_doc` PUT (index) is a pure write with no prior read; `_doc` DELETE reads document metadata (version/seq_no) before writing a tombstone; `_update` reads the full `_source` for a read-modify-write cycle. Separate weight sets should be validated against real production latency distributions before applying.
- Upsert detection — `_update` requests with `"upsert"` or `"doc_as_upsert": true` in the body follow a conditional path: create-path (cheap, no source read) if the document is absent, update-path (full read-modify-write) if it exists. Probabilistic cost modeling once hit/miss rates are observable.
- Auto-generated vs user-provided `_id` — `POST /<index>/_doc` (no ID in path) lets ES generate a UUID and skip the existence check entirely, making it a pure write. `PUT /<index>/_doc/<id>` (user-provided ID) requires an existence check before writing to handle version conflicts. Detectable by checking whether the path segment after `_doc` is present. The `index` operation formula should weight user-provided-ID writes higher once this is implemented.
- Bulk action breakdown — `_bulk` requests can mix `index`, `create`, `update`, and `delete` actions. Counting each action type within the bulk would allow a more precise stress signal than `docs_affected` alone.
- `has_highlight` — extra CPU cost per result document
- `is_deep_pagination` — `from > 1000`, significant heap pressure
- `timed_out` — query hit ES timeout threshold
- Separate `cpu_stress_score` and `memory_stress_score` — once real data allows accurate resource-type attribution
- Join queries: `has_child` / `has_parent` clauses (weight 5) — distributed join across parent-child relations, expensive index lookup
- `function_score` queries (weight 3) — custom scoring functions executed per document
- Stress score formula weight tuning and cost indicator multiplier calibration based on real production data
