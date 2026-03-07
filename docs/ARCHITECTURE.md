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

**Technology:** Nginx / OpenResty (Lua — ~25 lines, no parsing logic)

**Philosophy:** The gateway is a pure proxy. It does zero parsing and zero analytical logic. Its only responsibilities are:
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

#### Identity Extraction

*From HTTP headers:*

| Field | Header | Logic |
|-------|--------|-------|
| `username` | `Authorization` | `Basic` → base64 decode → split `:` → first part |
| `applicative_provider` | `x-opaque-id` / `x-app-name` / `user-agent` | `x-opaque-id` (strip `/pod-suffix`) → `x-app-name` → `user-agent` (up to first `/`) → `""` |
| `user_agent` | `user-agent` | Raw value |

*From the Nginx payload (network level, not a header):*

| Field | Source | Logic |
|-------|--------|-------|
| `client_host` | `ngx.var.remote_addr` | TCP peer IP address — cannot be spoofed via headers |

#### Path Parsing

| Field | Logic |
|-------|-------|
| `target` | First path segment not starting with `_`. Wildcards and multi-index patterns kept verbatim (e.g. `logs-*`, `index1,index2`). Defaults to `_all`. |
| `operation` | ES endpoint name extracted from path. For `_doc`, `method` in the record distinguishes index (PUT) from delete (DELETE). |

**Operation rules:**

| Condition | `operation` |
|-----------|-------------|
| path contains `_doc`, method `PUT` | `index` |
| path contains `_doc`, method `DELETE` | `delete` |
| default | last `_`-prefixed segment in path (`_search`, `_bulk`, `_create`, `_update`, `_update_by_query`, `_delete_by_query`, …) |

#### Request Body Extraction

| Field | Logic |
|-------|-------|
| `size` | `body.get("size", 10)` — extracted and stored **only when `operation == "_search"`**; omitted for all other operations (ES ignores `size` on non-search requests) |
| `script_clause_count` | Count of `"script"` keys found anywhere recursively in the body |
| `runtime_mapping_count` | Count of fields defined in `body["runtime_mappings"]` (0 if absent) |
| `template` | Body with all scalar leaf values replaced by `"?"`, then `json.dumps(sort_keys=True)` |

#### Red Flags

Recursively walks the full query body and counts all structurally expensive patterns. Raw counts are stored as individual fields in the observability record. Instead of computing a weighted `query_complexity` sum (which would require production data to justify per-clause weights), the analyzer checks binary flag conditions and produces a `stress_multiplier` applied after the base stress score.

**Raw clause counts** (always stored for drill-down analysis):

| Field | What is counted |
|-------|----------------|
| `bool_clause_count` | Number of `bool` nodes anywhere in the query tree |
| `bool_must_count` | Total number of clauses across all `bool.must` arrays |
| `bool_should_count` | Total number of clauses across all `bool.should` arrays |
| `bool_filter_count` | Total number of clauses across all `bool.filter` arrays |
| `bool_must_not_count` | Total number of clauses across all `bool.must_not` arrays |
| `terms_values_count` | Total number of values across all `terms: {field: [...]}` queries |
| `knn_clause_count` | Number of `knn` vector similarity queries |
| `fuzzy_clause_count` | Number of `fuzzy` clauses |
| `geo_bbox_count` | Number of `geo_bounding_box` / `geo_grid` clauses |
| `geo_distance_count` | Number of `geo_distance` clauses |
| `geo_shape_count` | Number of `geo_shape` / `geo_polygon` clauses |
| `agg_clause_count` | Total number of aggregation definitions at all nesting levels in `aggs` / `aggregations` (recursive) |
| `wildcard_clause_count` | Number of `wildcard`, `regexp`, and `prefix` clauses |
| `nested_clause_count` | Number of `nested` clauses |
| `runtime_mapping_count` | Number of fields defined in `runtime_mappings` |
| `script_clause_count` | Number of `script` occurrences anywhere in the query body |

**Presence flags** (fires if clause type exists at all):

| Flag | Condition | Multiplier | Rationale |
|------|-----------|------------|-----------|
| `flag_has_script` | `script_clause_count >= 1` | ×1.5 | Per-doc Painless execution, no caching, gated by `allow_expensive_queries` |
| `flag_has_runtime_mapping` | `runtime_mapping_count >= 1` | ×1.5 | ES docs: same per-doc cost as scripts |
| `flag_has_wildcard` | `wildcard_clause_count >= 1` (includes regexp, prefix) | ×1.3 | Full term-dictionary scan, gated by `allow_expensive_queries` |
| `flag_has_nested` | `nested_clause_count >= 1` | ×1.3 | Sub-query per nested object, distributed join |
| `flag_has_fuzzy` | `fuzzy_clause_count >= 1` | ×1.2 | Levenshtein automata construction, non-trivial even though bounded by fuzziness param |
| `flag_has_geo` | `geo_distance_count + geo_shape_count >= 1` | ×1.2 | Per-doc haversine/polygon intersection. Excludes `geo_bbox` (cheap range check) |
| `flag_has_knn` | `knn_clause_count >= 1` | ×1.2 | HNSW graph traversal + vector distance |

**Threshold flags** (fires when count exceeds threshold):

| Flag | Condition | Multiplier | Rationale |
|------|-----------|------------|-----------|
| `flag_excessive_bool` | `bool_must_count + bool_should_count + bool_filter_count + bool_must_not_count >= 50` | ×1.3 | Query bloat — many clauses (even individually cheap) compound into expensive queries; hand-written queries rarely exceed 10 total bool children |
| `flag_large_terms_list` | `terms_values_count >= 500` | ×1.2 | Bulk ID lookups, bypasses terms query cache |
| `flag_deep_aggs` | `agg_clause_count >= 10` | ×1.3 | Heap accumulation, cardinality explosion at each sub-agg level |

