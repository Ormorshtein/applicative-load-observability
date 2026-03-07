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
                    │  3. ngx.timer.at(0) → NiFi           │
                    └──────────────┬───────────────────────┘
                                   │ fire-and-forget POST
                                   │ drop if NiFi down or full
                                   ▼
                    ┌──────────────────────────┐     ┌──────────────────────────────┐
                    │           NIFI           │     │       ANALYZER SERVICE       │
                    │                          │     │       (Python / FastAPI)     │
                    │  ListenHTTP              │     │                              │
                    │       ↓                  │     │  - parse headers             │
                    │  InvokeHTTP ─POST──────────────▶  - parse path + body        │
                    │       ↓      ◀─JSON record────────  - calc stress score      │
                    │  PutElastic              │     │  - return observability rec  │
                    │  SearchRecord            │     └──────────────────────────────┘
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

**Technology:** Nginx / OpenResty (Lua — ~25 lines, no logic)

**Philosophy:** The gateway is a pure proxy. It does zero parsing and zero logic. Its only responsibilities are:
1. Forward every request to Elasticsearch verbatim
2. Return the ES response to the client immediately
3. After the response is sent, fire a single async HTTP POST to NiFi with raw data

All extraction, parsing, and analysis happens downstream in Python.

**How the async notification works:**
- `body_filter_by_lua_block` accumulates response chunks into `ngx.ctx.resp_body`
- `log_by_lua_block` fires `ngx.timer.at(0, notify_nifi, ctx)` — this runs after the response is already sent to the client
- `notify_nifi` uses `lua-resty-http` to POST JSON to `http://nifi:8080/observe`
- The entire call is wrapped in `pcall` — any error is silently dropped

**What Nginx sends to NiFi (raw variables, no processing):**

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
  "response_took_ms":    42,
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
| `response_took_ms` | `upstream_response_time * 1000` |
| `request_size_bytes` | `$content_length` |
| `response_size_bytes` | `#ngx.ctx.resp_body` |
| `client_host` | `ngx.var.remote_addr` |

**Drop behavior:**
- NiFi **down** → connect fails within 1s → pcall catches → drop
- NiFi **queue full** → returns 503 → drop
- No local queue, no retry, no buffer

---

### 2.2 NiFi Flow

**Technology:** Apache NiFi (configuration only — no custom code)

**Responsibility:** Receives raw events from the gateway, calls the analyzer, writes the result to Elasticsearch.

| Processor | Configuration | Failure route |
|-----------|--------------|---------------|
| `ListenHTTP` | Port 8080, path `/observe`, back-pressure 1000 flowfiles → 503 | — |
| `InvokeHTTP` | POST `http://analyzer:8000/analyze`, timeout 5s | Log + drop |
| `PutElasticsearchRecord` | Index `applicative-load-observability`, JsonTreeReader | Retry with backoff |

NiFi forwards the raw Nginx payload to the analyzer as-is — no transformation.

---

### 2.3 Analyzer Service

**Technology:** Python, FastAPI

**Endpoint:** `POST /analyze`

**Philosophy:** Single responsibility — receive a raw Nginx payload, extract all meaningful fields, return a structured observability record. Stateless, pure, no I/O beyond HTTP.

#### Header Extraction

| Field | Logic |
|-------|-------|
| `username` | Decode `Authorization: Basic` → base64 → split `:` → first part |
| `applicative_provider` | `x-opaque-id` (strip `/pod-suffix`) → `x-app-name` → `user-agent` (up to first `/`) → `""` |
| `user_agent` | Raw `user-agent` header value |
| `client_host` | `client_host` field from Nginx payload |

#### Path Parsing

| Field | Logic |
|-------|-------|
| `target` | First path segment not starting with `_`. Wildcards and multi-index patterns kept verbatim (e.g. `logs-*`, `index1,index2`). Defaults to `_all`. |
| `operation_kind` | `query` / `insert` / `update` / `delete` — derived from method + path segments |
| `operation_type` | `agg` / `text` / `geo` / `knn` / `bulk` / `by_query` / `single` — derived from path + body |

**Operation kind rules:**

| Condition | Result |
|-----------|--------|
| path contains `_search` | `query` |
| path contains `_bulk` | `insert` |
| path contains `_create` or method `PUT` + `_doc` | `insert` |
| path contains `_update_by_query` | `update` |
| path contains `_update` | `update` |
| path contains `_delete_by_query` | `delete` |
| method `DELETE` | `delete` |

**Operation type rules (checked in order):**

Derived from **both path and body** — path for structural operations, body for query shape.

