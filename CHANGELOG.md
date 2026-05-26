# Changelog

## 2.0.0 — ClickHouse migration (breaking)

### Breaking changes

| Old | New |
|-----|-----|
| `elasticsearch.*` values | removed — analytics sink is now ClickHouse |
| `kibana.*` values | removed — Kibana support dropped |
| `indexSettings.*` | renamed to `tableSettings.*` (`rawRetentionDays`, `summaryRetentionDays`, `rawPartitionBy`, `summaryPartitionBy`) |
| `pipelineMode` value | removed — Logstash is the only supported pipeline |
| `dashboardUI` value | removed — Grafana is the only supported UI |
| `nifi.*` values | removed — NiFi support dropped |
| image tag `kibana-setup-*` | renamed to `ch-setup-*` |
| `ELASTICSEARCH_URL` env var | replaced by `CLICKHOUSE_URL`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DATABASE` |

### Analytics sink: Elasticsearch → ClickHouse

- **ClickHouse 24.8 LTS** replaces Elasticsearch as the analytics sink.
- Logstash now writes via `logstash-output-clickhouse` plugin (HTTP insert, `JSONEachRow`).
  Auth via `X-ClickHouse-User`/`X-ClickHouse-Key` headers; `http_hosts` (array) instead of `hosts`.
- Timestamp format in `ObservabilityRecord` uses CH-compatible `"YYYY-MM-DD HH:MM:SS.mmm"` (no ISO-8601 T/Z).
- Schema: `alo_raw` (`MergeTree`), `alo_dead_letter` (`MergeTree`), `alo_summary` (`AggregatingMergeTree`) + incremental materialized view replacing the ES continuous transform.
- All `ObservabilityRecord` fields are now flat snake_case columns (e.g. `identity_username`, `response_es_took_ms`).
- **Cluster mode** (`clickhouse.cluster.enabled`): `ReplicatedMergeTree` local tables + `Distributed` front tables. Clients always write/read through the unsuffixed table name.
- **ch-setup job** (replaces `kibana-setup`): idempotent schema DDL via `CREATE … IF NOT EXISTS`; controlled by per-table flags (`clickhouse.setup.rawTable`, `.summaryTable`, `.materializedView`, `.deadLetterTable`).

### Grafana

- Datasource: `grafana-clickhouse-datasource` plugin (UID `alo-clickhouse`). `GF_INSTALL_PLUGINS` set automatically.
- All panels rewritten to `rawSql` against `alo.alo_raw` / `alo.alo_summary`.
- Array column `stress_cost_indicator_names` uses `arrayJoin()` / `hasAny()`.
- Template variables use `SELECT DISTINCT … FROM alo.alo_raw`.

### Removed

- Elasticsearch templates (`helm/alo/templates/elasticsearch/`)
- Kibana templates (`helm/alo/templates/kibana/`)
- NiFi templates (`helm/alo/templates/nifi/`)
- `elasticsearch-exporter` Compose service
- `kibana` Compose service
- Compose volume `es-data` → `ch-data`

### New values

```yaml
clickhouse:
  external.enabled / external.url / external.host / external.auth / external.tls
  cluster.enabled / cluster.name / cluster.shards / cluster.replicas / cluster.shardingKey
  setup.enabled / setup.rawTable / setup.summaryTable / setup.materializedView / setup.deadLetterTable
logstash:
  clickhouseOutput.flushSize / .deadLetterFlushSize / .idleFlushTime / .automaticRetries
  clickhouseOutput.poolMax / .chSettings
tableSettings:
  rawRetentionDays / summaryRetentionDays / rawPartitionBy / summaryPartitionBy
