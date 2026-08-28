# Architecture — Applicative Load Observability

## 1. Overview

ALO wraps any Elasticsearch deployment with a transparent observability pipeline. Every
request that passes through the gateway is analyzed for load, stress-scored, and written
to ClickHouse — with zero impact on the client and zero risk of cascading failure.

Two Elasticsearch-shaped things are involved; keeping them apart matters:

* **Monitored ES** — the customer's cluster the gateway proxies. ALO never writes to it.
* **ClickHouse** — the analytics sink ALO writes its observability rows to. Grafana reads
  from here. (Before 2.0 the sink was Elasticsearch and the UI was Kibana; both are gone.)

```
┌─────────────┐     ┌──────────────────────────────────────┐     ┌──────────────────┐
│   Client    │────▶│               GATEWAY                │────▶│    MONITORED     │
│ (any app)   │◀────│   Nginx / OpenResty (pure proxy)     │◀────│  ELASTICSEARCH   │
└─────────────┘     │                                      │     └──────────────────┘
                    │  1. Forward request → ES             │
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
                    │  http filter ─POST─────────────▶  - parse path + body         │
                    │       ↓      ◀─JSON record────────  - calc stress score       │
                    │  clickhouse output       │     │  - return flat CH row(s)     │
                    └──────────────┬───────────┘     └──────────────────────────────┘
                                   │ insert
                                   ▼
                    ┌──────────────────────────┐          ┌──────────────────┐
                    │        CLICKHOUSE        │◀─────────│     GRAFANA      │
                    │  alo_raw                 │  reads   │   5 dashboards   │
                    │  alo_summary (+ MV)      │          └──────────────────┘
                    │  alo_dead_letter         │
                    └──────────────────────────┘

        Optional: PROMETHEUS scrapes gateway / analyzer / logstash / ClickHouse
                  → Grafana "Stack Health" dashboard
```

---

## 2. Components

### 2.1 Gateway

**Technology:** Nginx / OpenResty (Lua)

**Philosophy:** The gateway is a pure proxy. It does zero parsing and zero analytical
logic. Its only responsibilities are:

1. Forward every request to the monitored Elasticsearch verbatim
2. Return the ES response to the client immediately
3. After the response is sent, fire a single async HTTP POST to Logstash with raw data

All extraction, parsing, and analysis happens downstream in Python.

**How the async notification works** (`gateway/nginx.conf.template`):

- `header_filter_by_lua_block` records whether the upstream response carried
  `Content-Encoding: gzip` (header check, not magic-byte sniffing — catches deflate and
  avoids false positives on payloads that happen to start with `0x1f 0x8b`).
- `body_filter_by_lua_block` accumulates response chunks with `table.insert` +
  `table.concat` (O(n) instead of O(n²) concatenation) into `ngx.ctx.resp_body`. True
  `response_size_bytes` is tracked via a separate counter (`ngx.ctx.resp_size`).
- `log_by_lua_block` fires `ngx.timer.at(0, notify_logstash, ctx)` — this runs after the
  response is already sent to the client. Context references are nilled to free memory.
- Request bodies larger than `client_body_buffer_size` are spooled to disk by nginx; the
  Lua block reads them back from `ngx.req.get_body_file()` so nothing is dropped.
- Compressed bodies (request `Content-Encoding: gzip`/`deflate`, or a gzip response) are
  base64-encoded behind a `gzip+b64:` prefix so `cjson` can serialise them safely. The
  analyzer recovers them (§2.3).
- `notify_logstash` uses `lua-resty-http` to POST JSON to `LOGSTASH_URL`.
- The whole call is wrapped in `pcall` — any error is silently dropped.
- `resty.http` and `cjson` are required lazily inside the timer callback (the cosocket
  API is unavailable in `init_worker_by_lua_block`).

**Prometheus metrics** (registered in `init_worker_by_lua_block`):

| Metric | Type | Labels |
|--------|------|--------|
| `alo_gateway_events_total` | counter | — |
| `alo_gateway_events_dropped_total` | counter | `reason` = `logstash_unreachable` / `logstash_error_<status>` / `pcall_error` / `timer_failed` |

A second internal server listens on **9145**, exposing `/metrics` (the Lua registry) and
`/stub_status` (for `nginx-prometheus-exporter`). It is not published by default.

**What the gateway sends to Logstash (raw variables, no processing):**

```json
{
  "method":              "POST",
  "path":                "/products/_search",
  "headers":             {"authorization": "Basic …", "x-app-name": "search-api"},
  "request_body":        "{\"query\":{\"match_all\":{}}}",
  "response_body":       "{\"took\":42,\"hits\":{\"total\":{\"value\":1500},\"hits\":[]}}",
  "response_status":     200,
  "upstream_response_time": "0.042",
  "content_length":      "284",
  "response_size_bytes": 1920,
  "client_host":         "10.0.0.5",
  "cluster_name":        "default"
}
```

| Field | Nginx source |
|-------|--------------|
| `method` | `ngx.var.request_method` |
| `path` | `ngx.var.uri` |
| `headers` | `ngx.req.get_headers()` serialized as-is |
| `request_body` | `ngx.req.get_body_data()`, falling back to the spooled body file |
| `response_body` | accumulated in `body_filter_by_lua_block` |
| `response_status` | `ngx.status` |
| `upstream_response_time` | `ngx.var.upstream_response_time` (seconds; analyzer ×1000 → `gateway_took_ms`) |
| `content_length` | `ngx.var.content_length` |
| `response_size_bytes` | `ngx.ctx.resp_size` (true byte count) |
| `client_host` | `ngx.var.remote_addr` |
| `cluster_name` | `${CLUSTER_NAME}`, baked in at template render time |

**Drop behavior:**
- Logstash **down** → connect fails within `LOGSTASH_TIMEOUT_MS` → pcall catches → drop,
  counted in `alo_gateway_events_dropped_total`
- No local queue, no retry, no buffer

**Note:** the config carries no `/health` location and no `@upstream_error` handler, so
the Helm chart's gateway probes are plain TCP socket checks and are off by default
(`gateway.probes.enabled: false`).

