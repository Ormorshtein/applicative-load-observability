# ALO v3 Redesign — From Logstash to Kafka

> **Status:** proposal, approved in direction (2026-11-08). Not implemented yet.
> **Scope:** phase 1 only. Phase 2 (storing full content, e.g. in S3) is out of scope,
> but the design keeps the door open for it.
> **Audience:** the people building and operating ALO. Read §1–§4 for the "what and why",
> §5 for the gateway deep-dive (the part we are most worried about), §8 for how releases work.

---

## Contents

1. [TL;DR](#1-tldr)
2. [Why we are changing anything](#2-why-we-are-changing-anything)
3. [Today vs. target](#3-today-vs-target)
4. [Who is responsible for what](#4-who-is-responsible-for-what)
5. [The gateway strip — deep dive](#5-the-gateway-strip--deep-dive)
6. [Analyzer, Kafka and ClickHouse](#6-analyzer-kafka-and-clickhouse)
7. [The event contract](#7-the-event-contract)
8. [How a gateway release works](#8-how-a-gateway-release-works)
9. [Phase 2 — the extension point](#9-phase-2--the-extension-point)
10. [Work plan](#10-work-plan)
11. [Risks and how we contain them](#11-risks-and-how-we-contain-them)
12. [Open questions](#12-open-questions)
13. [Decision log (Q&A)](#13-decision-log-qa)

---

## 1. TL;DR

- **Logstash goes away.** The gateway writes to Kafka. The analyzer consumes from Kafka,
  scores and writes results back to Kafka. ClickHouse reads its input straight from Kafka.
- **The gateway shrinks the data before it leaves.** Document content (what clients
  index, and what ES returns) never leaves the gateway — only sizes and structure do.
  ALO answers *"where in the cluster is the load coming from?"*, not *"what is in the
  documents?"*.
- **The gateway stays dumb and cheap.** It never parses document-sized JSON on the
  request path. Heavy work runs in an nginx thread pool, off the event loop, and under
  load the gateway *degrades to metadata-only* rather than slowing anyone down.
- **The smart logic lives in the analyzer**, which is Python and easy to change and
  release. The gateway's behaviour is mostly driven by config, so most changes do not
  need a new gateway image.
- **Kafka already exists and is shared by all our ECK environments.** There are exactly
  **two topics**: one for gateway (nginx) events and one for analyzer results. Both are
  created by hand, on-prem, before this version is deployed. ALO creates nothing in
  Kafka and does not ship Kafka in Helm. Docker Compose gets a single-node Kafka for
  local dev and CI only.
- **Data freshness budget is generous:** up to 5 minutes from request to visible in
  Grafana is fine. This lets us batch for efficiency everywhere behind the gateway.
  It is *not* a budget for the proxy itself — see §5.1.
- Released as **v3.0.0** — a clean cut. v2.1.x stays available.

---

## 2. Why we are changing anything

### Decision criteria (from the redesign meeting)

| Criterion | The question we asked |
|---|---|
| **Operations & attention** | How much attention can we afford to spend running this? Target: no more than ~2 days per sprint. |
| **Flexibility** | How easy must it be to ship changes? We are not yet sure the product is "done", so changes must stay cheap. |
| **Breadth of data** | How much data actually needs to reach the analyzer to answer our questions? |
| **Resources** | Do we have a lot of compute/memory to spend? No — resource use must be smart. |

### Principles that came out of it

1. **ALO is an investigation tool.** Only the NGINX reverse proxy is critical, because
   it sits in front of the clusters and must never hurt their availability or latency.
2. **Everything behind the proxy may be imperfect.** It is fine if releasing it is
   somewhat involved, as long as day-to-day it doesn't eat our attention.
3. **Prefer smart resource use.** Don't move megabytes we are going to throw away.

### What is wrong with today's pipeline under those criteria

- The gateway buffers **every full response in Lua memory with no cap**, then
  `cjson.encode`s the full request and response bodies **inside the nginx event loop**.
  A burst of large responses costs memory and CPU on the very component that must stay
  fast. (See `gateway/nginx.conf.template`, `body_filter_by_lua_block` and the
  `log_by_lua_block` timer.)
- We ship full documents across the network twice (gateway → Logstash → analyzer) only
  for the analyzer to read `took`, `hits.total`, `_shards` and a few counters from them.
- Logstash is one more JVM to size and run, and its ClickHouse output plugin has been
  archived since 2021 (see `docs/RATIONALE.md` §2).
- The gateway Lua is written twice — once in `gateway/nginx.conf.template` and once in
  `helm/alo/templates/gateway/configmap.yaml`. Every logic change must be made in both.
- All request headers, including `Authorization`, are forwarded downstream. With Logstash
  that was transient; in a Kafka topic it would be **stored for the topic's retention
  period**. This must not carry over.

---

## 3. Today vs. target

### Today (v2.1.x)

```
Clients ──→ Gateway (OpenResty) ──→ Elasticsearch
                 │  async HTTP POST — FULL request + response bodies, all headers
                 ▼
             Logstash ──http──→ Analyzer (FastAPI /analyze) ──→ record
                 │                                (back into Logstash)
                 ▼
             ClickHouse (alo_raw → alo_summary) ──→ Grafana
```

Logstash does three jobs today: receive from the gateway, call the analyzer
synchronously per event, and route the result (`_msearch` split, dead-letter, batching
into ClickHouse).

### Target (v3.0.0) — "Kafka only"

```
Clients ──→ Gateway (OpenResty) ──────────────────────→ Elasticsearch
                 │                                       (unchanged; the only critical path)
                 │  after the response is sent:
                 │  capture (bounded) → strip (thread pool) → async produce
                 ▼
     [Kafka]  topic 1 — gateway events     (small, stripped events, all ECK environments)
                 │
                 ▼  one consumer group, e.g. "alo-analyzer"
             Analyzer (Python): parse, score, split _msearch, mark failures
                 │
                 ▼
     [Kafka]  topic 2 — analyzer results   (records AND dead letters, told apart by a "kind" field)
                 │
                 ▼  ClickHouse Kafka engine table + two materialized views
             ClickHouse (alo_raw, alo_dead_letter → alo_summary) ──→ Grafana
```

There is one shared Kafka cluster with two topics, both created by hand on-prem before
deployment. Topic names are configuration (`kafka.topics.events`,
`kafka.topics.results`); ALO never creates or alters topics. The connection settings for
the analyzer's consumer and producer stay separate in config, which costs nothing and
keeps the option of splitting clusters later.

### Deployment topology (confirmed)

Because the topics are shared by all ECK environments, the natural layout is:

```
ECK env 1:  gateway ──┐
ECK env 2:  gateway ──┼──→ topic 1 ──→ analyzer (central) ──→ topic 2 ──→ ClickHouse (central) ──→ Grafana
ECK env N:  gateway ──┘
```

- Each environment installs the chart with only the gateway enabled
  (`analyzer.enabled=false`, `clickhouse.enabled=false`, `grafana.enabled=false`). The
  chart already supports per-component `enabled` flags.
- One central install runs the analyzer, ClickHouse and Grafana.
- Every gateway **must** set a unique `CLUSTER_NAME`. It is the only thing that tells
  environments apart in a shared topic. The chart will refuse an empty or default value
  when Kafka output is enabled.
- If more than one analyzer deployment ever consumes topic 1, they must share **one**
  consumer group, or every event is processed twice.

### Step-by-step flow

1. A client sends a request to the gateway, which proxies it to Elasticsearch exactly as
   today.
2. While the response streams back to the client, the gateway keeps only a **small,
   bounded** piece of it (see §5).
3. After the response is fully sent, the gateway builds a small event. Large bodies are
   stripped in a **thread pool**, so the nginx event loop is not blocked. The event is
   handed to an **async Kafka producer** buffer.
4. The analyzer consumes topic 1, builds observability records (same scoring code as
   today), splits `_msearch` into one record per sub-query, and produces to topic 2. Each
   message carries `kind: "record"` or `kind: "dead_letter"`.
5. ClickHouse reads topic 2 with its Kafka table engine. Two materialized views route by
   `kind` into `alo_raw` and `alo_dead_letter`. `alo_summary` is fed from `alo_raw`
   exactly as today.
6. Grafana is unchanged, except the Stack Health dashboard (Logstash panels are replaced
   by Kafka-related ones).

---

## 4. Who is responsible for what

The meeting notes left one question open: *do we throw away irrelevant data in NGINX or in
the analyzer?* The answer is **both, with a clear split**:

| Component | Owns | Never does |
|---|---|---|
| **Gateway** | **Volume.** Strips content by *size and structure*: drops document bodies, drops response content, keeps request structure and query bodies. Coarse, fast, rule-driven. | Never interprets queries. Never parses document-sized JSON on the event loop. Never waits for anything downstream. |
| **Analyzer** | **Meaning and privacy.** All parsing, scoring, templates, cost indicators. Final guarantee that no document content is stored — whatever slips past the gateway (e.g. a small `_update` body kept for its script) is reduced here before it is written. | Never sits in the request path. |
| **Kafka** | Buffering, decoupling, replay. | — |
| **ClickHouse** | Storage, batching of inserts (via the Kafka engine), aggregation. | — |

Rule of thumb: **if a change is about *what a request means*, it goes in the analyzer.
If it is about *how many bytes we move*, it goes in the gateway.**

---

## 5. The gateway strip — deep dive

The team's two concerns:

1. A process that strips messages could slow the proxy and hurt users.
2. Changing logic there could be hard — both the code and the deployment.

This section answers concern 1. §8 answers concern 2.

### 5.1 The one fact everything depends on

nginx runs a small number of worker processes. Each worker has **one event loop** that
serves *thousands* of connections. "Async" in OpenResty means *non-blocking I/O*, not
*free CPU*. Any CPU-heavy Lua code, even in a timer that runs "after the response",
runs on that same loop and **delays every other request on that worker**.

So the rule for the gateway is:

> **On the event loop, only do work that is constant-size or C-speed and spread across
> chunks. Anything proportional to a large body runs in a thread pool or doesn't run at all.**

**Two different "latencies" — don't mix them up:**

| | What it is | Budget |
|---|---|---|
| **Data freshness** | Time from a request until it is visible in Grafana. | **Up to 5 minutes** (agreed). The design should be well under a minute: producer flush ~1 s, analyzer batches of a few seconds, ClickHouse Kafka-engine flush ~7.5 s by default. We can trade freshness for efficiency (bigger batches) freely. |
| **Proxy overhead** | Extra time the gateway adds to *every* Elasticsearch call our users make. | **Close to zero.** This is the one that affects users. Everything in this section exists to protect it, and the CI latency gate (§8.3) enforces it. **Agreed threshold: ≤ 2 ms added at p99.** |

Today's gateway breaks this rule: it buffers whole responses and `cjson.encode`s whole
bodies on the event loop. **The new design does strictly less event-loop work than
today.**

### 5.2 Where each piece of work runs

| nginx phase | On the client's critical path? | What we do there | Cost |
|---|---|---|---|
| `access` | Yes (once per request) | Classify the operation from method + URI (string match). | µs |
| `body_filter` (per response chunk) | **Yes** | Count bytes; copy the first few KB of the response (bounded); for `_msearch` only, scan for anchor strings with `string.find` (C-speed). After the head is captured and there is no scanning to do, we **don't touch the chunk at all**. | O(chunk) at memchr speed; zero once done |
| `log` (after response is sent) | No, but on the event loop | Snapshot small fields; for a body in memory under the inline limit, take it; for a spooled body, **hardlink** the temp file (one syscall). Schedule a timer. | µs, plus a memcpy of ≤ a few MB |
| timer (event loop) | No, but on the event loop | Small bodies: strip inline (bounded size). Large bodies: hand off to the **thread pool** and yield (non-blocking). Then push the event into the Kafka producer buffer. | µs |
| **thread pool** (`ngx.run_worker_thread`) | **No, and not on the event loop** | The heavy work: stream-read and strip large bulk/update bodies, inflate gzip request bodies. | Proportional to body size, on a separate OS thread |
| Kafka producer flush (timer, cosocket) | No | Batch small events and send them over a non-blocking socket. | Small; events are KB-sized |

### 5.3 How requests are stripped

The gateway picks a **strategy per operation**. The mapping is a small rule table in
config (§8.2), not code.

| Operation (from method + path) | Strategy | What leaves the gateway |
|---|---|---|
| `_bulk` | `bulk_summary` | A summary instead of the body: per group of (action, `_index`, `pipeline`, routing yes/no, `_id` provided/auto) → count, total doc bytes, max doc bytes. Plus per-group counters for `update` lines: how many carry a `script`, how many use `doc_as_upsert`. **No document content.** |
| `PUT/POST …/_doc[/id]`, `…/_create/id` | `doc_size` | `{"_alo_doc_bytes": N}`. Constant work: we only need the length. |
| `POST …/_update/id` | `update` | The "settings" are kept (`script`, `doc_as_upsert`, `scripted_upsert`, `detect_noop`); `doc` and `upsert` are replaced by their byte sizes. Small bodies are parsed; bodies over a limit only get a plain-text check for those keys. |
| `_search`, `_count`, `_msearch`, `_update_by_query`, `_delete_by_query`, index create/settings/mappings, everything else | `keep` | The body as-is (it is the query, not data), up to `ALO_REQ_KEEP_MAX_BYTES` (default 1 MB). Above that: the first part plus a `request_truncated` flag and the true size. |

Why "summary" for bulk instead of "replace each document with its size": a 100k-document
bulk would still produce ~100k action lines (≈10 MB) if we kept every line. That is too
big for a Kafka message and useless for the analyzer, which only needs counts, actions,
targets and sizes. The grouped summary keeps every **setting** that matters (index,
pipeline, routing, id style, scripts) at a near-constant size, no matter how large the
bulk is.

**Gzip request bodies** (common for bulk from Beats/Logstash clients) are inflated
**inside the thread pool**, as a stream, with `lua-ffi-zlib`. They are never inflated on
the event loop.

### 5.4 How responses are stripped

We decided to drop response content **entirely** (hits, aggregations, `_source`,
suggestions, etc.) and record only the **total response size**, not per-document sizes.
What the analyzer needs from a response is a handful of small fields
(`took`, `timed_out`, `_shards`, `hits.total`, `errors`, `updated`/`deleted`), and ES
writes them **at the start** of the response, before any content.

So the gateway **never buffers the response**. It keeps:

| Captured | How | Bound |
|---|---|---|
| **Total size** | `$body_bytes_sent` in the log phase — no chunk inspection needed | — |
| **Head** | The first bytes of the response, cut at the first "stop anchor" (`"hits":[`, `"_source":`, `"aggregations":`) or at `ALO_RESP_HEAD_BYTES` (default 8 KB), whichever comes first. Because ES puts metadata first, this captures the metadata and **no document content**. | ≤ 8 KB |
| **`_msearch` windows** | Each sub-response has its own metadata in the middle of the stream. While streaming, `string.find` looks for the anchor `{"took":` and copies a short window (default 256 B, also cut at stop anchors) after each match. | ≤ `max_windows × window` (default 2,000 × 256 B = 512 KB) |
| **Gzip flag** | From the response `Content-Encoding`. | — |

How each operation gets its numbers from this:

| Operation | Needs | Where it comes from |
|---|---|---|
| `_search`, `_count`, `_update_by_query`, `_delete_by_query`, single-doc ops | `took`, `timed_out`, `_shards.total`, `hits.total`, `updated`/`deleted` | Head |
| `_bulk` | `took`, `errors`, item count, shards per index | Head has `took`/`errors` and the first items (shards per index; all items for one index report the same shard copies). The item count equals the action count from the request summary. |
| `_msearch` | Per sub-query `took`, `hits.total`, `_shards` | One window per sub-response |

**Gzip responses:** we can't scan compressed bytes, and inflating on the event loop is
exactly what we must avoid. So for gzip responses the gateway sends the **compressed
head** (base64) and the analyzer inflates just that prefix (zlib can inflate a prefix).
`_msearch` windows aren't available for gzip responses; those sub-queries still get full
request-side data (template, clause counts, cost indicators) but their per-sub response
numbers are marked partial. This is measured (`strip_partial` flag and metric), not hidden.

### 5.5 Handling many huge requests and responses at once

The questions here are memory, CPU and stalls. Each one is bounded:

| Risk | What bounds it |
|---|---|
| **Huge responses** (e.g. 100 MB of hits) | Never buffered. Per request we hold ≤ 8 KB of head (+ ≤ 512 KB of windows for `_msearch`). 100 concurrent huge responses ≈ 1 MB, not 10 GB. |
| **Huge request bodies in memory** | nginx already buffers request bodies before proxying (`lua_need_request_body on` — same as today). We lower `client_body_buffer_size` from 64 MB to **8 MB** by default: bodies above that spool to disk (an `emptyDir`), so huge bulks don't sit in worker memory. |
| **Copying huge bodies on the event loop** | Bodies ≤ 8 MB: one memcpy (≈1 ms or less). Spooled bodies: **not copied at all.** In the log phase we `link()` nginx's temp file to our own path (one syscall). nginx deletes its name when the request ends; ours stays readable. The thread stream-reads it in chunks and deletes it. A sweeper timer removes leftovers after a crash. |
| **CPU of stripping huge bulks** | Runs on thread-pool threads, never on the event loop. Stream-processed in fixed-size chunks, so memory per job is bounded regardless of body size. |
| **Too many jobs at once** | The thread pool has a fixed size and a bounded queue (`thread_pool alo_strip threads=4 max_queue=256`, per worker, configurable). There is also a per-worker **in-flight bytes budget**. If either is full, the event is sent **metadata-only** (sizes, timings, operation, path — no body) and counted under `alo_gateway_events_degraded_total{reason="strip_queue_full"\|"inflight_budget"}`. |
| **Kafka slow or down** | The producer buffer is bounded (`max_buffering`). When it is full, events are dropped and counted (`alo_gateway_events_dropped_total{reason="kafka_buffer_full"}`). The proxy never waits on Kafka. |
| **A bug in the strip code** | Every step runs under `pcall`. On error: send metadata-only, count `reason="strip_error"`. A strip bug cannot break proxying. |
| **Something unexpected in production** | **Kill switch:** `ALO_CAPTURE_MODE=off` turns the gateway into a pure proxy (no Lua capture at all). See §8.4. |

**Degradation ladder.** Under pressure the gateway gives up observability detail in this
order, and **never** gives up proxy latency:

```
full stripped event  →  metadata-only event  →  dropped event (counted)  →  (kill switch) pure proxy
```

This matches our existing durability stance (`docs/RATIONALE.md` §2): random loss is
acceptable as long as it is measured. Systematic loss (a whole class of traffic
disappearing) is not, which is why large bodies are handled in the thread pool rather
than skipped.

**Expected cost — to be confirmed by the step-0 spike (§10), not promised here:**
- Event loop, per request: tens of µs typical; ≤ ~1 ms for an 8 MB in-memory body.
- Thread pool: roughly a few hundred MB/s per thread for plain bulk stripping, and less
  for gzip. Measured on our own fixtures before we commit.

### 5.6 Pseudo-code

This is intentionally close to the real thing. Module names match the planned layout
`gateway/lua/alo/*.lua`.

#### nginx.conf — thin, no logic inline

```nginx
# main context
thread_pool alo_strip threads=${ALO_STRIP_THREADS} max_queue=${ALO_STRIP_MAX_QUEUE};

http {
    lua_package_path "/usr/local/openresty/site/lualib/?.lua;;";
    lua_shared_dict alo_state 1m;          # runtime capture mode, counters
    lua_need_request_body on;              # same as today
    client_body_buffer_size ${CLIENT_BODY_BUFFER_SIZE};   # default 8m
    client_body_temp_path /tmp/nginx/client_body;         # same fs as /tmp/nginx/alo_spool

    init_worker_by_lua_block { require("alo.init").worker() }   # metrics, producer, sweeper

    server {
        listen ${GATEWAY_PORT};
        location / {
            access_by_lua_block        { require("alo.capture").access() }
            header_filter_by_lua_block { require("alo.capture").header_filter() }
            body_filter_by_lua_block   { require("alo.capture").body_filter() }
            log_by_lua_block           { require("alo.capture").log() }
            proxy_pass http://elasticsearch;
            # ... unchanged proxy settings ...
        }
    }
}
```

#### Hot path — `alo/capture.lua`

```lua
local rules  = require "alo.rules"      -- operation → strategy table, built from config at startup
local find, sub = string.find, string.sub

function _M.access()
    if mode() == "off" then return end                    -- kill switch: no ctx, nothing else runs
    local ctx = ngx.ctx
    ctx.alo  = true
    ctx.op   = rules.classify(ngx.var.request_method, ngx.var.uri)   -- plain string matching
    ctx.rule = rules.for_op(ctx.op)
end

function _M.header_filter()
    local ctx = ngx.ctx
    if not ctx.alo then return end
    ctx.gzip_resp = (ngx.header["Content-Encoding"] or ""):find("gzip", 1, true) ~= nil
    ctx.head, ctx.head_len = {}, 0
end

function _M.body_filter()
    local ctx = ngx.ctx
    if not ctx.alo or ctx.capture_done then return end    -- after this: zero work per chunk

    local chunk = ngx.arg[1]                               -- only materialised while we still need it
    if chunk == "" then return end
    local rule = ctx.rule

    -- 1) head: copy until head_bytes or a stop anchor, whichever comes first
    if not ctx.head_done then
        local room  = rule.head_bytes - ctx.head_len
        local piece = sub(chunk, 1, room)
        local stop  = (not ctx.gzip_resp) and first_stop_anchor(piece)   -- string.find, plain
        if stop then piece = sub(piece, 1, stop - 1) end
        ctx.head[#ctx.head + 1] = piece
        ctx.head_len = ctx.head_len + #piece
        ctx.head_done = stop ~= nil or ctx.head_len >= rule.head_bytes
    end

    -- 2) windows (only _msearch, only uncompressed): scan with string.find, copy short windows
    if rule.windows and not ctx.gzip_resp then
        scan_windows(ctx, chunk, rule.windows)   -- keeps a (#anchor-1)-byte tail for chunk boundaries;
                                                 -- stops when max_windows reached
    end

    ctx.capture_done = ctx.head_done and not (rule.windows and not ctx.windows_full)
end

function _M.log()
    local ctx = ngx.ctx
    if not ctx.alo then return end

    local ev = {                                           -- small fields only
        event_id   = uuid(),
        ts         = ngx.req.start_time(),
        method     = ngx.var.request_method,
        path       = ngx.var.uri,
        op         = ctx.op,
        status     = ngx.status,
        upstream_ms= tonumber(ngx.var.upstream_response_time),
        req_bytes  = tonumber(ngx.var.content_length) or 0,
        resp_bytes = tonumber(ngx.var.body_bytes_sent) or 0,
        identity   = identity_from_headers(),   -- username decoded from Basic auth, user-agent,
                                                -- x-app-name, x-alo-* only. NO Authorization header.
        resp_head  = table.concat(ctx.head or {}), resp_gzip = ctx.gzip_resp,
        resp_windows = ctx.windows,
        cluster    = CLUSTER_NAME,
    }

    -- request body: pick the cheapest way to hand it over
    local body = nil
    if ctx.rule.strategy ~= "doc_size" then               -- doc_size needs only the length
        body = ngx.req.get_body_data()                     -- in memory: ≤ client_body_buffer_size
        if not body then
            local f = ngx.req.get_body_file()
            if f then body = { spooled = hardlink_into_spool(f) } end   -- one link() syscall, no copy
        end
    end

    local ok = ngx.timer.at(0, process, ev, body)
    if not ok then metric_dropped("timer_failed") end
end
```

#### Off the request path — `alo/process.lua` (timer)

```lua
function process(premature, ev, body)
    if premature then cleanup(body) return end
    local rule = rules.for_op(ev.op)

    local ok, stripped, meta = pcall(function()
        if rule.strategy == "doc_size" then
            return '{"_alo_doc_bytes":' .. ev.req_bytes .. '}'           -- constant work

        elseif rule.strategy == "keep" and not is_spooled(body)
               and #body <= cfg.req_keep_max then
            return body                                                   -- no work

        elseif small_enough_inline(body, rule) then                        -- e.g. ≤ 16 KB
            return strip.run(rule.strategy, body, cfg)                    -- bounded inline work

        else
            if not budget.reserve(size_of(body)) then return nil, "inflight_budget" end
            -- runs on a pool thread; this coroutine yields, the event loop keeps serving
            local th_ok, out, m = ngx.run_worker_thread(
                "alo_strip", "alo.strip", "run", rule.strategy, body, cfg)
            budget.release(size_of(body))
            if not th_ok then return nil, "strip_queue_full" end         -- pool/queue saturated
            return out, m
        end
    end)

    if ok and stripped then
        ev.request_body, ev.request_meta = stripped, meta
    else
        ev.degraded = (not ok) and "strip_error" or meta                  -- metadata-only event
        metric_degraded(ev.degraded)
    end

    producer.send(ev)          -- appends to the async buffer; never blocks; drops + counts when full
end
```

#### In the thread pool — `alo/strip.lua` (`bulk_summary`)

```lua
-- Runs inside ngx.run_worker_thread: its own Lua VM on an OS thread.
-- No access to request context; only pure Lua / FFI modules (cjson, lua-ffi-zlib).
function _M.run(strategy, body, cfg)
    if strategy == "bulk_summary" then return bulk_summary(open_stream(body, cfg), cfg) end
    if strategy == "update"       then return update_settings(read_bounded(body, cfg), cfg) end
    if strategy == "keep"         then return keep_truncated(open_stream(body, cfg), cfg) end
end

-- open_stream: yields fixed-size chunks (e.g. 256 KB) from either an in-memory string
-- or a spooled file; inflates on the fly if the request was gzip/deflate. Bounded memory.

local function bulk_summary(stream, cfg)
    local groups, carry, expect_doc, cur = {}, "", false, nil
    for chunk in stream do
        local buf, pos = carry .. chunk, 1
        while true do
            local nl = find(buf, "\n", pos, true)
            if not nl then break end
            local len = nl - pos
            if len > 0 then
                if expect_doc then
                    -- document line: we only need its length (and, for update, two flags)
                    cur.count, cur.bytes = cur.count + 1, cur.bytes + len
                    if len > cur.max then cur.max = len end
                    if cur.action == "update" then
                        if find(buf, '"script"', pos, true) and before(nl) then cur.scripts = cur.scripts + 1 end
                        if find(buf, '"doc_as_upsert":true', pos, true) and before(nl) then cur.upserts = cur.upserts + 1 end
                    end
                    expect_doc = false
                else
                    -- action line: tiny (~100 B) — safe to decode
                    local a  = cjson.decode(sub(buf, pos, nl - 1))
                    local action, meta = next(a)                -- "index" | "create" | "update" | "delete"
                    cur = group_for(groups, action, meta._index, meta.pipeline,
                                    meta.routing ~= nil, meta._id ~= nil)
                    if action == "delete" then cur.count = cur.count + 1
                    else expect_doc = true end
                end
            end
            pos = nl + 1
        end
        carry = sub(buf, pos)                                    -- partial line → next chunk
        if #carry > cfg.max_line_bytes then carry = "" ; mark_oversized_line(cur) end
    end
    return cjson.encode({ _alo_bulk_summary = { groups = list(groups) } })
end
```

#### Kafka producer — `alo/producer.lua`

```lua
-- created once per worker in init_worker (lua-resty-kafka, Kong fork — see §5.7)
producer = kafka_producer:new(cfg.brokers, {
    producer_type   = "async",            -- buffered; send() never blocks
    flush_time      = cfg.flush_ms,        -- e.g. 1000 ms (freshness budget is minutes)
    batch_num       = cfg.batch_num,       -- e.g. 500 events
    max_buffering   = cfg.max_buffering,   -- hard cap on buffered events per worker
    error_handle    = function(topic, _, queue, idx, err, retryable)
        metric_dropped("kafka_send_failed", queue_len(queue, idx))
    end,
    ssl             = cfg.tls_enabled,     -- SASL_SSL vs SASL_PLAINTEXT
    sasl_config     = {                    -- same credentials the Java JAAS line holds
        mechanism = "SCRAM-SHA-256",
        user      = os.getenv("ALO_KAFKA_USERNAME"),
        password  = os.getenv("ALO_KAFKA_PASSWORD"),
    },
})

function _M.send(ev)
    local msg = cjson.encode(ev)                           -- small: a few KB
    if #msg > cfg.max_message_bytes then                   -- belt and braces
        msg = cjson.encode(metadata_only(ev, "oversize")) end
    local ok, err = producer:send(cfg.topic, nil, msg)     -- nil key → spread across partitions
    if not ok then metric_dropped("kafka_buffer_full") end
end
```

#### What the analyzer does with it (Python)

```python
def parse_response(ev) -> ResponseMetrics:
    head = ev["resp_head"]
    if ev.get("resp_gzip"):
        head = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(b64decode(head), 64_000)
    m = tolerant_fields(head)            # took, timed_out, _shards.total, hits.total{value,relation},
                                         # errors, updated, deleted, first bulk items
    if ev["op"] == "_msearch":
        subs = [tolerant_fields(w) for w in ev.get("resp_windows") or []]
        # windows[0] is the top-level {"took":...}; the rest map 1:1 to sub-queries
    return metrics_from(m, subs)

def parse_bulk_request(ev) -> BulkInfo:
    groups = json.loads(ev["request_body"])["_alo_bulk_summary"]["groups"]
    return BulkInfo(doc_count=sum(g["count"] for g in groups),
                    actions={g["action"] for g in groups},
                    targets={g["index"] for g in groups}, ...)
```

### 5.7 Why `lua-resty-kafka` and not an nginx Kafka module

The natural first idea is a ready-made nginx plugin that writes to Kafka. We looked at
the options:

| Option | What it is | Fit for us |
|---|---|---|
| **Built into nginx / OpenResty** | Nothing. Neither open-source nginx nor OpenResty ships Kafka support. | — |
| **`kaltura/nginx-kafka-log-module`** | A C module (librdkafka) that sends a message per request in the **log phase**, built from nginx variables. | ✗ Its last push was in Aug 2021; open issues on SSL setup and on a `dlopen` failure (missing `rd_kafka_flush` symbol). Has to be compiled into a custom nginx build. And see the timing problem below. |
| **`brg-liuwei/ngx_kafka_module`** | A C module that turns a `location` into an HTTP→Kafka endpoint: it takes a POST body and produces it. | ✗ Built to *receive* data over HTTP, not to mirror proxied traffic. We would still need our own Lua to call it, i.e. an extra local HTTP hop. |
| **`lua-resty-kafka`** | The Kafka client of the OpenResty world, pure Lua on non-blocking sockets. Installed into the stock OpenResty image with a package manager; no compiling. It is the library behind Kong's `kafka-log` plugin and Apache APISIX's `kafka-logger`, so it is in effect *the* nginx-family Kafka plugin. | ✓ Chosen. Kong's fork supports **SCRAM-SHA-256**, which is what we use. |

**The timing problem** is the deciding reason, not just maintenance. A log-phase module
sends its message *during the log phase*, from values available at that moment. Our
stripped event is only ready *later*, after the thread pool finishes (§5.2). To use such
a module we would have to either:

- strip inline in the log phase, on the event loop — exactly the latency risk we are
  designing away; or
- send the unstripped data — exactly the volume we are trying not to move.

`lua-resty-kafka` lets us produce **when the event is ready**, from the same timer that
waits for the thread pool.

**Release simplicity matters too.** A C module means building nginx/OpenResty from source
with the module and librdkafka, redoing that on every OpenResty upgrade, and dealing with
ABI or symbol mismatches like the open `dlopen` issue above. That is the opposite of
the "easy to release" goal in §8. `lua-resty-kafka` is a few Lua files copied into the
image, the same way `lua-resty-http` is installed today.

**What we give up:** librdkafka produces from its own thread and has built-in
compression and idempotent delivery. We don't need these. Our messages are a few KB, and
occasional loss is accepted and counted.

**About SCRAM-SHA-256 "with JAAS":** JAAS is the *Java* way of supplying the credentials
(`org.apache.kafka.common.security.scram.ScramLoginModule required username="…" password="…";`).
Non-Java clients take the same three things directly: mechanism `SCRAM-SHA-256`, username
and password. That applies to the gateway (`sasl_config`), the analyzer (librdkafka:
`sasl.mechanism` / `sasl.username` / `sasl.password`) and ClickHouse. One Kubernetes
Secret holds the username and password for all of them.

**Fallback if step 0 finds a problem** with `lua-resty-kafka` (e.g. the Kong fork's
SCRAM needs an OpenResty patch that our version lacks): the gateway POSTs events to a
**Fluent Bit sidecar on localhost**. Fluent Bit is C, uses librdkafka, supports
SCRAM-SHA-256 and is widely run. The rest of the design is unchanged; only the last hop
differs.

---

## 6. Analyzer, Kafka and ClickHouse

### Analyzer

- **Transport changes, logic does not.** `build_record` and everything under
  `analyzer/parser`, `analyzer/stress` and `analyzer/record_builder` keep working. What
  changes is the input format (stripped events, §7) and the I/O around it.
- FastAPI `/analyze` is replaced by a `confluent-kafka` loop:
  consume a batch → build records → produce → **then** commit offsets (at-least-once).
  Scale out by adding consumers, up to the partition count of topic 1 (gateway events).
- Jobs Logstash does today move into the analyzer as plain, unit-tested functions:
  - `_msearch` fan-out: one output message per sub-query.
  - Dead-letter marking: unparseable input, unknown operation and record-build errors go
    to the **same results topic** with `kind: "dead_letter"` (we have one results topic,
    not two).
- Connects with SCRAM-SHA-256 (librdkafka settings). The consumer and producer have
  separate connection settings in config, even though today both point at the same
  shared cluster.
- A small HTTP server remains for `/health` and `/metrics`: consumer lag, events/s, build
  errors, produce errors.
- **Parsers accept both formats:** stripped (`schema_version: 2`) and raw (when the
  gateway runs in `raw` mode). This is also what makes rolling upgrades safe (§8).
- **Privacy backstop:** before writing `request_body` to the record, the analyzer removes
  any document content that slipped through (e.g. `doc`/`upsert` inside a small `_update`
  kept for its script).

### ClickHouse (`clickhouse_setup/_schema.py`)

ClickHouse reads Kafka with its built-in Kafka table engine. **The Kafka credentials are
set on-prem in the ClickHouse server configuration by the team that runs it;** ALO's
setup job only creates tables and views.

- `alo_results_queue` — `ENGINE = Kafka` on topic 2, `JSONEachRow`,
  `kafka_handle_error_mode = 'stream'`. Broker list, topic name and consumer group come
  from chart values; credentials do not.
- `alo_results_to_raw_mv` — `… WHERE kind = 'record'` → `alo_raw`. ClickHouse does the
  batching that Logstash's `flush_size`/`idle_flush_time` did.
- `alo_results_to_dead_letter_mv` — `… WHERE kind = 'dead_letter'` → `alo_dead_letter`.
- `alo_results_errors_mv` — rows where the `_error` virtual column is set (malformed
  messages) → `alo_dead_letter`, so a bad message never stalls consumption.
- Cluster mode: the materialized views write into the `Distributed` tables (sharding key
  unchanged).

### Kafka (one shared on-prem cluster, operated outside ALO)

Both topics are created by hand, on-prem, before deployment. ALO only needs their names
and SCRAM-SHA-256 credentials.

| Topic | Producer → consumer | Message size (typical) | Notes |
|---|---|---|---|
| **Topic 1 — gateway events** | all gateways → analyzer | 1–5 KB; ≤ `ALO_REQ_KEEP_MAX_BYTES` + small overhead | Its partition count is the upper limit on analyzer parallelism. |
| **Topic 2 — analyzer results** | analyzer → ClickHouse | ~1–2 KB | Records and dead letters, told apart by `kind`. |

Messages are small by construction. The meeting's "messages over 5 MB" concern doesn't
arise with stripping on. The only potentially large field is a `keep`-strategy query
body, capped at 1 MB by default. With stripping off (`raw` mode) the gateway enforces
`ALO_KAFKA_MAX_MESSAGE_BYTES` and sends metadata-only above it.

### Deployment changes

- **Docker Compose:** remove `logstash` and `logstash-exporter`; add a single-node KRaft
  Kafka (dev/CI only).
- **Helm:** delete `templates/logstash/*` and `values.logstash`. Add one `kafka:` block
  used by the gateway, the analyzer and ch-setup:

  ```yaml
  kafka:
    brokers: "kafka-1:9093,kafka-2:9093"
    securityProtocol: SASL_SSL        # or SASL_PLAINTEXT
    sasl:
      mechanism: SCRAM-SHA-256
      existingSecret: alo-kafka       # keys: username, password (gateway + analyzer only)
    tls:
      caSecret: ""                    # optional CA bundle
    topics:
      events: ""                      # topic 1 — required
      results: ""                     # topic 2 — required
    analyzer:
      consumerGroup: alo-analyzer
    clickhouse:
      consumerGroup: alo-clickhouse   # credentials are set on-prem in ClickHouse itself
  ```

  Add `values.schema.json` entries. Update `templates/tests/test-pipeline.yaml`.
- **Release workflow:** stop building the `logstash` image (four images instead of five).
- **Stack Health dashboard:** replace the Logstash panels with gateway produce, drop and
  degrade counters, thread-pool queue, analyzer lag/throughput, and ClickHouse
  `system.kafka_consumers`.

---

## 7. The event contract

One message on topic 1 (gateway events), with stripping on:

```json
{
  "schema_version": 2,
  "event_id": "5b0c9e7a2f6d4c1e",
  "ts": 1762600000.123,
  "cluster": "prod-a",
  "method": "POST",
  "path": "/logs-app/_bulk",
  "op": "_bulk",
  "status": 200,
  "upstream_ms": 184.0,
  "req_bytes": 52428800,
  "resp_bytes": 7340032,
  "identity": {
    "username": "ingest-svc",
    "user_agent": "elastic-transport-python/8.13",
    "app_name": "",
    "labels": { "team": "payments" }
  },
  "request_body": "{\"_alo_bulk_summary\":{\"groups\":[{\"action\":\"index\",\"index\":\"logs-app\",\"pipeline\":\"parse\",\"routing\":false,\"id\":\"auto\",\"count\":48000,\"bytes\":51200000,\"max\":4100}]}}",
  "request_truncated": false,
  "resp_head": "{\"took\":171,\"errors\":false,\"items\":[{\"index\":{\"_index\":\"logs-app\",\"_id\":\"…\",\"_version\":1,\"result\":\"created\",\"_shards\":{\"total\":2,\"successful\":2,\"failed\":0}…",
  "resp_gzip": false,
  "resp_windows": null,
  "degraded": null
}
```

- `schema_version` — the analyzer supports the current and previous versions (§8.3).
- `event_id` — a unique id per request. Unused in phase 1; it is the join key for phase 2 (§9).
- `identity` — derived in the gateway. **The raw `Authorization` header never leaves the
  gateway.**
- `degraded` — set when the event was sent metadata-only, with the reason.

The contract is documented in one place (this section, later moved to
`docs/ARCHITECTURE.md`). **Golden fixtures** (raw request/response → expected event) live
in `tests/fixtures/contract/`, and the Lua tests and the Python tests both run against
them, so the two sides cannot drift.

---

## 8. How a gateway release works

This answers the second concern: *"changing logic there will be complicated to do — logic
and deploy wise"*.

### 8.1 Make most changes not need a gateway release at all

The design pushes change away from the gateway on purpose:

| Kind of change | Where it lives | What a release looks like |
|---|---|---|
| New score, indicator, template rule, field extraction, privacy filtering | Analyzer (Python) | Analyzer image only. The gateway is untouched. **This is the vast majority of changes.** |
| Tune a threshold (head size, keep limit, thread count, budgets), switch a strategy for an operation, change capture mode | Gateway **config** (`values.yaml` → ConfigMap/env) | `helm upgrade` → config checksum changes → rolling restart. No new image. |
| Change *how* the gateway captures or strips (new strategy, bug fix in Lua) | Gateway **Lua modules** | New gateway image (§8.3). Rare. |
| Change the event format | Contract | `schema_version` bump, analyzer first (§8.3). Rare. |

### 8.2 Code layout that makes gateway changes small and safe

- **All Lua moves into modules baked into the image:** `gateway/lua/alo/{capture,process,strip,rules,producer,identity,budget,init}.lua`.
- **`nginx.conf` becomes thin** — directives plus one-line `require("alo.x").phase()` calls.
  Today the Lua logic is duplicated between `gateway/nginx.conf.template` and the Helm
  ConfigMap. After this change **there is one copy**, in the image, and the Helm ConfigMap
  only carries directives and values.
- **The rule table is config.** For example:

  ```yaml
  gateway:
    capture:
      mode: strip                  # off | meta | strip | raw
      respHeadBytes: 8192
      reqKeepMaxBytes: 1048576
      inlineMaxBytes: 16384
      strip:
        threads: 4
        maxQueue: 256
        inflightBudgetBytes: 268435456
      rules:                       # operation → strategy; defaults ship in the image
        _bulk:   bulk_summary
        _doc:    doc_size
        _create: doc_size
        _update: update
        _msearch: { strategy: keep, windows: { anchor: '{"took":', bytes: 256, max: 2000 } }
  ```

### 8.3 Releasing a new gateway version — step by step

1. **Develop against fixtures.** Change the Lua module, add or extend golden fixtures.
   Run the tests locally in the gateway image:
   `docker run … resty -I gateway/lua busted gateway/spec`.
2. **CI gates** (new jobs in `.github/workflows/ci.yml`):
   - **Unit tests:** busted specs for every strategy, against the shared golden fixtures.
   - **Event-loop budget test:** a `resty` script feeds large fixtures (100 MB bulk, gzip
     bulk, 50 MB search response, 1,000-query `_msearch`) through the hot-path functions
     and fails if per-request event-loop time exceeds a budget.
   - **Proxy latency regression test:** compose stack plus the stress tool; compares
     p50/p99 through the gateway in `off` vs. `strip` mode. It fails if the added p99 is
     above the agreed threshold of **2 ms**. This
     is about the proxy, not data freshness (§5.1).
3. **Tag the release** (existing flow: `git tag v3.x.y && git push origin v3.x.y`). The
   release workflow builds the gateway image as today.
4. **If the contract changed: roll out the analyzer first.** The analyzer reads both
   version N and N−1, so it is safe with old and new gateways at the same time. Then roll
   the gateway. Rolling back the gateway is therefore always safe.
5. **Roll the gateway** with `helm upgrade`. The chart will set:
   - `strategy: RollingUpdate`, `maxUnavailable: 0`, `maxSurge: 1` — capacity never drops.
   - Readiness probe on by default, so a new pod gets traffic only when nginx is serving.
   - Graceful shutdown: `preStop` sleep (lets the Service stop sending traffic), then nginx
     `SIGQUIT`. Workers finish in-flight requests, and the producer flushes its buffer on
     worker exit. Anything still unsent is counted as dropped.
6. **Canary by pausing the rollout.** After the first new pod is ready:
   `kubectl rollout pause deploy/<release>-gateway`. Watch Stack Health for ~15 minutes:
   gateway p99 vs. ES `took`, degraded/dropped counters, thread-pool queue, analyzer
   errors. Then `kubectl rollout resume`.
7. **Roll back** with `helm rollback <release>`. The gateway is stateless, so rollback is
   just the previous image and config.

### 8.4 Emergency switches (no code, no image)

| Switch | Effect | How fast |
|---|---|---|
| `capture.mode: off` | Pure proxy. No Lua capture runs at all. | One `helm upgrade` → rolling restart (~1–2 minutes). |
| `capture.mode: meta` | Capture metadata only (sizes, timings, operation). No body handling, no thread pool. | Same. |
| Runtime toggle *(optional, nice-to-have)* | The same modes set through the internal port (`:9145/alo/mode`, not exposed outside the pod), stored in a shared dict. No restart. | Seconds, per pod. |

---

## 9. Phase 2 — the extension point

Phase 2 means optionally keeping full content (e.g. in S3) for deeper investigation. Phase
1 does **not** build any of it. It only makes sure phase 2 is a pure add-on:

- Every event already has an `event_id`.
- The producer module takes a **list of sinks**. Phase 2 adds a second sink, for example
  raw bodies to a new content topic (created by hand, like the others) keyed by
  `event_id`, with an S3 sink connector behind it. It is enabled per operation in the
  rule table.
- The analyzer and ClickHouse need **no changes**. Content is joined by `event_id` only
  when someone investigates.

---

## 10. Work plan

Each step is one PR and is reviewable on its own.

| # | Step | Contents | Done when |
|---|---|---|---|
| **0** | **Gateway spike (go/no-go)** | Prototype `capture` + `strip` (bulk_summary only) + `lua-resty-kafka` (Kong fork) in the gateway image. Verify: SCRAM-SHA-256 against our on-prem cluster with our OpenResty version; `ngx.run_worker_thread` with `cjson` and `lua-ffi-zlib` inside the thread; the hardlink hand-off of spooled bodies. Benchmark: p50/p99 proxy latency with capture `off` vs. `strip`, under a mix of large bulks, large responses and `_msearch`. | The numbers are written down and the added p99 is **≤ 2 ms**. If SCRAM fails: switch to the Fluent Bit sidecar fallback (§5.7). **If the overhead is above 2 ms, we revisit before building anything else.** |
| 1 | **Repo cleanup, part A** | Simplifications that don't depend on Kafka: one copy of each dashboard, stale-content fixes, decided deletions, tools reorganised, one CI script for GitHub and GitLab. Exact list in §10.1. | Every item in §10.1 part A is done; CI green; compose stack still runs end to end on the 2.x pipeline |
| 2 | Event contract + analyzer parsers | `schema_version: 2`; summary-aware parsers (bulk summary, response head, `_msearch` windows, gzip head); golden fixtures; privacy backstop; still accepts raw. Pure Python. | Unit tests green on the fixtures |
| 3 | Gateway | Lua modules, **one** `nginx.conf.template` in the image (the Helm copy is deleted, §10.1 B4), rule table from config, thread pool, budgets, degradation, Kafka producer, header allowlist + username in gateway, kill switch, metrics. busted + budget tests in CI. | CI gates from §8.3 green |
| 4 | Analyzer transport | Kafka consumer/producer loop, at-least-once, `_msearch` fan-out, dead letters marked with `kind` on the results topic, `/health` + `/metrics`. | Integration test: gateway → Kafka → analyzer → Kafka |
| 5 | ClickHouse | Kafka engine tables, materialized views, error stream → dead letter, `ON CLUSTER` schema mode for external clusters. | Records land in `alo_raw`; malformed messages land in `alo_dead_letter` |
| 6 | Deployment | Compose (Kafka, no Logstash), Helm (`kafka:` block, rollout strategy, probes on, single-node in-chart ClickHouse), release workflow, Prometheus config, Stack Health dashboard. | `helm template` / `helm test` green; compose stack runs end to end |
| 7 | Tests | Integration, resilience and challenge suites moved off Logstash. Latency regression job. | Full suite green |
| 8 | **Repo cleanup, part B** + docs + release | Every removal that only becomes possible once the Kafka path exists (§10.1 part B). Then `ARCHITECTURE`, `HELM`, `README`, `CHANGELOG`, new `RATIONALE` section "Why Kafka now" (§13, Q7), and this file folded in and deleted. Tag `v3.0.0`. | Every item in §10.1 part B is done; released |

### 10.1 Repository simplification (steps 1 and 8)

**Goal:** after v3, the repo holds only what the product ships, what tests it, and what
documents it as it is. Each artifact has **one** source of truth.

Today: 194 tracked files, about 41,000 lines. About **8,900 of those lines are
byte-identical copies** of the dashboard JSON.

All decisions below are already made (§13, Q14), so the people doing these steps don't
need to choose anything. Line counts were measured on `main` at v2.1.21.

#### Part A — step 1 (no dependency on Kafka; ships on the 2.x pipeline)

**A1. Dashboards: one committed copy, one delivery path per Grafana type**

| Action | Files | Why |
|---|---|---|
| Delete | `grafana/provisioning/dashboards/*.json` (5 files, 8,928 lines) | Byte-identical to `helm/alo/files/grafana-*.json`. The Helm copy stays because Helm's `.Files.Get` can only read files inside the chart. |
| Change | `docker-compose.yml`: Grafana mounts `./helm/alo/files` as its dashboards folder; update the path in `grafana/provisioning/dashboards/dashboards.yml` | Compose and Helm load the same files. |
| Change | `grafana/_dashboards.py` `export_dashboards()`: write only to `helm/alo/files/` | One output location. |
| Add | `tests/unit/grafana/test_dashboards_in_sync.py`: build every dashboard in memory and compare with the committed JSON | CI fails if someone changes a builder and forgets to regenerate. Today nothing catches that. |
| Change | `helm/alo/templates/grafana/job-setup.yaml`: run only when `grafana.external.enabled=true` | Today an in-chart Grafana gets its dashboards **twice** — from the provisioning ConfigMaps and again from the API job. In-chart Grafana: provisioning only. External Grafana: API job only. |

**A2. Stale content and encoding fixes**

| Action | Where | Fix |
|---|---|---|
| Fix text | `grafana/_dashboard_builders.py` (lines ~190, ~509), Hebrew in `grafana/_strings.py` (line ~129) → regenerate JSON | "hourly summary-index fallback (survives raw-data ILM expiry)" is Elasticsearch-era wording → "hourly `alo_summary` fallback (survives the raw-table TTL)". |
| Fix comment + default | `analyzer/record_builder/__init__.py` (lines 32–37), `.env.example` | The comment explains the cap with the ES keyword limit (no longer relevant). Rewrite it as "storage cap for `request_body` in ClickHouse". Code says 32000 and `.env.example` says 32768 → both 32000. |
| Fix text | `helm/alo/values.schema.json` line 43 | "replaces v1's Elasticsearch sink" → a plain description. |
| Fix encoding | `grafana/setup.py`, `grafana/_dashboards.py`, `grafana/_dashboard_builders.py` | Remove the UTF-8 byte-order mark at the top of each file. Replace the garbled box-drawing characters (`ΓöÇ`, 21+ lines) with `─`. |
| Fix encoding | `CHANGELOG.md` | One garbled line, same fix. |
| Prevent | `.pre-commit-config.yaml` | Add the `fix-byte-order-marker` hook. |

**A3. Decided deletions**

| Delete | Lines | Also update |
|---|---|---|
| `docs/PRODUCT_SPEC.md` | 160 | README docs table |
| `tests/integration/verify_grafana_dashboards.py`, `tests/integration/_grafana_debug.py` (Playwright) | 564 | `tests/help.md` |

**A4. Tools: one home, no path hacks**

The interactive challenges are kept (decided), but they are load *tools*, not tests.
`shared/` is used only by tools and tests, never by the product.

| Action | From → to |
|---|---|
| Move | `tests/challenges/` → `tools/challenges/`; scenario modules `_challenge_<name>.py` → `tools/challenges/scenarios/<name>.py`; `_challenge_v1.py` → `scenarios/four_apps.py` |
| Replace | The 15 thin wrappers (`challenge.py`, `challenge_*.py`; 259 lines) → one entry point: `python -m tools.challenges <name> [--seed …]`, `--list`, default `four_apps` |
| Move | `shared/` → `tools/common/` |
| Delete | The three re-export shims and their `sys.path` hacks: `tests/challenges/helpers.py`, `tests/integration/helpers.py`, `tools/stress/_helpers.py` (89 lines). Callers import `tools.common` directly. |
| Change | The stress tool runs as `python -m tools.stress`; update `tools/stress/Dockerfile` `COPY` paths |
| Move | `tests/unit/challenges/test_infra.py` → `tests/unit/tools/test_challenge_infra.py`; `tests/unit/shared/test_latency_tracker.py` → `tests/unit/tools/test_stats.py` |
| Change | `pyproject.toml` isort `known-first-party`: `shared` → `tools` |

**A5. One CI definition for GitHub and GitLab**

Both CIs are kept (decided). Today their job logic is written twice, and `.gitlab-ci.yml`
has not been updated since the `shared/` refactor.

- Add `scripts/ci.sh` with subcommands `lint`, `typecheck` and `test`. Steps 3 and 6 later
  add `lua` and `chart`.
- `.github/workflows/ci.yml` and `.gitlab-ci.yml` each become a thin list of
  `scripts/ci.sh <job>` calls, so the two cannot drift. The image build stays in GitHub
  `release.yml`.

**A6. Documentation trims**

| File | Change |
|---|---|
| `tests/help.md` (260 lines) | Down to ~40 lines: how to run each suite. Drop the file-by-file tree and per-file tables; they go stale with every change and the repo itself shows the tree. |
| `README.md` | Remove the PRODUCT_SPEC row; update the paths for the challenges and stress tool. |

#### Part B — step 8 (after the Kafka path works)

**B1. Logstash, everywhere**

| Delete / change | Detail |
|---|---|
| Delete `logstash/` | 4 files, 152 lines |
| Delete `helm/alo/templates/logstash/` | 7 files, 408 lines; plus `values.logstash`, its `values.schema.json` entries, and the `ingress.logstash` / `route.logstash` values |
| Change `docker-compose.yml` | Remove the `logstash` and `logstash-exporter` services |
| Change `prometheus/prometheus.yml` | Remove the `logstash` job and fix the `CLUSTER_NAME` comment (it now comes from the gateway, not Logstash) |
| Change `.github/workflows/release.yml` | Stop building the `logstash` image |
| Change `grafana/_health_panels.py`, `grafana/_health_dashboard.py` | Replace the Logstash panels (44 references) with Kafka/analyzer panels, then regenerate |
| Change `helm/alo/templates/grafana/configmap-dashboards.yaml`, `job-setup.yaml` | Drop the `logstash.exporter.enabled` conditions |
| Change `.env.example` | Remove the Logstash block; add the Kafka block |
| Rewrite `helm/alo/templates/tests/test-pipeline.yaml` | Test gateway → Kafka → ClickHouse |

**B2. The analyzer's HTTP surface**

| Delete / change | Detail |
|---|---|
| Delete `analyzer/_routes.py` | `/analyze` and the unused `/analyze/bulk` |
| Change `analyzer/main.py` | No FastAPI app; Kafka loop plus a small `/health` + `/metrics` server |
| Change `pyproject.toml` | Remove `fastapi`, `uvicorn`, `prometheus-fastapi-instrumentator`; add `confluent-kafka`, `prometheus-client`. Update the mypy `additional_dependencies` in `.pre-commit-config.yaml`. |
| Replace `tests/unit/analyzer/test_main.py` (424 lines) | With tests for the consumer loop (batching, `_msearch` fan-out, dead-letter marking, commit-after-produce) |
| Shrink `analyzer/_decompression.py` + its test (155 lines) | Remove the latin-1 / magic-byte recovery path. It only existed for Logstash's ISO-8859-1 codec. What remains is gzip-prefix inflation of response heads (§5.4). |

**B3. Helm analyzer exposure**
- Delete `helm/alo/templates/analyzer/ingress.yaml` and `route.yaml` (53 lines) and the
  `ingress.analyzer` / `route.analyzer` values. The analyzer no longer accepts requests.
  Its Service stays for metrics scraping.

**B4. One gateway config**
- Delete `helm/alo/templates/gateway/configmap.yaml` (255 lines; it is a second,
  diverged copy of the gateway config).
- Move its Helm-only features into the image's `gateway/nginx.conf.template`, driven by
  env vars: Elasticsearch auth header injection (basic / API key), upstream TLS (SNI,
  CA, verify depth, insecure skip), worker processes, timeouts, error log level. Compose
  and Helm then run **the same** config.
- The `LOGSTASH_URL` / `PIPELINE_URL` naming split disappears along with both variables.

**B5. In-chart ClickHouse: single node only** (decided)
- Delete `clickhouse.cluster.{shards,replicas,keeper}` and the `01-cluster.xml` block in
  `helm/alo/templates/clickhouse/configmap.yaml`; the StatefulSet is fixed at one replica.
- Schema-level cluster mode stays, because the on-prem ClickHouse is a cluster: ch-setup
  keeps `ON CLUSTER` + `Replicated*MergeTree` + `Distributed`, enabled only with external
  ClickHouse (`clickhouse.external.cluster: "<cluster name>"`).
- Because the in-chart ClickHouse must read Kafka too, the chart renders its Kafka SCRAM
  settings from the `kafka` secret. This applies only to the in-chart instance; external
  ClickHouse is configured on-prem.

**B6. Final documentation**

| File | Change |
|---|---|
| `docs/ARCHITECTURE.md` | Rewritten for v3. Drop the repo file tree (~40 lines that drift). |
| `docs/HELM.md` | `kafka:` block, gateway-only installs per ECK environment, single-node in-chart ClickHouse |
| `docs/RATIONALE.md` | Replace "Kafka — a natural alternative we didn't pursue" with "Why Kafka now"; move in the decision log from §13 of this file |
| `docs/REDESIGN.md` (this file) | **Delete** once v3 ships. It is a proposal; afterwards the design lives in ARCHITECTURE and the decisions in RATIONALE. |
| `tools/stress/benchmarking.md` (292 lines) | Rewrite around the step-0 method and numbers; drop the Logstash sizing |
| `CHANGELOG.md` | The 3.0.0 entry lists every removal above, as breaking changes |

#### Deliberately kept

| Kept | Why |
|---|---|
| Hebrew dashboard (`alo-main-he`, `_strings.py`, `cheat_sheet_he.html`) | Decided. Hebrew-speaking users rely on it. |
| `.gitlab-ci.yml` | Decided. It runs CI on the on-prem mirror. Kept in sync through `scripts/ci.sh` (A5). |
| Interactive challenges | Decided. Moved to `tools/` (A4). |
| Prometheus compose profile + exporters | Decided. Updated for Kafka (B1). |
| `docs/TODO.md`, `CHANGELOG.md` history | Still accurate and useful. |
| `grafana/cheat_sheet.md` | Embedded into the dashboards at build time. |
| `tools/stress/` | Used by the latency gate (§8.3) and by step 0. |

#### Expected result

| | Before | After (estimate) |
|---|---|---|
| Duplicated dashboard JSON | 8,928 lines | 0 |
| Copies of the gateway nginx config | 2 (diverged) | 1 |
| Places CI job logic is defined | 2 | 1 |
| Ways dashboards reach an in-chart Grafana | 2 | 1 |
| Services in Compose (default profile) | 6 | 6 (Logstash out, Kafka in) |
| Lines removed (excluding new v3 code) | — | ≈ 11,000 |

---

## 11. Risks and how we contain them

| Risk | Likelihood | Containment |
|---|---|---|
| The strip adds latency to the proxy | Low by design | No large-body work on the event loop (§5.2); CI latency gate; canary; kill switch. |
| `lua-resty-kafka` SCRAM-SHA-256 doesn't work with our OpenResty version or brokers | Low–medium (Kong's fork documents SCRAM-SHA-256; older releases needed an OpenResty patch) | Checked in step 0, before any other work. Fallback: Fluent Bit sidecar (§5.7). |
| Two gateways share a `CLUSTER_NAME` on the shared topic, so their data is mixed together | Medium (human error) | The chart refuses an empty or default `CLUSTER_NAME` when Kafka output is on. Documented in the install guide. |
| `ngx.run_worker_thread` limitations (which modules load in the thread) | Low–medium | Checked in step 0. Fallback: a smaller inline limit and metadata-only for big bodies (measured loss). |
| Hardlink hand-off fails (different filesystem, permissions) | Low | Spool dir sits on the same volume as `client_body_temp_path`. If `link()` fails: metadata-only, counted. |
| ES response field order changes, so head capture misses fields | Low | Stop anchors and byte cap degrade to "fields missing", never to "content leaked". Analyzer flags missing fields; a fixture per ES major version. |
| Event loss when Kafka is unavailable | Expected sometimes | Accepted and measured (`events_dropped_total{reason}`), in line with our durability stance. |
| ClickHouse Kafka engine stalls on a bad message | Low | `kafka_handle_error_mode = 'stream'` + error MV → dead letter. |
| More components to operate (two Kafka connections) | Certain | The clusters already exist and are run by others. ALO stops running Logstash, so the net count of things *we* operate goes down. |

---

## 12. Open questions

**None open.** Everything below is resolved (details in §13). Step 0 (§10) remains the
technical go/no-go.

- Topics: one shared on-prem Kafka cluster, two topics, created by hand before deployment.
  ALO creates nothing in Kafka.
- Auth: SCRAM-SHA-256.
- ClickHouse → Kafka: ClickHouse's built-in Kafka engine; credentials set on-prem.
- Data freshness: up to 5 minutes is acceptable.
- Deployment topology: a gateway-only install in each ECK environment; one central
  analyzer + ClickHouse + Grafana.
- Proxy overhead: at most 2 ms added at p99, enforced by the CI gate.

---

## 13. Decision log (Q&A)

How we got here, in order.

**Q1. Which architecture did we pick?**
"Kafka only" (option 2 in *ALO Redesign.docx*): gateway → Kafka → analyzer → Kafka →
ClickHouse. "Vector + Kafka" (option 3) was also on the table. We picked Kafka only
because the gateway can produce to Kafka directly. Logstash's remaining jobs (calling the
analyzer, splitting `_msearch`, routing dead letters, batching) are either absorbed by
Kafka/ClickHouse or become plain analyzer code.

**Q2. How should bodies be stripped?**
- *Inserts* (`_bulk`, single `PUT`s): replace the content with a size summary, but keep
  the settings that can matter (index, pipeline, routing, id style, scripts, upsert
  flags).
- *Responses* (search hits, aggregations, everything): strip the content entirely and
  keep one total response size — not a size per document. Keep only the small metadata
  that scoring needs.
- Document bodies, whether from indexing requests or from query results, are **never
  stored**. ALO's job is to show *where* in the cluster the load is.

**Q3. Strip in NGINX or in the analyzer?**
Both, with a clear split (§4): the gateway owns *volume* (coarse, rule-driven, cheap); the
analyzer owns *meaning and privacy* (final guarantee before storage).

**Q4. Do we run Kafka?**
No. The clusters exist for both legs (gateway → analyzer, analyzer → ClickHouse). ALO
only connects to them.

**Q5. What is in scope?**
Phase 1 only — a plain pipeline with no content storage. It should deliver enough value to
customers on its own. Phase 2 (S3 or another store for content) must be easy to add later
(§9), and nothing more is done for it now.

**Q6. Won't stripping in NGINX slow the proxy and hurt users? How does it handle many huge
requests and responses? How is the gateway code released?**
Answered in §5 (where the work runs, how requests and responses are stripped, how huge
and concurrent traffic is bounded, pseudo-code) and §8 (release process). Short version:
- The client path only does constant or memchr-speed work.
- Responses are never buffered.
- Large request bodies are processed in a thread pool, and spooled ones are handed over
  without copying.
- Overload degrades observability, never latency.
- Most changes ship as analyzer or config changes. Gateway releases are gated by CI
  latency tests, rolled out with a canary pause, and can be rolled back instantly.
- A kill switch turns the gateway into a pure proxy.

**Q7. `docs/RATIONALE.md` says we considered Kafka and didn't pursue it. What changed?**
Each objection listed there is now answered:

| Objection in RATIONALE | Answer now |
|---|---|
| Kafka producer in the gateway's hot path | The producer is async with a bounded buffer and runs after the response is sent. Failures are dropped and counted, never waited on. |
| Loses Logstash's `split` for `_msearch` | It becomes a small analyzer function (already half there in `record_builder/_msearch.py`). |
| ClickHouse batching becomes application code | The ClickHouse Kafka engine does the batching. |
| Dead-letter routing becomes application code | A few lines in the analyzer, plus the ClickHouse error stream. |
| Consumer offsets make the analyzer stateful | Offsets are stored in Kafka, not in the analyzer. Building a record stays a pure, stateless function. |
| A platform nobody here operates | The clusters now exist and are operated outside ALO. |

That section of RATIONALE will be replaced by "Why Kafka now" as part of step 8.

**Q8. Who creates the Kafka topics, and how many are there?**
The Kafka cluster and its topics are shared by all our ECK environments. There is one
topic for gateway (nginx) events and one for analyzer results, both created by hand,
on-prem, before the new version is deployed. ALO only takes the topic names as config.
Consequences: dead letters share the results topic (told apart by `kind`), and
`CLUSTER_NAME` must be unique per gateway (§3).

**Q9. Why not use a ready-made nginx plugin to write to Kafka?**
Neither nginx nor OpenResty has Kafka support built in. The available C modules are
either unmaintained (`kaltura/nginx-kafka-log-module`, last push 2021) or built for a
different job (`ngx_kafka_module`). More importantly, a log-phase module sends before our
stripped event exists, and a C module means custom nginx builds on every upgrade.
`lua-resty-kafka` — the library behind Kong's and APISIX's Kafka plugins — is the
OpenResty-native choice. Full reasoning in §5.7.

**Q10. Which Kafka authentication?**
SCRAM-SHA-256. The team configures it through JAAS on the Java side; Lua, Python and
ClickHouse take the same username and password directly (§5.7).

**Q11. How does ClickHouse read from Kafka, and who sets its credentials?**
With ClickHouse's built-in Kafka table engine. Credentials are set on-prem in the
ClickHouse server config; ALO's setup job only creates the tables and materialized views
(§6).

**Q12. What latency is acceptable?**
For data freshness, up to 5 minutes from request to visible is fine; the design should
land well under a minute. That is separate from the overhead the proxy adds to user
requests, which must stay close to zero: **at most 2 ms added at p99**, enforced in CI
and checked in step 0 (§5.1).

**Q13. How is ALO deployed across environments?**
A gateway-only install of the chart in each ECK environment, all writing to the shared
gateway-events topic, plus one central install of the analyzer, ClickHouse and Grafana
(§3).

**Q14. Should v3 also clean up the repo?**
Yes. It is a step of its own, split in two (§10.1): part A (step 1) covers what doesn't
depend on Kafka; part B (step 8) covers what Kafka makes removable. Decisions made up front:
- **In-chart ClickHouse:** single node only. The chart no longer runs a sharded or
  replicated ClickHouse itself, but table creation keeps cluster mode for external
  ClickHouse clusters.
- **Kept:** the Hebrew dashboard; GitLab CI (kept in sync with GitHub through one
  shared CI script); the interactive challenges (moved to `tools/`); the Prometheus
  compose profile.
- **Deleted:** `docs/PRODUCT_SPEC.md` and the Playwright dashboard scripts.