| Condition | Source | Result |
|-----------|--------|--------|
| path ends `_bulk` | path | `bulk` |
| path ends `_update_by_query` or `_delete_by_query` | path | `by_query` |
| body has `aggs` or `aggregations` | body | `agg` |
| body has top-level `knn` or `query.knn` | body | `knn` |
| body has `query.geo_*` clause | body | `geo` |
| body has `query.match` / `multi_match` / `query_string` / `simple_query_string` | body | `text` |
| default | — | `single` |

#### Request Body Extraction

| Field | Logic |
|-------|-------|
| `size` | `body.get("size", 10)` |
| `has_script` | Recursively search for any key named `"script"` anywhere in body |
| `has_runtime_mappings` | `"runtime_mappings"` key exists at top level |
| `template` | Body with all scalar leaf values replaced by `"?"`, then `json.dumps(sort_keys=True)` |

**Query Complexity — `calc_query_complexity(body) → dict`**

A dedicated calculator that recursively walks the query body and counts all structurally expensive patterns. Returns both raw counts (stored as fields) and a single weighted `query_complexity` score (feeds stress formula).

| Field | What is counted | Weight |
|-------|----------------|--------|
| `bool_clause_count` | Number of `bool` nodes anywhere in the query tree — each adds coordination overhead and scales with nesting depth | 1 |
| `terms_values_count` | Total number of values across all `terms: {field: [...]}` queries | 1 |
| `geo_clause_count` | Number of `geo_distance` / `geo_shape` / `geo_bounding_box` / `geo_polygon` clauses | 2 |
| `fuzzy_clause_count` | Number of `fuzzy` clauses (Levenshtein automata construction) | 2 |
| `nested_clause_count` | Number of `nested` clauses (sub-query executed per nested object) | 2 |
| `knn_clause_count` | Number of `knn` vector similarity queries — CPU-intensive per-vector comparison | 2 |
| `wildcard_clause_count` | Number of `wildcard`, `regexp`, and `prefix` clauses — all require a full term-dictionary scan, bypassing the inverted index | 3 |
| `agg_clause_count` | Number of top-level aggregation definitions in `aggs` / `aggregations` — each bucket accumulates heap-resident field data | 3 |

```
query_complexity = (
    1 * bool_clause_count
  + 1 * terms_values_count
  + 2 * geo_clause_count
  + 2 * fuzzy_clause_count
  + 2 * nested_clause_count
  + 2 * knn_clause_count
  + 3 * wildcard_clause_count
  + 3 * agg_clause_count
)
```

All raw counts and `query_complexity` are stored in the observability record.
Baseline for stress normalisation: `query_complexity = 10`.

#### Response Body Extraction

| Field | Logic |
|-------|-------|
| `hits` | `response.hits.total.value` (0 if absent) |
| `shards_total` | `response._shards.total` (0 if absent) |
| `docs_affected` | bulk: `len(items)` / update_by_query: `updated` / delete_by_query: `deleted` / else: 0 |

---

### 2.4 Stress Score

Calculated by `stress.py`. All missing fields default to 0. No upper bound — extreme operations produce extreme scores intentionally.

**Baselines:**

| Input | Baseline | Rationale |
|-------|----------|-----------|
| `took_ms` | 100 ms | Elastic slow-log default starts at 500ms; healthy queries are <100ms |
| `hits` | 1 000 docs | Reasonable result set; scoring + sorting scales with hits |
| `shards_total` | 5 shards | Typical primary count; each shard is CPU + JVM overhead |
| `size` | 100 docs | 10× ES default of 10; drives fetch-phase heap |
| `docs_affected` | 100 docs | Bulk/update/delete volume |
| `query_complexity` | 10 | Weighted complexity units |

**Formulas:**

*Query:*
```
stress = 0.40·norm(took_ms, 100)
       + 0.20·norm(hits, 1000)
       + 0.15·norm(query_complexity, 10)
       + 0.15·norm(size, 100)
       + 0.10·norm(shards_total, 5)

Feature multipliers (applied after):
  has_script           → × 1.5
  has_runtime_mappings → × 1.3
```

Operation type cost (agg, knn, geo) is already captured inside `query_complexity` — no separate multiplier needed.

*Bulk insert (`operation_kind == "insert"` and `operation_type == "bulk"`):*
```
stress = 0.40·norm(took_ms, 100)
       + 0.40·norm(docs_affected, 100)
       + 0.20·norm(shards_total, 5)
```

*Update / delete by query (`operation_type == "by_query"`):*
```
stress = 0.40·norm(took_ms, 100)
       + 0.40·norm(docs_affected, 100)
       + 0.20·norm(shards_total, 5)

if has_script → × 1.5
```