**Two copies of the config.** Compose renders `gateway/nginx.conf.template`; Helm renders
its own equivalent from `helm/alo/templates/gateway/configmap.yaml`, which adds optional
upstream ES auth injection (`ES_AUTH_USERNAME` / `ES_AUTH_PASSWORD` / `ES_AUTH_API_KEY`
pre-computed into an auth header at worker init) and puts the metrics server behind
`gateway.exporter.enabled`. Any change to one must be mirrored into the other. They also
name one env var differently: Compose passes `LOGSTASH_URL`, Helm passes `PIPELINE_URL`.

---

### 2.2 Logstash pipeline

**Technology:** Logstash 8.13.0 with `logstash-filter-http` (1.4.3) and
`logstash-output-clickhouse` (`logstash/Dockerfile`).

**Responsibility:** Receive raw events from the gateway, call the analyzer, insert the
result into ClickHouse.

**Pipeline stages** (`logstash/pipeline/observability.conf`):

| Stage | Plugin | Configuration |
|-------|--------|---------------|
| Input | `http` | Port `LOGSTASH_HTTP_PORT` (default 8080), **plain ISO-8859-1 codec** |
| Filter | `ruby` | Pre-escapes bytes 0x80–0xFF as `\u00XX` so binary (gzip) bodies survive JSON parsing |
| Filter | `json` | Parses `message`; `_jsonparsefailure` or missing `method`/`path` → `drop` |
| Filter | `ruby` | Builds the clean analyzer payload from gateway fields only |
| Filter | `http` | POST to `ANALYZER_URL` (default `http://analyzer:8000/analyze`), `keepalive => true` |
| Filter | `ruby` | Replaces event fields with the analyzer response; flags dead-letter; unpacks `_msearch_records` |
| Filter | `split` | One event per `_msearch` sub-query record |
| Output | `clickhouse` | `alo.alo_raw`, or `alo.alo_dead_letter` for flagged events |

An event is routed to the dead-letter table when the analyzer returned an `error` key,
when `request_operation` is `unknown`, or when the http filter tagged
`_httprequestfailure` (analyzer unreachable).

Insert tuning is env-driven: `LS_CH_FLUSH_SIZE` (5000),
`LS_CH_DEAD_LETTER_FLUSH_SIZE` (1000), `LS_CH_IDLE_FLUSH_TIME` (5 s),
`LS_CH_AUTOMATIC_RETRIES` (3), `LS_CH_POOL_MAX` (10), `LS_CH_SETTINGS`
(default `input_format_skip_unknown_fields=1,async_insert=1,wait_for_async_insert=0`).
`save_on_failure => false` — ALO drops rather than degrades.

---

### 2.3 Analyzer service

**Technology:** Python 3.11+, FastAPI

| Endpoint | Purpose |
|----------|---------|
| `POST /analyze` | One gateway payload → one flat record (or an `_msearch` fan-out envelope) |
| `POST /analyze/bulk` | JSON array of payloads → JSON array of results, 1:1 positional |
| `GET /health` | Liveness / readiness |
| `GET /metrics` | Prometheus, via `prometheus-fastapi-instrumentator` |

**Philosophy:** Single responsibility — receive a raw gateway payload, extract all
meaningful fields, return a structured observability record. Stateless and pure apart
from the dynamic-baseline query (§2.4). Errors never propagate: an unparseable payload or
a raised exception yields HTTP 200 with a `partial_error_record`, which Logstash routes to
the dead-letter table.

#### Body decompression

`analyzer/_decompression.py` recovers compressed bodies. The `gzip+b64:` prefix set by the
gateway is decoded directly; otherwise the original bytes are recovered from the latin-1
codepoints Logstash produced, then sniffed for gzip/zlib magic. Failures fall back to the
original text.

#### Identity extraction

*From HTTP headers:*