```

### Chart
- Helm chart `version` + `appVersion` → **2.0.0**.

---

## 1.22.1

### Helm chart: per-resource setup flags (replaces `dashboardUI` enum)

**Breaking:** `dashboardUI: kibana|grafana|none` removed. Kibana and Grafana are now toggled independently via `kibana.enabled` and `grafana.enabled`.

**ES resources now run in their own Job (`es-setup`, hook-weight 1).** Previously ES ILM, mappings, index templates, and the summary transform ran inside the Kibana setup job — meaning choosing `dashboardUI: grafana` silently skipped all ES resource creation. Fixed.

**New per-resource flags** under `elasticsearch.setup`, `kibana.setup`, and `grafana.setup` — all default to `true`:

| Values path | Controls |
|---|---|
| `elasticsearch.setup.ilm` | ILM policies |
| `elasticsearch.setup.componentTemplate` | Component template (field mappings) |
| `elasticsearch.setup.indexTemplates` | Composable index templates |
| `elasticsearch.setup.summaryTemplate` | Summary index template |
| `elasticsearch.setup.transform` | Summary transform (stop/delete/create/start) |
| `kibana.setup.dataView` | Kibana data view |
| `kibana.setup.savedSearches` | Saved searches |
| `kibana.setup.dashboards` | Dashboard import/rebuild |
| `kibana.setup.rebuild` | Rebuild via API + re-export ndjson (default: false) |
| `grafana.setup.datasource` | Elasticsearch datasource(s) in Grafana |
| `grafana.setup.dashboards` | Grafana dashboards |

**Migration:** remove `dashboardUI` from values overrides; set `kibana.enabled` / `grafana.enabled` directly.

### Grafana: per-section flags + CA cert file support

- `grafana.setup.datasource` flag added (mirrors `kibana.setup.*` pattern). Controls `--datasource` / `--no-datasource` in both API and provision modes.
- `grafana/setup.py`: `do_api_setup` and `do_provision` accept `datasource=` and `dashboards=` kwargs; CLI exposes `--datasource` / `--no-datasource` and `--dashboards` / `--no-dashboards` via `BooleanOptionalAction`.
- `grafana/_datasource.py`: `generate_datasource_yaml` now accepts `es_username`, `es_password`, `es_insecure`, `es_ca_cert` — CA cert value is read from disk if a file path is given, else treated as a literal PEM string. Provisioned YAML gains `basicAuth`, `tlsSkipVerify`, and `tlsCACert` blocks as appropriate.
- `grafana/setup.py` `_build_datasource_body`: same file-read logic for `es_ca_cert` (API path).
- Helm grafana-setup Job: passes `--no-datasource` / `--no-dashboards` from values; mounts ES CA cert secret at `/etc/ssl/es/ca.crt` via `ES_CA_CERT` env var when `elasticsearch.external.tls.caSecret` is set. Job now renders when either `datasource` or `dashboards` is enabled.

### Logstash: configurable JVM heap + extra env vars

- `logstash.javaOpts` (default `"-Xms512m -Xmx512m"`) passed as `LS_JAVA_OPTS` to the container. Fixes OOM on memory-constrained nodes — override via `--set logstash.javaOpts="-Xms1g -Xmx1g"`.
- `logstash.extraEnv` (default `[]`) — arbitrary env vars appended to the Logstash container for settings not exposed by the chart.
- `docker-compose.yml`: logstash service gains `LS_JAVA_OPTS=${LS_JAVA_OPTS:--Xms512m -Xmx512m}` to match.

### Default values changes

- `kibana.enabled` default changed `true` → `false`; `grafana.enabled` default changed `false` → `true`.
- `gateway.service.type` and `grafana.service.type` default changed `ClusterIP` → `LoadBalancer`.
- `analyzer.replicas` default changed `2` → `1`.
- ES, Logstash, Analyzer, Gateway resource requests/limits reduced to lower dev-cluster footprint (ES: 250 m/512 Mi req, 1/1 Gi limit; Analyzer: 50 m/64 Mi req, 200 m/128 Mi limit; Gateway: 50 m/64 Mi req, 200 m/256 Mi limit; Logstash: 100 m/512 Mi req, 500 m/1 Gi limit).
- `elasticsearch.javaOpts` default `−Xms512m −Xmx512m` → `−Xms256m −Xmx256m`.

### Chart
- Helm chart bumped to `0.13.0`; `appVersion` → `1.22.0`.

## 1.21.3

### Analyzer

- **Module split** — `analyzer/main.py` (147 lines, 4 concerns) broken into focused `_`-prefixed modules: `_logging.py` (dictConfig), `_metrics.py` (Prometheus instrumentation), `_routes.py` (`/analyze`, `/analyze/bulk`, `/health` handlers). `main.py` is now a ~30-line orchestrator.
- **`python -m analyzer.main` entry point** — `def main() / if __name__ == "__main__"` block added so the server can be started directly without the uvicorn CLI. Passes `log_config=None` to prevent uvicorn from overwriting the custom dictConfig.
- **Package split** — `parser.py`, `record_builder.py`, `stress.py` each converted to a sub-package (`parser/`, `record_builder/`, `stress/`) for better internal cohesion.
- **`_baselines.py` error handling** — replaced bare `assert` with `RuntimeError`, narrowed broad `except Exception` to explicit `(urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError)`.
- **`_decompression.py` error handling** — specific exception types replace broad `except Exception: pass`; added module logger; renamed `blob` to `raw_bytes` for clarity.

### Gateway

- **`b64_if_binary` helper** — DRY refactor of the gzip-detection / base64-encode logic into a local Lua function. Eliminates the duplicated `header_filter_by_lua_block` and unifies request-body and response-body handling under a single code path.

### Chart

- Helm chart bumped to `0.12.1`; `appVersion` → `1.21.3`.
- All 6 images (analyzer, logstash, gateway, kibana-setup, grafana-setup, stress) rebuilt and pushed at `1.21.3`.

## 1.21.2

### Gateway

- **gzip response body handling** — when Elasticsearch returns a `Content-Encoding: gzip` response, the raw binary bytes are now base64-encoded with a `gzip+b64:` prefix before JSON-serialisation. Previously `cjson.encode` silently replaced every non-UTF-8 byte with U+FFFD, producing corrupted `response_body` fields and causing the analyzer to crash or route records to the dead-letter index.
- **gzip request body handling** — same treatment for clients that send `Content-Encoding: gzip` request bodies (e.g. Logstash bulk writes). The compressed bytes are base64-encoded before entering the Logstash payload so `bulk_doc_count`, request template, and clause counts are parsed correctly from the decompressed NDJSON.
- Both fixes use OpenResty's built-in `ngx.encode_base64` — no extra dependencies or Dockerfile changes required.

### Analyzer

- **`gzip+b64:` fast path in `decompress_body`** — detects the gateway prefix, base64-decodes, and inflates in Python. Moves all decompression complexity into Python (where it's easy to maintain) rather than Lua.
- **`UnicodeEncodeError` guard** — non-Latin-1 characters in response bodies (e.g. residual `\ufffd` from older gateway versions) no longer crash the decompressor; they are passed through as-is.
- **`cluster_name` in `partial_error_record`** — error records produced during analyzer failures now always carry `cluster_name`, so the Logstash dead-letter index pattern `logs-alo.dead_letter-%{cluster_name}` can always be interpolated without leaving placeholder literals in the index name.

### Grafana

- **CPU panel** — ES CPU usage now filters by `cluster=~"$cluster"` instead of `instance`, and the legend uses `{{name}}` for readable series labels.
- **Health dashboard drilldown** — the CPU panel links to the language-appropriate health dashboard (`alo-health` or `alo-health-he`) based on the `lang` parameter.

### Chart

- Helm chart bumped to `0.12.0`; `appVersion` → `1.21.2`.
- All 6 images (analyzer, logstash, gateway, kibana-setup, grafana-setup, stress) rebuilt and pushed at `1.21.2`.

## 1.21.0

### Analyzer
- **`request.bulk_doc_count`** — new field populated only for `_bulk` operations. Counts NDJSON action lines (`index`, `create`, `update`, `delete`) directly from the request body, so the value is accurate even for interrupted requests (HTTP 499) where the response body is empty or partial.
- **`_bulk` stress formula now uses `request.bulk_doc_count`** instead of `response.docs_affected`. Bulk operations that previously scored 0 impact (due to missing response items on 499s) now produce accurate stress scores. `response.docs_affected` is unchanged — still recorded for all operations and still used in `_update_by_query` / `_delete_by_query` scoring.

### Dashboards
- **"Write Volume"** panels renamed to **"Bulk Write Volume"** and switched to `request.bulk_doc_count` (sum/avg) in both the main and usage dashboards.
- **"Avg Documents per Write"** renamed to **"Avg Documents per Bulk"**.
- **New panel: "Status Code by Operation"** — line chart in the Volume & Throughput section showing request count split by `request.operation × response.status` (e.g. `_search / 200`, `_bulk / 499`). Grafana only; built with nested terms aggregation.

### Logstash / Helm
- **Dead letter `request.body` standardisation** — for events that fail analysis (`_httprequestfailure`), the flat `request_body` gateway field is now renamed to `[request][body]` before indexing into the dead-letter index, matching the naming convention of the main observability record.

### Elasticsearch Schema
- Added `request.bulk_doc_count` (`long`) to the component template (raw indices).
- Added `request.bulk_doc_count` (`double`) to the summary index template.
- Added `request.bulk_doc_count` avg aggregation to the summary transform.

### Chart
- Helm chart bumped to `0.11.0`; `appVersion` → `1.21.0`.

## 1.20.0

### Pipeline
- **Byte-safe HTTP compression support** — The pipeline now safely preserves gzip/zlib-compressed payloads containing raw binary data (e.g. from Logstash `http_compression: true`) without JSON-codec corruption.
  - **Gateway**: Unchanged, safely proxies raw bytes via `cjson.encode()`.
  - **Logstash**: Input codec changed from `json` to `plain { charset => "ISO-8859-1" }` to prevent UTF-8 corruption of high bytes (0x80-0xFF). A new fast C-level ruby `gsub` filter escapes high bytes as `\u00XX` literals before the `json` filter parses the payload.
  - **Analyzer**: Replaced Python's `surrogateescape` decoding with `latin-1` mapping to recover the exact bytes received by Logstash. The fallback path for uncompressed bodies now correctly decodes the recovered bytes as UTF-8, ensuring non-ASCII text (e.g., Hebrew, Arabic, CJK) correctly survives the Latin-1 round-trip.

### Tests
- Replaced all `surrogateescape` usage in the testing suite with `latin-1` to mirror the new pipeline behavior.
- Added tests for mixed ASCII/Hebrew payloads to verify byte-safety guarantees and UTF-8 recovery on non-compressed bodies.

### Chart
- Helm chart bumped to `0.10.0`; `appVersion` → `1.20.0`.
- All 6 images (analyzer, logstash, gateway, kibana-setup, grafana-setup, stress) rebuilt and pushed at `1.20.0`.

## 1.19.0

### Analyzer

- **HTTP compression support** — request/response bodies forwarded by the gateway are now decompressed in the analyzer when they're gzip- or zlib-encoded (e.g. clients using `http_compression: true` such as Logstash). `analyzer/_decompression.py` sniffs the magic bytes and inflates; `main.py` reads the incoming HTTP body with `errors="surrogateescape"` so binary bytes survive the JSON envelope round-trip. Without this, compressed payloads ended up indexed as garbage strings.
- **`_bulk` `took` now sourced from the gateway timing.** Elasticsearch `_bulk took` has been wrong on every release since 8.13: 8.13–8.15 returned nanoseconds (#111854 / #111863) and 8.16+ reads from a 200ms-cached clock so values are quantized to `{0, 200, 400, …}`. The analyzer now ignores `took` for bulk and uses gateway round-trip time, which sidesteps both bugs. Non-bulk operations are unchanged.
- **`request.body_truncated` flag** — when the stored `request.body` is shortened to fit the ES keyword limit, the record now carries `request.body_truncated: true`. Parsing (template, clause counts, docs_affected, hits, size_bytes) always runs on the *full* body received from the gateway — only the persisted field is trimmed. Lets dashboards distinguish "we have the full body" from "this is a partial copy" instead of silently misleading viewers.
- **`ALO_REQUEST_BODY_STORE_MAX_BYTES` env var** — analyzer-side cap on the *stored* `request.body` field is now tunable. Default `32000`, interpreted as the size of the stored string including the truncation suffix — sits safely under the 32 766-byte ES keyword field limit so the default works out of the box without manual tuning. Set to `0` to disable truncation entirely (requires the `request.body` mapping to allow values above 32 766 bytes). Wired through `helm/alo/values.yaml` (`analyzer.requestBody.storeMaxBytes`), `values.schema.json`, the analyzer Deployment, and a commented `docker-compose.yml` example.

### Gateway

- **Large request bodies no longer disappear.** Two changes combine to guarantee the full request body always reaches the analyzer: (1) default `client_body_buffer_size` raised from `10m` → `64m` so realistic bulk payloads stay in memory; (2) when nginx spools a body above the cap to a temp file, the `log_by_lua_block` falls back to `ngx.req.get_body_file()` and slurps the file, so we never drop the body. Previously, anything above `10m` left the analyzer with an empty `request_body` — losing template, clause counts, and `docs_affected` (which surfaced as `docs_affected: 0`). The buffer is lazy-allocated per request so the bump costs nothing for normal traffic. Mirrored in the Helm `gateway/configmap.yaml`.
- **`CLIENT_BODY_BUFFER_SIZE` env var** — nginx in-memory buffer is now tunable. Wired through `gateway/entrypoint.sh` (envsubst), `docker-compose.yml`, and `helm/alo/values.yaml` (`gateway.clientBodyBufferSize`) + `values.schema.json`. Default `64m`. Bump only if disk I/O on the spooled-body path becomes a bottleneck.

### Grafana

- **Dashboard filter links stay on the current dashboard.** Pie / bar / table / raw-doc filter links previously hard-coded `dashboard_uid="alo-main"`, so clicking a filter on Cost Indicators or Cluster Usage redirected users to the Stress Analysis dashboard. Replaced with Grafana's built-in `${__dashboard.uid}` variable so the URL resolves to whichever dashboard the user is viewing.

---

## 1.18.1

### Hebrew Stress Analysis dashboard

- **Bilingual main dashboard** — `alo-main` (English) and `alo-main-he` (Hebrew) generated from a single `_dashboard_builders.build_main_dashboard(lang)` builder + source-string-keyed translation table (`grafana/_strings.py`). Adding a panel updates both variants; only the strings dict is duplicated.
- **Top-bar toggle** — each variant carries a header link (`עברית` / `English`) pointing to the other, with `includeVars: true, keepTime: true` so time range and dashboard filters persist across the switch.
- **Translated**: dashboard title + description, every panel title (incl. ES CPU), all `i`-tooltip descriptions, row headers, table column labels, variable sidebar labels, and the Dashboard Guide panel (`grafana/cheat_sheet_he.html` — HTML mode + Unicode bidi controls so RTL survives Grafana's sanitizer).
- **Helm chart** — `alo-main-he.json` mounted via `configmap-dashboards.yaml`.

### Main dashboard polish

- **Doc ID column** added to *Top 10 Heaviest Operations* (raw-document table). Source field `_id` exposed via the existing organize transform.
- **Sum / Avg split** — *Documents Matched by Queries*, *Write Volume*, and *Request Size* each split into a Sum panel (left half) plus an Avg panel (right half). Sum = throughput / amplification; Avg = per-request shape (selectivity, batch size, payload size).

### Dashboard parity (Kibana ↔ Grafana)

- **Grafana — Top 10 Heaviest Operations** added to the main dashboard (raw-document table ranked by `stress.score`, with per-cell Filter-by links for Application / Operation / Target / Cost Indicators).
- **Latency percentiles everywhere** — Top 10 Templates, Top 10 Cost Indicators, Score Breakdown, and Requests by Application tables now expose P50 / P95 / P99 ES latency instead of a single average. The "ES Latency by Operation" timeseries becomes a unified **ES Latency** panel with Avg / P50 / P95 / P99 series (both dashboards).
- **Grafana panel descriptions** — every data panel across the main, cost-indicators, and usage dashboards now carries a hover description matching Kibana's.
- **Kibana — gateway latency removed** from cheat sheet, table columns, and panel descriptions. Kept only ES latency (the supported signal).
- **Kibana — `include_missing` pie bucket dropped** (dead code: analyzer always emits `"unflagged"` for requests with zero cost indicators).

### Chart
- Helm chart bumped to `0.8.1`; `appVersion` → `1.18.1`.

## 1.18.0

All 6 images (analyzer, logstash, gateway, kibana-setup, grafana-setup, stress) rebuilt and pushed at `1.18.0`. 1.17.1–1.17.5 only bumped a subset of images per release, so the dashboard work landing under 1.17.5 never reached users running the analyzer/logstash/gateway tags. Every version reference is now consistent: `pyproject.toml`, `helm/alo/Chart.yaml` (`appVersion` and chart `version`), `helm/alo/values.yaml`, `docker-compose.yml`, `CONTRIBUTING.md`, `README.md`, `tools/stress/benchmarking.md`. No code changes since 1.17.5.

## 1.17.5

### Dashboard

- **Configurable datasources** — all Grafana panels use `$datasource` template variable. Switch ES instance from the dashboard dropdown.
- **Rate by Template** panel added to Cluster Usage dashboard.
- **Measurement units** — latency panels show "ms", size panels show auto-scaled bytes.
- Various panel fixes (percentile types, pie chart dimensions, status code field type).
- **Cost Indicators dashboard** — removed redundant "Historical Trends" collapsed row. The three timeseries (Avg Base Score by Template, Avg Multiplier by Template, Avg Cost Indicators by Application) are now first-class panels in the Trends section. With the unified `logs-alo.*-*,alo-summary` datasource (1.17.0) every panel already serves long windows, so the "(Historical)" labeling was misleading.
- **Prometheus datasource opt-in (Compose)** — `grafana/provisioning/datasources/prometheus.yml` is now generated by `grafana/setup.py` based on `PROMETHEUS_URL` (or `--prometheus-url`), defaulting to empty (skipped). Mirrors the Helm chart's `grafana.prometheusUrl` opt-in. Re-running with the env var unset removes any previously generated file.

## 1.17.2

### Helm Chart

- **Per-service route TLS overrides** — each route (gateway, kibana, etc.) can override the global TLS termination, certs, and annotations. Shared `alo.routeTls` and `alo.routeAnnotations` helpers.
- **Grafana route** — new `grafana/route.yaml` template + `route.grafana` values.
- **Grafana admin password from Secret** — `grafana.adminPasswordExistingSecret` for deployment and setup job.
- **Prometheus datasource fix** — configurable `grafana.prometheusUrl` (was referencing nonexistent `alo-prometheus` service). Empty = skip.
- **Grafana ES datasource** — updated to combined `logs-alo.*-*,alo-summary` pattern + summary datasource in configmap.
- **Gateway lua-prometheus** — added `lua_shared_dict`, counter init, `metric_events_total`/`metric_events_dropped` increments, and `/metrics` endpoint to Helm configmap (was Docker Compose only).
- **Gateway cluster_name** — added to Lua payload in Helm configmap (was missing).
- **Gateway probes** — optional liveness/readiness TCP probes (disabled by default).
- **Gateway proxyConnectTimeout** — added to values.yaml (was only `| default` in template).
- **Logstash exporter** — `workingDir: /tmp` to suppress `.env` file error.
- **Logstash _msearch fan-out** — added to Helm configmap, fixed output condition (`else if` guard).
- **Index performance settings** — `indexSettings.shards`, `.replicas`, `.refreshInterval`, `.rawRetention`, `.rolloverMaxAge`, `.summaryRetention` passed as CLI args to kibana setup job.
- **Grafana setup ES auth** — ES credentials and TLS settings passed to Grafana setup job for datasource creation.
- **PodDisruptionBudgets** — optional PDB for gateway, logstash, analyzer (disabled by default).
- **Image tags** — all updated to 1.17.1.
- **values.schema.json** — updated for all new fields.

## 1.17.1

### Dashboard

- Removed extra panels that were incorrectly merged into main dashboard (Latency Percentiles section, Score Composition section). These belong in CI dashboard / Usage dashboard respectively.
- Removed unused `mk_pie_filters` from Grafana helpers.
- Fixed stale `build_historical_dashboard` reference in Grafana export function.

## 1.17.0

### Dashboard

- **Historical dashboard removed** — percentile and score composition panels merged into the main Stress Analysis dashboard as collapsed rows. Three dashboards now (Stress Analysis, Cost Indicators, Cluster Usage).
- **Seamless long-term retention** — primary datasource queries `logs-alo.*-*,alo-summary` (combined index pattern). Raw data provides full resolution for 3 days; summary data seamlessly fills in for up to 120 days. ~2% noise from overlap is negligible and documented.
- **ES Latency panel upgraded** — shows Avg, P50, P95, P99 on a single chart (was avg-only).
- **Volume panels dual-query** — fallback dashed line from summary `sum(count)` ensures request volume survives raw data expiry.
- **Percentile panels** (p95/p99 ES latency, gateway latency, stress score) added to main dashboard from summary transform data.
- **Score Composition section** (base score, multiplier, cost indicator count by template/app) added to main dashboard.
- Grafana and Kibana dashboards fully synced.

### Infrastructure

- **ES summary transform overhauled** — output uses same nested field paths as raw index (`stress.score`, `response.es_took_ms`, `request.template`, etc.) enabling shared data views. Added p50/p95/p99 percentile aggregations for latency and stress score. Transform `retention_policy` auto-deletes summary docs older than 120 days.
- **ILM simplified** — all raw indices now use uniform 3-day rollover + 3-day delete with `parse_origination_date`. Removed per-operation retention tiers (was 90d/30d/60d).
- **Lite index removed** — TSDS approach abandoned in favor of the summary transform. Removed lite ILM, index template, Logstash clone filter, and Helm clone config.
- **Helm Logstash parity** — added `_msearch` fan-out logic and fixed output condition (`else if [@metadata][ds_dataset]` instead of bare `else`).
- Dead code cleanup: removed unused `mk_pie_filters`, `mk_ts_response`, `mk_summary_timeseries`, `mk_summary_table`, and stale flat field name references.

## 1.16.0

### Analyzer

- **`cost_indicator_multipliers`** field added to stress section — stores per-indicator multiplier values (e.g., `{"has_script": 1.5}`) for full score drilldown in dashboards.
- **`cluster_name` passthrough** — analyzer reads `cluster_name` from the gateway payload and includes it in the record. Enables centralized Logstash serving multiple clusters.
- **`POST /analyze/bulk`** endpoint for batch analysis (array in, array out, per-item error isolation).

### Dashboard

- **CI dashboard rework** — Score Composition stacked bar chart, Base vs Final Score table, raw metrics alongside weighted values in Score Breakdown table (ES Latency ms, raw shards, raw hits). Section headers added.
- **Pipeline Bottleneck section** in Stack Health — flow rates (input/filter/output), queue depth, plugin time per event, analyzer in-progress & latency, ES thread pool queues and rejected operations.
- **Historical Trends dashboard** (standalone) — queries the hourly summary index for lightweight long-term trend analysis. Sections: Stress Trends, Score Composition, Volume & Latency, Top Offenders.
- Historical sections added to Stress Analysis and Cost Indicators dashboards.
- Stack Health: split CPU & Queue Backpressure, added memory/JVM panels for Analyzer + Logstash, instance variable filters on all panels.
- DLQ table fixed (switched to `logs` metric for proper columns).
- Gateway: Events Dropped + Event Delivery Rate panels.
- All Kibana dashboards renamed with `ALO —` prefix for consistency.

### Infrastructure

- **Gateway lua-prometheus** — `alo_gateway_events_total` and `alo_gateway_events_dropped_total{reason}` Prometheus counters. Reasons: `logstash_unreachable`, `logstash_error_<status>`, `pcall_error`, `timer_failed`. Exposed on `/metrics` endpoint (port 9145).
- **`cluster_name` moved to gateway** — Logstash no longer sets it from env var. Gateway sends it in the payload, enabling a single centralized Logstash for multiple clusters.
- **ES summary transform** — continuous transform aggregating raw records into hourly summaries per (template, operation, app, target, cluster). ~4x doc size reduction. Summary index persists after raw data ILM deletion.
- **`pipeline.workers: 4`** for Logstash parallel processing.
- Summary data view + datasource for Kibana and Grafana.
- ServiceMonitor for gateway lua-metrics in Helm chart.
- Prometheus `gateway-lua` scrape job.

### Documentation

- README rewritten as project entry point (architecture diagram, quick start, key concepts).
- Docs consolidated: `haproxy-gateway-analysis.md` and `grafana-support.md` folded into ARCHITECTURE.md and HELM.md.
- Benchmarking guide moved to `tools/stress/benchmarking.md`.
- `.env.example` expanded with all env vars grouped by component.
- Stale image tags fixed (1.6.0 → 1.15.0).

---

## 1.15.0

### Analyzer

- **`POST /analyze/bulk` endpoint** — accepts a JSON array of payloads, returns a JSON array of results with 1:1 positional correspondence. Per-item error isolation: one bad payload produces a partial error record without affecting the rest of the batch.
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

- **Logstash `pipeline.workers: 4`** — enables parallel event processing across 4 worker threads, increasing throughput ~4x for the HTTP filter call path.
- **`pyproject.toml` with `uv`** — migrated from `requirements.txt`; dev dependencies managed via optional `[dev]` extra.
- **Logstash healthcheck** added; unknown operations routed to dead-letter queue.
- **Docker base images pinned** — uv 0.11.1, OpenResty 1.29.2.2-alpine.
- **CI aligned to Python 3.12** (matching Docker images); standard pre-commit hooks added (`trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-merge-conflict`).
- Grafana/Kibana Dockerfiles narrowed `COPY` scope; `.dockerignore` extended.

### Helm

- **`pipeline.workers` configurable** — new `logstash.pipeline.workers` value (default 4) rendered into logstash.yml via ConfigMap.
- **Fixed DLQ routing for unknown operations** — Helm ConfigMap was missing the `if op == "unknown"` check, causing unknown operations to index into `logs-alo.unknown-*` instead of routing to the dead letter queue.

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