*Single document insert / update / delete (`operation_type == "single"`):*
```
stress = 0.50·norm(took_ms, 100) + 0.50
```
The constant `0.50` represents the irreducible cost of any write operation regardless of latency.

> All multiplier values are best-effort initial placeholders. They encode the relative resource
> profile of each operation type (CPU vs memory intensity) and must be tuned with real data.

---

### 2.5 Elasticsearch — Observability Index

**Index:** `applicative-load-observability`

Written by NiFi. One document per analyzed operation.

---

## 3. Observability Record Schema

```json
{
  "timestamp":              "2026-03-07T10:00:00.000Z",

  "operation_kind":         "query",
  "operation_type":         "agg",
  "target":                 "products",
  "template":               "{\"aggs\":{\"?\":{\"terms\":{\"field\":\"?\"}}}}",

  "username":               "alice",
  "client_host":            "10.0.0.5",
  "applicative_provider":   "search-api",
  "user_agent":             "elasticsearch-py/8.13.0 (Python/3.11.0; linux)",

  "response_took_ms":       42,
  "hits":                   1500,
  "shards_total":           5,
  "size":                   10,
  "docs_affected":          0,
  "has_script":             false,
  "has_runtime_mappings":   false,
  "request_size_bytes":     284,
  "response_size_bytes":    1920,

  "bool_clause_count":      12,
  "terms_values_count":     0,
  "geo_clause_count":       0,
  "fuzzy_clause_count":     0,
  "nested_clause_count":    0,
  "knn_clause_count":       0,
  "wildcard_clause_count":  0,
  "agg_clause_count":       1,
  "query_complexity":       15,

  "stress_score":           0.87
}
```

---

## 4. Failure Handling

| Scenario | Component | Behavior |
|----------|-----------|----------|
| NiFi down | Gateway | Connect fails within 1s → pcall → drop |
| NiFi queue full | Gateway | NiFi returns 503 → drop |
| Lua timer error | Gateway | pcall → silent drop, client unaffected |
| Analyzer down | NiFi | InvokeHTTP failure route → log + drop |
| ES write fails | NiFi | PutElasticsearchRecord → retry with backoff |
| Malformed body | Analyzer | Returns 200 with partial record, best-effort |

**Rule:** failures in the observability pipeline never propagate upstream. The client always gets its ES response.

---

## 5. Repository Structure

```
applicative-load-observability/
├── README.md                        # product spec
├── docker-compose.yml               # full-stack orchestration
├── docs/
│   ├── ARCHITECTURE.md              # this file
│   └── dashboard-wireframes.html    # visual dashboard mockup
│
├── gateway/
│   ├── nginx.conf                   # Nginx reverse-proxy + Lua fire-and-forget
│   └── Dockerfile                   # FROM openresty/openresty:alpine
│
├── analyzer/
│   ├── main.py                      # FastAPI — POST /analyze
│   ├── parser.py                    # all extraction logic (pure functions)
│   ├── stress.py                    # stress score calculation
│   ├── requirements.txt             # fastapi, uvicorn
│   └── Dockerfile                   # FROM python:3.12-slim
│
└── nifi/
    └── flow.json                    # NiFi flow: ListenHTTP → InvokeHTTP → PutElasticsearchRecord
```

**To run the full stack:**

```bash
docker-compose up --build
```

Clients connect to `localhost:9200` (gateway) instead of Elasticsearch directly.

---

## 6. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Nginx/OpenResty as gateway | Battle-tested, C-speed proxying, no bottleneck risk |
| Nginx does zero parsing | All logic in Python — easier to test, change, reason about |
| Nginx sends raw headers | No Lua logic for auth/provider extraction — Python handles it |
| Fire-and-forget after response | Zero client latency impact |
| Drop > degrade | No queue in gateway, instant drop if NiFi is unavailable |
| NiFi as orchestrator | Retry, routing, ES writes all in config — no custom code |
| Analyzer is stateless + pure | Single endpoint, trivially testable, no dependencies |
| Template by scalar-scrubbing | Language-agnostic, no query schema knowledge required |
| `applicative_provider` fallback chain | Works with ES conventions (X-Opaque-Id) and custom headers |
| Stress score has no upper bound | Extreme operations should show extreme scores |
| Single docker-compose | Full stack runs with one command |

---

## 7. Future Implementation Ideas

- `has_highlight` — extra CPU cost per result document
- `is_deep_pagination` — `from > 1000`, significant heap pressure
- `timed_out` — query hit ES timeout threshold
- Separate `cpu_stress_score` and `memory_stress_score` — once real data allows accurate resource-type attribution
- Stress score weight and multiplier tuning based on real production data