| Field | Header | Logic |
|-------|--------|-------|
| `identity_username` | `Authorization` | `Basic` → base64 decode → split `:` → first part |
| `identity_applicative_provider` | `x-app-name` / `user-agent` | `x-app-name` → `user-agent` up to the first `/` or space → `""`. `x-opaque-id` is intentionally **not** used — real values (e.g. Kibana's per-request IDs) carry a random component and explode cardinality |
| `identity_user_agent` | `user-agent` | Raw value |
| `identity_labels` | `x-alo-*` | Prefix stripped, stored as `Map(String, String)` — `x-alo-team: payments` → `{'team': 'payments'}`. Use hyphens, not underscores: nginx drops underscore headers by default |

*From the payload (network level, not a header):*

| Field | Source | Logic |
|-------|--------|-------|
| `identity_client_host` | `ngx.var.remote_addr` | TCP peer IP — cannot be spoofed via headers |

#### Path parsing

| Field | Logic |
|-------|-------|
| `request_target` | First path segment not starting with `_`. Wildcards and multi-index patterns kept verbatim (`logs-*`, `index1,index2`). Defaults to `_all`; for `_bulk` it falls back to the index named in the action lines |
| `request_operation` | Last `_`-prefixed path segment; `_doc` resolves by method |

**Operation rules** (`analyzer/parser/_path.py`):

| Condition | `request_operation` |
|-----------|---------------------|
| path contains `_doc`, method `GET`/`HEAD` | `get` |
| path contains `_doc`, method `PUT`/`POST` | `index` |
| path contains `_doc`, method `DELETE` | `delete` |
| path contains a `_`-prefixed segment (not `_doc`) | that segment (`_search`, `_msearch`, `_bulk`, `_count`, …) |
| no `_`-prefixed segment | `get` / `index` / `delete` by method |

#### Request body extraction

| Field | Logic |
|-------|-------|
| `request_size` | `body.get("size", 10)` — stored **only** when the operation is `_search`; 0 otherwise |
| `request_template` | Body with all scalar leaf values replaced by `"?"`, then `json.dumps(sort_keys=True)`. `_bulk` uses the NDJSON-aware `scrub_bulk_template` |
| `request_bulk_doc_count` | **`_bulk` only.** NDJSON action lines (`index`/`create`/`update`/`delete`), counted from the *request* so interrupted requests (499) still score accurately |
| `request_body` | The body as stored. Capped at `ALO_REQUEST_BODY_STORE_MAX_BYTES` (default 32768; 0 = no cap); a truncated body gets a `…[TRUNCATED]` suffix and `request_body_truncated = 1` |
| `request_geo_vertex_count` | Total vertices across geo shapes — feeds a continuous bonus (§2.4) |

#### `_msearch` fan-out

`_msearch` is not one record. `analyzer/record_builder/_msearch.py` pairs each NDJSON
header/body with its slot in `responses[]` and emits **one full record per sub-query**,
returned as `{"_msearch_records": [...]}`. Logstash `split`s the array into separate rows.
Three columns correlate them:

| Column | Meaning |
|--------|---------|
| `msearch_request_id` | 12-hex id shared by every sub-query of one `_msearch` |
| `msearch_batch_size` | Number of sub-queries in that request |
| `msearch_sub_query_index` | 0-based position |

Each sub-record carries its own target, template, hits, shards, `took`, and stress score.
Non-msearch rows leave these columns empty/zero.

#### Response body extraction

| Field | Logic |
|-------|-------|
| `response_es_took_ms` | `response_body.took`. **`_bulk` overrides this** with the gateway round-trip time (below) |
| `response_hits` | `hits.total.value` (0 if absent). `hits.total.relation == "gte"` sets the `unbound_hits` indicator |
| `response_shards_total` | `_shards.total`; for `_bulk`, the sum of shard counts across *distinct* indices in `items[]` |
| `response_docs_affected` | bulk: `len(items)` / update_by_query: `updated` / delete_by_query: `deleted` / else 0 |
| `response_status`, `response_size_bytes` | Straight from the gateway payload |

**`_bulk` took override** (`resolve_bulk_took`): ES's `_bulk took` has been wrong on every
version since 8.13 — 8.13–8.15 reported nanoseconds (#111854 / #111863), 8.16+ reads a
200 ms-cached clock so values quantize to {0, 200, 400, …}. Gateway round-trip time is ES
processing plus a tiny network hop, so `_bulk` uses it directly whenever it is > 0. Other
operations keep the upstream `took`.

#### Cost indicators

The analyzer recursively walks the query body and counts structurally expensive patterns.
Raw counts land in `clause_counts_*` columns. Rather than a weighted "complexity" sum
(which would need production data to justify per-clause weights), binary **cost
indicators** produce a `stress_multiplier` applied after the base score. Clause counting
runs only for query-carrying operations: `_search`, `_msearch`, `_count`, `_explain`,
`_validate`, `_update_by_query`, `_delete_by_query`.

**Raw clause counts** (`clause_counts_*`):

| Column | What is counted |
|--------|----------------|
| `bool` | `bool` nodes anywhere in the tree |
| `bool_must` / `bool_should` / `bool_filter` / `bool_must_not` | Clauses across all such arrays |
| `terms_values` | Values across all `terms: {field: [...]}` queries |
| `knn` | `knn` vector similarity queries |
| `fuzzy` | `fuzzy` clauses |
| `geo_bbox` | `geo_bounding_box` / `geo_grid` clauses |
| `geo_distance` | `geo_distance` clauses |
| `geo_shape` | `geo_shape` / `geo_polygon` clauses |
| `agg` | Aggregation definitions at all nesting levels (recursive) |
| `wildcard` | `wildcard`, `regexp`, and `prefix` clauses |
| `nested` | `nested` clauses |
| `runtime_mapping` | Fields in `runtime_mappings` |
| `script` | `script` occurrences anywhere in the body |

**Presence indicators:**

| Indicator | Condition | Multiplier | Rationale |
|-----------|-----------|------------|-----------|
| `has_script` | `script >= 1` | ×1.5 | Per-doc Painless execution, no caching, gated by `allow_expensive_queries` |
| `has_runtime_mapping` | `runtime_mapping >= 1` | ×1.5 | ES docs: same per-doc cost as scripts |
| `has_wildcard` | `wildcard >= 1` | ×1.3 | Full term-dictionary scan |
| `has_nested` | `nested >= 1` | ×1.3 | Sub-query per nested object, distributed join |
| `has_fuzzy` | `fuzzy >= 1` | ×1.2 | Levenshtein automata construction |
| `has_geo` | `geo_distance + geo_shape >= 1` | ×1.2 | Per-doc haversine / polygon intersection. Excludes `geo_bbox` (cheap range check) |
| `has_knn` | `knn >= 1` | ×1.2 | HNSW traversal + vector distance |

**Threshold indicators:**

| Indicator | Condition | Multiplier | Env override |
|-----------|-----------|------------|--------------|
| `excessive_bool` | `bool_must + bool_should + bool_filter + bool_must_not >= 50` | ×1.3 | `COST_INDICATOR_BOOL_THRESHOLD` |
| `large_terms_list` | `terms_values >= 500` | ×1.2 | `COST_INDICATOR_TERMS_THRESHOLD` |
| `deep_aggs` | `agg >= 10` | ×1.3 | `COST_INDICATOR_AGGS_THRESHOLD` |

**Response-derived indicator:**

| Indicator | Condition | Multiplier | Meaning |
|-----------|-----------|------------|---------|
| `unbound_hits` | `hits.total.relation == "gte"` | ×1.3 | ES stopped counting at `track_total_hits` (default 10 000) — the query scanned more than `response_hits` records |

Eleven indicators total. Each flagged indicator writes `cost_indicators_<name> = 1`, its
name into `stress_cost_indicator_names`, and its multiplier into
`stress_cost_indicator_multipliers`. Rows with no indicators get the sentinel name
`["unflagged"]`, so dashboards can group on the array without losing them.

**Multiplier mechanics:**

```
stress_multiplier = product(indicator.multiplier for each active indicator)
```

- No indicators → 1.0× (no change)
- Script + wildcard → 1.5 × 1.3 = 1.95×
- Script + nested + geo → 1.5 × 1.3 × 1.2 = 2.34×
- Max theoretical (all 11) ≈ 9× — rare; 2–3 indicators is typical

Why multiplicative: expensive features genuinely compound (a wildcard inside a nested
query is worse than either alone). This is observability, not rate-limiting — explosion is
a feature.

---

### 2.4 Stress score

Computed in `analyzer/stress/_formulas.py`. All missing fields default to 0. No upper
bound — extreme operations should produce extreme scores.

#### Latency metric: `es_took_ms`

The formulas use `es_took_ms` (ES's self-reported execution time), not `gateway_took_ms`
(full round-trip). Both are stored.

**Why:** `gateway_took_ms` = es_took + HTTP serialization + network transfer. Under
cluster saturation it inflates uniformly for *all* queries — pool exhaustion, TCP buffer
pressure, and queueing are system-wide effects unrelated to any individual query's cost.
Since latency is 40–70 % of the score, that noise would bury the signal from genuinely
expensive queries. (`_bulk` is the deliberate exception, §2.3.)

**Trade-off:** `es_took_ms` is blind to response transfer cost. The `hits` factor
partially compensates. See §9.

#### Baselines

Each normalised input divides the observed value by a baseline; a score of 1.0 means the
query is at baseline across all dimensions.

**Static defaults** (`STRESS_BASELINE_*`):

| Input | Default | Env var | Rationale |
|-------|---------|---------|-----------|
| `es_took_ms` | 100 ms | `STRESS_BASELINE_TOOK_MS` | Slow-log default starts at 500 ms; healthy queries are <100 ms |
| `hits` | 500 docs | `STRESS_BASELINE_HITS` | Moderate result set; scoring + sorting scales with hits |
| `shards_total` | 5 shards | `STRESS_BASELINE_SHARDS_TOTAL` | Typical primary count; each shard is CPU + JVM overhead |
| `docs_affected` | 500 docs | `STRESS_BASELINE_DOCS_AFFECTED` | Bulk / update / delete volume |

> `request_size` (the client's page size) is **not** in the formula. ES scores and ranks
> all matched documents regardless of `size` — query-phase CPU is identical for 10 or
> 10 000 results; `size` only affects the fetch phase. The field is still recorded.

**Dynamic baselines** (`analyzer/_baselines.py`):

When `CLICKHOUSE_URL` is set, the analyzer periodically queries `alo.alo_raw` for the
median (`quantile(0.5)`) of `response_es_took_ms` and `response_shards_total` over recent
`_search` / `_msearch` / `_count` traffic. The score is then self-calibrating: as the
cluster's "normal" shifts, so do the baselines.

| Setting | Default | Env var |
|---------|---------|---------|
| Cache TTL | 60 s | `BASELINE_CACHE_TTL` |
| Query window | `1 HOUR` (ClickHouse interval syntax) | `BASELINE_QUERY_WINDOW` |

Only `took_ms` and `shards_total` refresh dynamically — `hits` and `docs_affected` reflect
query structure rather than cluster state. If ClickHouse is unreachable or returns no
rows, cached values are kept; on first start the static defaults apply. Static
`STRESS_BASELINE_*` overrides always win for the keys they set. Connection settings match
the rest of the stack: `CLICKHOUSE_URL`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`,
`CLICKHOUSE_DATABASE`, `CLICKHOUSE_CA_CERT`, `CLICKHOUSE_INSECURE`.

#### Normalisation

```
norm(value, baseline) = value / baseline
```

No clamping. A query at 2× baseline contributes 2.0, not 1.0.

#### Formulas

Each formula computes a `base` as a weighted sum of normalised inputs. For non-bulk,
non-single-write operations, continuous bonuses and the cost-indicator multiplier are then
applied. Operations fall into five formula classes; unknown operations default to the
single-doc write formula.

| Operations | Formula class |
|------------|---------------|
| `_search`, `_msearch`, `_count`, `_scroll`, `_explain`, `_validate` | query |
| `_bulk` | bulk |
| `_update_by_query`, `_delete_by_query` | by-query |
| `_update` | update |
| `_create`, `index`, `delete`, `get` | single-doc write |

*query:*
```
base  = 0.50·norm(es_took_ms, 100) + 0.15·norm(shards_total, 5) + 0.35·norm(hits, 500)
score = (base + Σ bonuses) × stress_multiplier
```

*`_bulk`:*
```
score = 0.45·norm(es_took_ms, 100) + 0.55·norm(bulk_doc_count, 500)
```
Uses the request-side action-line count so interrupted requests (HTTP 499) still score.
No bonuses, no multiplier.

*by-query:*
```
base  = 0.40·norm(es_took_ms, 100) + 0.35·norm(docs_affected, 500) + 0.25·norm(shards_total, 5)
score = (base + Σ bonuses) × stress_multiplier
```

*`_update`:*
```
base  = 0.60·norm(es_took_ms, 100) + 0.40·norm(shards_total, 5)
score = (base + Σ bonuses) × stress_multiplier
```

*single-doc write:*
```
score = 0.70·norm(es_took_ms, 100) + 0.30·norm(shards_total, 5)
```
No query body → no indicators → no multiplier, no bonuses.

**Continuous bonuses:**

For operations that apply the multiplier (everything except `_bulk`, `_create`, `index`,
`delete`), each clause type contributes a logarithmic bonus once its count exceeds a
threshold:

```
bonus = min(weight × ln(1 + count − threshold), cap)
```

Bonuses are additive to `base` *before* the multiplier, and each firing bonus is recorded
in the `stress_bonuses` Map column.

| Count | Threshold | Weight | Cap | Configurable |
|-------|-----------|--------|-----|--------------|
| `bool_total` (must + should + filter + must_not) | 4 | 0.10 | 0.50 | `STRESS_CLAUSE_THRESHOLD` / `_WEIGHT` / `_CAP` |
| `agg_clause_count` | 3 | 0.10 | 0.50 | `STRESS_AGG_THRESHOLD` / `_WEIGHT` / `_CAP` |
| `wildcard_clause_count` | 1 | 0.10 | 0.50 | — |
| `nested_clause_count` | 1 | 0.10 | 0.50 | — |
| `fuzzy_clause_count` | 1 | 0.10 | 0.50 | — |
| `geo_vertex_count` | 10 | 0.12 | 0.60 | `STRESS_GEO_VERTEX_THRESHOLD` |
| `knn_clause_count` | 1 | 0.10 | 0.50 | — |
| `script_clause_count` | 1 | 0.10 | 0.50 | — |
| `terms_values_count` | 50 | 0.10 | 0.50 | — |

**No double-counting:** bonuses are additive on `base` (continuous, low-count signal);
cost indicators are multiplicative on the final score (binary, high-count signal). At high
counts both fire — correct, since e.g. 15 aggs deserve both.

Every formula input is persisted individually in `stress_components_*` (`took`, `shards`,
`hits`, `docs_affected`, `bulk_doc_count`, `bonus`) and their sum in `stress_base`, so a
dashboard can show exactly what drove a score.

> All weights, multipliers, and thresholds are best-effort initial values grounded in ES
> documentation and benchmarks. They must be tuned against real production data.

---

### 2.5 Prometheus (optional)

Runtime health of ALO itself — distinct from the query-load analytics in ClickHouse.

| Job | Source | Scrape target |
|-----|--------|---------------|
| `gateway` | `nginx-prometheus-exporter` reading gateway `:9145/stub_status` | `nginx-exporter:9113` |
| `gateway-lua` | Lua counters in the gateway | `gateway:9145/metrics` |
| `analyzer` | `prometheus-fastapi-instrumentator` | `analyzer:8000/metrics` |
| `logstash` | `kuskoman/logstash-exporter` reading the monitoring API `:9600` | `logstash-exporter:9198` |
| `clickhouse` | ClickHouse built-in endpoint (commented out by default) | `clickhouse:9363` |

Prometheus stamps a `cluster` external label from `CLUSTER_NAME` (expanded via
`--enable-feature=expand-external-labels`). It **must** match the Logstash `CLUSTER_NAME`
so the Stack Health dashboard's Prometheus panels and its ClickHouse dead-letter panels
line up. In Docker Compose the whole monitoring stack sits behind the `prometheus` profile
(`docker compose --profile prometheus up`); in Helm it is `grafana.prometheusUrl` plus the
per-component `exporter.enabled` / `serviceMonitors.enabled` switches.

---

## 3. Observability record

The analyzer emits a **flat, snake_case JSON object** whose keys map 1:1 to `alo_raw`
columns (`analyzer/record_builder/_assembly.py`). There is no nesting — Logstash inserts
the object as-is with `input_format_skip_unknown_fields=1`.

```json
{
  "timestamp": "2026-03-07 10:00:00.000",
  "cluster_name": "default",

  "identity_username": "alice",
  "identity_applicative_provider": "search-api",
  "identity_user_agent": "elasticsearch-py/8.13.0 (Python/3.11.0; linux)",
  "identity_client_host": "10.0.0.5",
  "identity_labels": {"team": "payments"},

  "request_method": "POST",
  "request_path": "/products/_search",
  "request_operation": "_search",
  "request_target": "products",
  "request_template": "{\"query\":{\"match\":{\"title\":\"?\"}},\"size\":\"?\"}",
  "request_body": "{\"query\": {\"match\": {\"title\": \"shoes\"}}, \"size\": 10}",
  "request_body_truncated": 0,
  "request_size_bytes": 284,
  "request_size": 10,
  "request_geo_vertex_count": 0,
  "request_bulk_doc_count": 0,

  "response_status": 200,
  "response_es_took_ms": 42,
  "response_gateway_took_ms": 67,
  "response_hits": 1500,
  "response_shards_total": 5,
  "response_docs_affected": 0,
  "response_size_bytes": 1920,

  "clause_counts_bool": 0,
  "clause_counts_bool_must": 0,

  "cost_indicators_has_script": 0,
  "cost_indicators_has_wildcard": 0,

  "stress_score": 0.87,
  "stress_base": 0.87,
  "stress_multiplier": 1.0,
  "stress_components_took": 0.21,
  "stress_components_shards": 0.15,
  "stress_components_hits": 1.05,
  "stress_components_docs_affected": 0.0,
  "stress_components_bulk_doc_count": 0.0,
  "stress_components_bonus": 0.0,
  "stress_cost_indicator_count": 0,
  "stress_cost_indicator_names": ["unflagged"],
  "stress_cost_indicator_multipliers": {},
  "stress_bonuses": {}
}
```

(The `clause_counts_*` and `cost_indicators_*` groups are abbreviated above — all 16
counts and all 11 flags are always emitted.)

**With indicators and bonuses active:**

```json
{
  "cost_indicators_has_script": 1,
  "cost_indicators_has_wildcard": 1,
  "stress_multiplier": 1.95,
  "stress_cost_indicator_count": 2,
  "stress_cost_indicator_names": ["has_script", "has_wildcard"],
  "stress_cost_indicator_multipliers": {"has_script": 1.5, "has_wildcard": 1.3},
  "stress_bonuses": {"bool_total": 0.1946, "script_clause_count": 0.1099}
}
```

**Column groups:**

| Prefix | Purpose |
|--------|---------|
| `identity_*` | Who sent the request (incl. the `identity_labels` Map from `x-alo-*` headers) |
| `request_*` | What was requested; `bulk_doc_count` only meaningful on `_bulk`, `size` only on `_search` |
| `response_*` | What ES returned; `docs_affected` feeds stress only on `_update_by_query` / `_delete_by_query` |
| `clause_counts_*` | 16 raw structural counts |
| `cost_indicators_*` | 11 flags, 0/1 |
| `stress_*` | score, base, multiplier, per-input components, bonuses, indicator names + multipliers |
| `msearch_*` | Sub-query correlation, `_msearch` only |
| `cluster_name` | Multi-tenant separation; stamped by the gateway |

**Dead-letter record** (`partial_error_record`) is deliberately minimal: `timestamp`,
`cluster_name`, `error`, `raw` (truncated payload), `request_path`, `request_method`.

---

## 4. ClickHouse schema

`clickhouse_setup/_schema.py` is the single source of truth; `clickhouse_setup/setup.py`
applies it (the `ch-setup` container / Helm Job). All DDL is idempotent.

| Object | Engine | Purpose |
|--------|--------|---------|
| `alo_raw` | `MergeTree` | One row per analyzed request |
| `alo_dead_letter` | `MergeTree` | Events that failed analysis (permissive columns) |
| `alo_summary` | `AggregatingMergeTree` | Pre-aggregated `*State` rows |
| `alo_summary_mv` | Materialized view | Incremental `alo_raw` → `alo_summary` |

**`alo_raw`** — `PARTITION BY toYYYYMMDD(timestamp)`,
`ORDER BY (cluster_name, request_operation, identity_applicative_provider, timestamp)`,
`TTL timestamp + INTERVAL 3 DAY DELETE`. Dashboard filter columns the sort key does not
cover get `bloom_filter(0.01)` skip indexes: `identity_username`, `identity_client_host`,
`request_target`, `request_template`, `stress_cost_indicator_names`. `request_body` is
`String CODEC(ZSTD(3))`.

**`alo_summary`** — dimensions `(time_bucket, request_template, request_operation,
identity_applicative_provider, request_target, cluster_name)`, hourly buckets
(`toStartOfHour`), `PARTITION BY toYYYYMM(time_bucket)`, **120-day** TTL. Aggregate state
columns cover count, sum/avg stress, avg base / multiplier / indicator count, avg
took / gateway-took / hits / shards / docs-affected / request-size, and
`quantiles(0.5, 0.95, 0.99)` state for ES took, gateway took, and score. Grafana finalises
them with the matching `*Merge` functions.

That is the retention model: **raw is short-lived and detailed, summary is long-lived and
pre-aggregated.**

**Unknown operations.** `summary_include_unknown_operation` (Helm:
`tableSettings.summaryExcludeUnknownOperation`) controls whether the MV keeps rows whose
`request_operation` is `unknown`. Default: keep them, so a cluster sending only unparsed
traffic still appears in the summary table and in dashboard variables. Because
`CREATE MATERIALIZED VIEW IF NOT EXISTS` is a no-op on an existing install, `setup.py`
compares the deployed MV definition against the desired one and DROPs + recreates on a
mismatch — **no backfill**; only newly ingested traffic reflects the change.

**Cluster topology.** With `cluster_enabled`, every table becomes a `<name>_local`
(`Replicated*MergeTree`, coordinated by ClickHouse Keeper) plus a `<name>` `Distributed`
front sharded on `cityHash64(cluster_name, request_operation)` (dead-letter shards on
`cityHash64(cluster_name)` — it has no operation column). Clients always reference the
unsuffixed name, so Logstash, the analyzer, and Grafana are unchanged either way.

**Tunables** (`TableSettings`, exposed both as CLI flags and Helm `tableSettings.*`):
retention days per table, partition expressions, full TTL clause overrides (including tier
moves like `... TO VOLUME 'warm'`), extra per-table `SETTINGS`, and the sharding key.

**Post-2.0.0 migrations.** Columns and indexes added after the initial 2.0.0 release are
applied as `ALTER TABLE ... ADD COLUMN/INDEX IF NOT EXISTS`, so upgrades over an existing
deployment are safe. Backfilling a new skip index into existing parts requires an explicit
`ALTER TABLE ... MATERIALIZE INDEX` — deliberately left to the operator.

---

## 5. Dashboards

Five Grafana dashboards, generated from Python builders in `grafana/` and written to both
`grafana/provisioning/dashboards/` (Compose) and `helm/alo/files/` (chart ConfigMap) by
`export_dashboards()`.

| UID | Title | Datasource |
|-----|-------|------------|
| `alo-main` | ALO — Stress Analysis | ClickHouse |
| `alo-main-he` | ALO — Stress Analysis (Hebrew) | ClickHouse |
| `alo-cost-indicators` | Cost Indicators & Query Patterns | ClickHouse |
| `alo-usage` | ALO — Cluster Usage | ClickHouse |
| `alo-health` | ALO — Stack Health | Prometheus + ClickHouse |

The ClickHouse datasource uses the `grafana-clickhouse-datasource` plugin (pinned to
4.15.0 in Compose). Its connection protocol is configurable — `native` (port 9000,
default) or `http` (e.g. 8123 / 80 behind an ingress) — via `grafana.setup.connection.*`
in Helm, or `--protocol` / `--ch-port` / `--ch-path` / `--ch-secure` on `grafana/setup.py`.

Dashboard variable option queries are scoped to the dashboard time range and bounded by
`GROUP BY` (memory cost tracks distinct values, not rows scanned), capped by
`grafana.setup.variableOptionLimit`.

---

## 6. Failure handling

| Scenario | Component | Behavior |
|----------|-----------|----------|
| Logstash down | Gateway | Connect fails within `LOGSTASH_TIMEOUT_MS` → pcall → drop, `alo_gateway_events_dropped_total{reason="logstash_unreachable"}` |
| Lua timer error | Gateway | pcall → silent drop, client unaffected |
| ES upstream down / erroring | Gateway | Nginx returns the upstream error to the client; ALO adds nothing and swallows nothing |
| Analyzer down | Logstash | http filter tags `_httprequestfailure` → `alo_dead_letter` |
| Analyzer raises | Analyzer | HTTP 200 + `partial_error_record` → `alo_dead_letter` |
| Unparsed operation | Logstash | `request_operation == "unknown"` → `alo_dead_letter` |
| ClickHouse insert fails | Logstash | `automatic_retries` (3), then dropped — `save_on_failure => false` |
| Malformed body | Analyzer | Best-effort partial record, HTTP 200 |

**Rule:** failures in the observability pipeline never propagate upstream. The client
always gets its ES response.

---

## 7. Key design decisions

| Decision | Rationale |
|----------|-----------|
| Nginx/OpenResty as gateway | Battle-tested, C-speed proxying, no bottleneck risk |
| Gateway does zero parsing | All logic in Python — easier to test, change, reason about |
| Gateway sends raw headers | No Lua auth/provider extraction; Python handles it |
| Fire-and-forget after response | Zero client latency impact |
| Drop > degrade | No queue in the gateway, instant drop if Logstash is unavailable |
| Logstash as pipeline | HTTP input + filter + CH output — config-driven, no custom code |
| Analyzer is stateless | Single-purpose endpoints, trivially testable |
| ClickHouse as sink | Columnar store sized for high-cardinality analytics; raw TTL + AggregatingMergeTree summary give short-term detail and long-term trend at bounded cost, without touching the monitored ES |
| Flat snake_case record | Column-per-field maps directly onto ClickHouse — no nested-type gymnastics, no mapping explosion |
| Template by scalar-scrubbing | Language-agnostic, no query schema knowledge required |
| `applicative_provider` fallback chain | Works with `X-App-Name`, falls back to User-Agent parsing |
| Stress score has no upper bound | Extreme operations should show extreme scores |
| `_msearch` fanned out per sub-query | A batch's cost is the sum of unrelated queries; one row per sub-query keeps template attribution meaningful |
| Dashboards generated from Python | Compose provisioning and the Helm ConfigMap come from the same builders, so they cannot drift |
| Environment-variable configuration | The same images work across Compose, Helm, and manual deployments |

### Known limitations

**Geo scoring uses vertex count, not area.** For `geo_shape` / `geo_polygon`, the bonus is
based on total vertex count (tessellation CPU), not search area — ES tessellates query
polygons into triangles at query time, and cost scales with vertices. The area mostly
determines how many documents match, which the `hits` component already captures.
Threshold: `STRESS_GEO_VERTEX_THRESHOLD` (default 10).

> **Future recommendation candidate:** geo search area and a `broad_geo` indicator were
> considered and removed — redundant with hits for *scoring*. They remain valuable as
> *recommendation* signals ("you're querying a 500 km radius — intentional?").

**Hit count is best-effort.** ES caps `hits.total.value` at 10 000 unless the client sends
`track_total_hits: true`. ALO records what ES returns, so `response_hits` can be a lower
bound; `unbound_hits` flags exactly those rows. This affects the hits component of the
score and any "total hits" panel — both underreport during heavy scanning. ALO does not
inject `track_total_hits` into proxied requests: it would change query semantics and add
overhead to every search.

**Request bodies are capped.** Beyond `ALO_REQUEST_BODY_STORE_MAX_BYTES` (32 KB default)
the stored `request_body` is truncated (`request_body_truncated = 1`). Analysis — clause
counting, templating, bulk counting — runs on the *full* body before truncation; only the
stored copy is shortened.

---

## 8. Repository structure

```
applicative-load-observability/
├── README.md                        # product overview + quick start
├── docker-compose.yml               # full-stack orchestration (+ prometheus profile)
├── .env.example                     # every tunable env var
├── docs/
│   ├── ARCHITECTURE.md              # this file
│   ├── HELM.md                      # Kubernetes / OpenShift deployment
│   └── PRODUCT_SPEC.md              # original product vision
│
├── gateway/
│   ├── nginx.conf.template          # Nginx config template (envsubst at startup)
│   ├── entrypoint.sh                # Resolves env vars and starts OpenResty
│   └── Dockerfile                   # openresty:1.29.2.2-alpine + lua-resty-http 0.17.2 + nginx-lua-prometheus
│
├── analyzer/
│   ├── main.py                      # FastAPI app wiring
│   ├── _routes.py                   # /analyze, /analyze/bulk, /health
│   ├── _metrics.py                  # Prometheus instrumentation
│   ├── _logging.py                  # dictConfig
│   ├── _baselines.py                # dynamic baselines from ClickHouse
│   ├── _decompression.py            # gzip/zlib/base64 body recovery
│   ├── parser/                      # _headers, _path, _request_body, _response_body, _geo
│   ├── record_builder/              # _builder, _assembly, _msearch, _stress, _models, _schema
│   ├── stress/                      # _clause_counting, _cost_indicators, _formulas
│   └── Dockerfile
│
├── logstash/
│   ├── Dockerfile                   # logstash:8.13.0 + filter-http + output-clickhouse
│   ├── logstash.yml / pipelines.yml
│   └── pipeline/observability.conf  # http in → analyzer → clickhouse out
│
├── clickhouse_setup/
│   ├── setup.py                     # DDL runner (ch-setup image / Helm Job)
│   ├── _schema.py                   # schema-as-code: tables, MV, TTL, indexes
│   ├── _client.py                   # minimal HTTP client
│   └── Dockerfile
│
├── grafana/
│   ├── setup.py                     # datasource + dashboard provisioning (files or API)
│   ├── _dashboards.py               # panel builders + export_dashboards()
│   ├── _dashboard_builders.py       # main / main-he / cost-indicators / usage
│   ├── _health_dashboard.py, _health_panels.py, _datasource.py, _strings.py
│   ├── provisioning/                # datasources/*.yml + dashboards/*.json
│   ├── cheat_sheet.md, cheat_sheet_he.html
│   └── Dockerfile
│
├── prometheus/prometheus.yml        # scrape config for the optional monitoring profile
├── shared/                          # HTTP client, data generators, stats helpers
├── helm/alo/                        # Helm chart (see docs/HELM.md)
├── tools/stress/                    # load generator, 11 workload profiles
└── tests/                           # unit, integration, challenges (see tests/help.md)
```

**To run the full stack:**

```bash
docker compose up -d
```

Compose does **not** run Elasticsearch — set `ELASTICSEARCH_HOST` to the cluster you want
to monitor, then point clients at the gateway (`localhost:9200`) instead of ES directly.

**Environment variables** (Compose defaults shown; override for Helm / manual deployments):

| Variable | Default | Used by | Purpose |
|----------|---------|---------|---------|
| `ELASTICSEARCH_HOST` | `elasticsearch:9200` | Gateway | Upstream host:port of the **monitored** ES |
| `GATEWAY_PORT` | `9200` | Gateway | Port the gateway listens on |
| `LOGSTASH_URL` | `http://logstash:8080/` | Gateway | Where the async notification is POSTed. **The Helm gateway reads the same value from `PIPELINE_URL`** — the two configs use different names for it |
| `LOGSTASH_TIMEOUT_MS` | `1000` | Gateway | Timeout for that POST |
| `WORKER_CONNECTIONS` | `1024` | Gateway | Max concurrent connections per worker |
| `CLIENT_BODY_BUFFER_SIZE` | `64m` | Gateway | In-memory request body buffer before spooling to disk |
| `DNS_RESOLVER` | `127.0.0.11` | Gateway | DNS resolver (auto-detected in K8s) |
| `CLUSTER_NAME` | `default` | Gateway, Logstash, Prometheus | Tenant label stamped on every record / series |
| `LOGSTASH_HTTP_PORT` | `8080` | Logstash | HTTP input port |
| `ANALYZER_URL` | `http://analyzer:8000/analyze` | Logstash | Analyzer endpoint |
| `LS_JAVA_OPTS` | `-Xms512m -Xmx512m` | Logstash | JVM heap |
| `LS_CH_FLUSH_SIZE` / `LS_CH_DEAD_LETTER_FLUSH_SIZE` | `5000` / `1000` | Logstash | Rows per ClickHouse insert |
| `LS_CH_IDLE_FLUSH_TIME` | `5` | Logstash | Seconds before flushing a partial batch |
| `LS_CH_AUTOMATIC_RETRIES` / `LS_CH_POOL_MAX` | `3` / `10` | Logstash | Insert retries / connection pool |
| `LS_CH_SETTINGS` | `input_format_skip_unknown_fields=1,async_insert=1,wait_for_async_insert=0` | Logstash | ClickHouse per-insert settings |
| `CLICKHOUSE_URL` | `http://clickhouse:8123` | Logstash, analyzer, ch-setup | ClickHouse HTTP endpoint |
| `CLICKHOUSE_DATABASE` | `alo` | all CH clients | Database name |
| `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` | `default` / *(empty)* | all CH clients | Credentials |
| `CLICKHOUSE_CA_CERT` / `CLICKHOUSE_INSECURE` | *(empty)* / `false` | analyzer, ch-setup | TLS |
| `CLICKHOUSE_CLUSTER` | *(empty)* | ch-setup | Enables `ON CLUSTER` + Distributed tables |
| `ALO_REQUEST_BODY_STORE_MAX_BYTES` | `32768` | Analyzer | Cap on stored `request_body` (0 = unlimited) |
| `BASELINE_CACHE_TTL` / `BASELINE_QUERY_WINDOW` | `60` / `1 HOUR` | Analyzer | Dynamic baseline refresh |
| `STRESS_BASELINE_*` | see §2.4 | Analyzer | Static baseline overrides |
| `COST_INDICATOR_*_THRESHOLD` | see §2.3 | Analyzer | Indicator thresholds |
| `STRESS_CLAUSE_*` / `STRESS_AGG_*` / `STRESS_GEO_VERTEX_THRESHOLD` | see §2.4 | Analyzer | Bonus tuning |
| `GRAFANA_PORT` / `GRAFANA_ADMIN_PASSWORD` | `3000` / `admin` | Grafana | UI |

---

## 9. Future implementation ideas

- `response_size_bytes` as a stress factor — the formulas use `es_took_ms`, which is blind
  to transfer cost: a query with `es_took=30ms` returning 5 MB imposes real serialization
  load the score ignores. It would add signal for heavy documents, missing source
  filtering, highlight / `script_fields` inflation, and large aggregation payloads.
  Deferred because it is partly redundant with hits, penalises "fat" indexes regardless of
  query quality, and has a skewed distribution that makes baseline selection hard. If
  undetected response-heavy patterns show up in production, add it to `StressContext` with
  a low weight (0.05–0.10) carved from the latency share.
- Cost indicator threshold and multiplier tuning against real firing rates and their
  correlation with `response_es_took_ms`.
- `search_type` classification (`agg` / `knn` / `geo` / `text` / `simple`). Deferred: naive
  top-level detection misclassifies expensive clauses nested inside a `bool`. Requires
  recursive detection with a priority order.
- Per-operation write weights — `_create`, `_doc` PUT, and `_doc` DELETE share a formula
  despite different read depth (PUT is a pure write; DELETE reads version/seq_no;
  `_update` reads the full `_source`).
- Upsert detection — `_update` with `upsert` / `doc_as_upsert` follows a conditional
  create-vs-update path; probabilistic cost modeling once hit/miss rates are observable.
- Auto-generated vs user-provided `_id` — `POST /<index>/_doc` skips the existence check;
  `PUT /<index>/_doc/<id>` does not. Detectable from the path segment after `_doc`.
- Bulk action breakdown — count `index`/`create`/`update`/`delete` actions within a `_bulk`
  for a sharper signal than the flat action-line count.
- `has_highlight` — extra per-result CPU.
- Depth-weighted agg scoring — weight aggs by nesting depth instead of a flat node count.
- Deep pagination scoring — `log10(1 + from) * 4`; ES must score and discard all preceding
  docs.
- Scroll detection — `has_scroll` indicator; scroll holds long-lived shard-level search
  contexts across requests.
- `timed_out` — query hit the ES timeout threshold.
- Separate `cpu_stress_score` and `memory_stress_score`, once real data allows
  resource-type attribution.
- Join queries (`has_child` / `has_parent`) and `function_score`.
- Gateway response time panels — dropped from the main dashboard because
  `response_gateway_took_ms` includes gateway↔ES network time (infrastructure noise rather
  than query cost). Worth re-adding if network issues become a diagnostic concern.

---

## Note: why not HAProxy?

OpenShift's built-in HAProxy ingress controller **cannot replace the OpenResty gateway**.
The gateway needs to capture full request and response bodies and fire async POST
notifications after the response is sent — HAProxy Lua lacks reliable response body
capture, has no post-response async phase, and doesn't support request body template
scrubbing. See the original analysis in git history (`docs/haproxy-gateway-analysis.md`,
removed in 1.15.0).