Thresholds configurable via env vars (like existing `STRESS_BASELINE_*` pattern):
`RED_FLAG_BOOL_THRESHOLD`, `RED_FLAG_TERMS_THRESHOLD`, `RED_FLAG_AGGS_THRESHOLD`

**Multiplier mechanics:**

```
stress_multiplier = product(flag.multiplier for each active flag)
```

- No flags → 1.0× (no change)
- Script + wildcard → 1.5 × 1.3 = 1.95×
- Script + nested + geo → 1.5 × 1.3 × 1.2 = 2.34×
- Max theoretical (all 10 flags) ≈ 7.0× — rare in practice, 2-3 flags typical

Why multiplicative: expensive features genuinely compound (wildcard inside nested is worse than either alone). System is for observability, not rate-limiting — explosion is a feature.

#### Response Body Extraction

| Field | Logic |
|-------|-------|
| `es_took_ms` | `response_body.took` — ES's own cluster-side execution time in ms (0 if absent) |
| `hits` | `response_body.hits.total.value` (0 if absent) |
| `shards_total` | `response_body._shards.total` (0 if absent) |
| `docs_affected` | bulk: `len(items)` / update_by_query: `updated` / delete_by_query: `deleted` / else: 0 |

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

Each formula computes a `base` score as a weighted sum of normalised inputs, then applies the `stress_multiplier` from red flags (see §2.3). The multiplier defaults to 1.0 when no flags fire.

*`_search`:*
```
base = 0.55·norm(es_took_ms, 100)
     + 0.20·norm(shards_total, 5)
     + 0.15·norm(hits, 10000)
     + 0.10·norm(size, 100)
stress = base × stress_multiplier
```

*`_bulk`:*
```
stress = 0.45·norm(es_took_ms, 100)
       + 0.55·norm(docs_affected, 500)
```

*`_update_by_query` / `_delete_by_query`:*
```
base = 0.40·norm(es_took_ms, 100)
     + 0.35·norm(docs_affected, 500)
     + 0.25·norm(shards_total, 5)
stress = base × stress_multiplier
```

*`_update`:*
```
base = 0.60·norm(es_took_ms, 100)
     + 0.40·norm(shards_total, 5)
stress = base × stress_multiplier
```
For partial-doc updates (no script), no flags fire and `stress_multiplier` is 1.0, so the formula reduces to latency + shards.

*`_create` / `index` / `delete`:*
```
stress = 0.70·norm(es_took_ms, 100)
       + 0.30·norm(shards_total, 5)
```
Single-document writes. No query body → no red flags → no multiplier. All three share this formula as a baseline; see Future Ideas for per-operation weight refinement.

> All weights, flag multipliers, and thresholds are best-effort initial values grounded in ES documentation
> and benchmarks. They must be tuned with real production data over time.

---

## 3. Observability Record Schema

```json
{
  "timestamp":              "2026-03-07T10:00:00.000Z",

  "operation":              "_search",
  "method":                 "POST",
  "path":                   "/products/_search",
  "request_body":           {"query": {"match": {"title": "shoes"}}, "size": 10},
  "target":                 "products",
  "template":               "{\"query\":{\"match\":{\"title\":\"?\"}},\"size\":\"?\"}",

  "username":               "alice",
  "client_host":            "10.0.0.5",
  "applicative_provider":   "search-api",
  "user_agent":             "elasticsearch-py/8.13.0 (Python/3.11.0; linux)",

  "gateway_took_ms":        67,
  "es_took_ms":             42,
  "hits":                   1500,
  "shards_total":           5,
  "size":                   10,
  "docs_affected":          0,
  "request_size_bytes":     284,
  "response_size_bytes":    1920,

  "bool_clause_count":      2,
  "bool_must_count":        3,
  "bool_should_count":      1,
  "bool_filter_count":      2,
  "bool_must_not_count":    0,
  "terms_values_count":     0,
  "knn_clause_count":       0,
  "fuzzy_clause_count":     0,
  "geo_distance_count":     0,
  "geo_shape_count":        0,
  "geo_bbox_count":         0,
  "agg_clause_count":       1,
  "wildcard_clause_count":  0,
  "nested_clause_count":    0,
  "runtime_mapping_count":  0,
  "script_clause_count":    0,

  "red_flags":              [],
  "red_flag_count":         0,
  "stress_multiplier":      1.0,

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

## 5. Key Design Decisions

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

## 6. Repository Structure

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

## 7. Future Implementation Ideas

- Red flag threshold and multiplier tuning — current thresholds (`bool children >= 50`, `terms >= 500`, `aggs >= 10`) and multiplier values (1.2–1.5) are initial estimates. Once production data is available, analyse flag firing rates and correlation with `es_took_ms` to validate and adjust these values.
- `search_type` classification (`agg` / `knn` / `geo` / `text` / `simple`) — applies to `_search`, `_update_by_query`, and `_delete_by_query` (all carry a query body). Deferred because naive top-level detection (e.g. "body has `query.geo_*`") misclassifies queries where the expensive clause is nested inside a `bool`. Since red flags already capture these signals recursively and correctly, adding a shallow `search_type` label would produce inconsistent dashboard data. Requires recursive detection with a priority order (most expensive type wins).
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
- Stress score formula weight tuning and red flag multiplier calibration based on real production data
