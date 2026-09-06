# Rationale — Applicative Load Observability

This document explains *why*, not *how*. For the pipeline design, record schema, and
operational detail, see [Architecture](ARCHITECTURE.md). For deployment, see
[Helm Deployment](HELM.md).

## 1. The gateway position

We could only adopt tools we could operate ourselves, or that the organization already
operated elsewhere. A platform-level capability nobody ran was off the table. This
constraint runs through every decision in this section.

### Why not eBPF / passive tapping

An alternative to putting anything in the request path is to gather the data
passively — eBPF-based tools (Pixie, Cilium/Hubble, Beyla, or a commercial agent like
groundcover) tap the socket layer and pair request and response themselves, no extra
hop, no added latency.

We could only pick what we could run ourselves. That ruled out anything needing a
platform-level install we didn't own, and an eBPF agent was out on capacity grounds
before it was out on technical ones.

It would also have failed on a technical point: eBPF tracers cap captured payload at a
fixed byte limit. ALO needs whole request and response bodies — a truncated ES bulk
payload is not a usable record.

### Why not Envoy, and why not `mirror`

Two narrower alternatives, neither evaluated in practice — both ruled out by the same
ownership constraint before either got as far as a trial:

- **An Envoy tap filter.** If OpenShift Service Mesh were deployed, Envoy already sits
  beside Elasticsearch and its tap filter captures request and response as one paired
  record — the same thing OpenResty gives us, no new hop, no vendor. Service Mesh
  wasn't deployed in these clusters, and standing it up is a bigger platform ask than
  one proxy we already own and operate.
- **nginx's `mirror` directive.** Duplicates the request to a second upstream. Gives
  us nothing of the response, which is most of what the analyzer needs.

### Why OpenResty, not plain nginx

Plain nginx can proxy. It cannot hold the response body for inspection after it's
been streamed to the client, and it has no scripting layer to build the record we
send downstream. OpenResty adds exactly that: Lua phases at each stage of the
request/response lifecycle, and `lua-resty-http` for firing the notification
ourselves.

The gateway does three things:

1. Proxies the request to Elasticsearch and returns the response to the client,
   unmodified.
2. Captures the full request and response bodies during proxying.
3. Fires an async HTTP POST to Logstash *after* the response is already sent —
   method, path, headers, request/response bodies, status, timing, and sizes.

Concretely: `header_filter_by_lua_block` detects response `Content-Encoding` before
chunks accumulate; `body_filter_by_lua_block` accumulates them into `ngx.ctx.resp_body`;
`log_by_lua_block` builds the record and hands it to `ngx.timer.at(0, ...)`, which runs
after the response has already gone to the client. See `gateway/nginx.conf.template`.

### The gateway is asynchronous by design

The notification to the pipeline happens in a timer that fires after the client has
already received their response. If Logstash is slow or down, the notification is
dropped — logged and counted, never retried, never blocking. The client's traffic to
Elasticsearch is unaffected either way. Failures in the observability pipeline must
never propagate upstream into the thing being observed.

### The cost: full-fidelity capture is not lightweight

All parsing and analysis happen downstream in Python — the gateway encodes the captured
record to JSON to hand it off, but never decodes or inspects it. Query analysis, clause
counting, and cost scoring all live in the analyzer. The capture path is
the exception: full request and response bodies are held in worker memory, because
full fidelity is the product, not an afterthought. See [Architecture](ARCHITECTURE.md)
for buffering, sizing, and the memory tuning this requires.

### Why not HAProxy at all

OpenShift's built-in HAProxy ingress controller **cannot replace the OpenResty
gateway.** The gateway needs to capture full request and response bodies and fire an
async notification after the response is sent — HAProxy Lua can't do either reliably:

- **Response body capture is unreliable.** OpenResty streams response chunks via
  `body_filter_by_lua_block` and accumulates them reliably. HAProxy Lua only has
  access to `tune.bufsize` bytes (16 KB by default) of response data, and `res.body`
  returns `nil` in many contexts. Elasticsearch responses regularly exceed 16 KB —
  this alone makes HAProxy unsuitable for what the analyzer needs.
  ([HAProxy discourse: response body coming as nil](https://discourse.haproxy.org/t/response-body-is-coming-as-nil-using-register-fetches-and-lua/9893),
  [request/response body logging](https://discourse.haproxy.org/t/request-response-body-logging/4868),
  [reading request/response via Lua](https://discourse.haproxy.org/t/how-to-read-request-and-response-using-lua-plugin/8484),
  [haproxy/haproxy#2564](https://github.com/haproxy/haproxy/issues/2564))
- **No post-response async phase.** OpenResty's `log_by_lua_block` +
  `ngx.timer.at(0, ...)` fires after the response is sent — zero added client latency.
  HAProxy Lua actions run *during* request processing (`http-request`, `http-response`,
  `tcp-request`). A notification call from there would block the client response,
  violating the rule above. HAProxy does have `core.httpclient()` for outbound HTTP —
  the capability exists, there is just no equivalent of "run this after the response is
  sent."
  ([HAProxy Lua API](https://www.haproxy.com/documentation/haproxy-lua-api/getting-started/introduction/),
  [How Lua runs in HAProxy](https://www.arpalert.org/src/haproxy-lua-api/2.8/index.html),
  [5 Ways to Extend HAProxy with Lua](https://www.haproxy.com/blog/5-ways-to-extend-haproxy-with-lua))

### Why not the OpenShift Route

Separately from what HAProxy itself can do, the built-in OpenShift Route was not an
option in this environment, for reasons independent of HAProxy's capabilities:

- **OpenShift 4 doesn't support custom HAProxy templates.** Customizations available
  in OpenShift 3.x are explicitly missing in OpenShift 4 — the Ingress Operator manages
  the router lifecycle, and direct template changes aren't a supported configuration.
  Customization is limited to a few knobs (`maxConnections`, custom error pages).
  ([Red Hat: HAProxy router customizations missing in OpenShift 4](https://access.redhat.com/solutions/5477331),
  [OpenShift Ingress Operator docs](https://docs.openshift.com/container-platform/4.10/networking/ingress-operator.html))
- **It's a shared, cluster-wide resource.** The OpenShift HAProxy router serves every
  deployment in the cluster. Injecting application-specific observability logic into
  it would require cluster-admin privileges, affect all other traffic through the
  router, get overwritten on the next OpenShift upgrade, and — the one that mattered
  most — risk taking down ingress for the entire cluster if a bug in our logic ever
  misbehaved. We attempted this route more than once and it never landed, for exactly
  this reason.

|  | OpenResty | HAProxy (standalone) | OpenShift HAProxy |
|---|---|---|---|
| Full response body capture | Yes (`body_filter_by_lua_block`) | Unreliable (16 KB buffer, nil) | No (can't customize) |
| Full request body capture | Yes (`ngx.req.get_body_data()`) | Partial (`tune.bufsize` limit) | No (can't customize) |
| Async POST after response | Yes (`ngx.timer.at`) | No (blocks client) | No (can't customize) |
| Zero client latency impact | Yes | No | No |
| Per-app isolation | Yes (own pod) | Yes (own pod) | No (shared cluster resource) |
| Survives platform upgrades | Yes | Yes | No (operator-managed) |

The standard pattern instead: HAProxy (or the OpenShift router) handles routing and
TLS; a dedicated OpenResty pod in our own namespace handles body capture and
notification. This is the same shape used by service meshes (Envoy sidecars) and
API gateways (Kong, itself OpenResty-based) industry-wide.

### What Elasticsearch's own capture can and can't do

Elasticsearch has two ways to see request load, and it's worth being precise about
both rather than dismissing them.

**Audit logging** can emit request bodies via
`xpack.security.audit.logfile.events.emit_request_body`. This isn't new. But
`request.body` only appears on six *authentication* event types
(`authentication_success`, `authentication_failed`, `realm_authentication_failed`,
`tampered_request`, `run_as_denied`, `anonymous_access_denied`), only on the
coordinating node, and it's all-or-nothing — there's no way to audit request bodies
for search requests only. Elastic's own docs put it plainly: *"There is no audit event
type specifically dedicated to search queries"* and *"the original raw query, as
submitted by the client, is not accessible downstream when authorization auditing
occurs."* Per-request-type control has been requested
([elastic/elasticsearch#64234](https://github.com/elastic/elasticsearch/issues/64234))
and is still open. It also requires a Platinum (existing customers only) or Enterprise
subscription.

**Query Logs**, added in 9.4, is the purpose-built version: every query across
DSL, ES|QL, EQL, and SQL, with latency, hit counts, shard counts, and full query body,
zero configuration. It overlaps most of what our stress model measures.

Where it still falls short, for our purposes:

- **It's query logging — indexing isn't a query.** `_bulk` requests never appear in
  it, and bulk write load is usually the load that matters most. ALO handles `_bulk`
  explicitly, including document counts affected.
- **It doesn't include the response status or response size**, both of which we
  capture and use.
- **It needs 9.4 on the source cluster, and 9.4 on any destination cluster** the logs
  are shipped to — a real constraint for clients running older ECK deployments.
- **It's Preview on self-managed deployments**, GA only on Elastic Cloud, and
  threshold-sampled by default rather than complete.

### `took` cannot be trusted from inside Elasticsearch

Elasticsearch's own `_bulk` `took` value has been quantized to multiples of 200ms
since 8.16 — bulks that finish in under ~200ms of actual indexing time report
`took: 0`, even though the client clearly received the response much sooner. This is
confirmed as intended behavior by Elastic, not a bug awaiting a fix
([elastic/elasticsearch#129894](https://github.com/elastic/elasticsearch/issues/129894),
open; our own reproduction across 8.13.4/8.18.6/9.0.0 is at
[elastic/elasticsearch#148334](https://github.com/elastic/elasticsearch/issues/148334),
closed as a duplicate of the above). 8.13.4 returns smooth millisecond values; 8.18.6
and 9.0.0 quantize to 200ms steps.

Because of this, the gateway measures `took` externally — elapsed time as observed
from outside the cluster — for `_bulk` operations, rather than trusting the value
Elasticsearch reports. This isn't a workaround for a bug that will get fixed; it's
permanent, because Elastic considers the current behavior correct.

### Not a permanent answer

An Envoy tap filter or an eBPF tracer captures the same request/response pair without
adding a hop, and either could supersede this gateway. Neither was available to us —
both need a platform-level install we don't own and couldn't commit to operating. The
gateway is what we could ship and support ourselves, and it delivers value now. If the
mesh lands, or an eBPF agent becomes something the platform runs, this decision should
be revisited.

---

## 2. The pipeline

We could only adopt tools we could operate ourselves, or that the organization already
operated elsewhere. A platform-level capability nobody ran was off the table.

### Why Logstash

Logstash was chosen because it was already part of the stack the organization
operated — an in-house tool, not a new one — and because an HTTP input, an enrichment
filter, and an output got the pipeline to working in an afternoon. It also gave us
what we actually needed structurally: an in-process queue to absorb spikes in gateway
traffic (`queue.type: memory`, `queue.max_bytes: 256mb` — spike absorption, not
durability), and a place to run a synchronous enrichment call to the analyzer mid
stream, merging the response back into the event before it's written out.

That was the right trade when the sink was Elasticsearch. The sink has since changed
— see below for what that leaves unresolved.

### Durability: what we guarantee, and what we don't

The pipeline is not hermetic, and it isn't meant to be. This is observability data
measuring load trends, not an audit log — a missing fraction of events doesn't move a
p95 or a stress score, and restarts along the way are usually intentional on our part.

What we do guarantee is **coverage**: no *class* of traffic may be systematically
excluded. Large bodies, gzipped bodies, binary payloads, `_msearch` fan-out — all must
be handled, or the signal becomes biased rather than merely thinner. Random loss
thins the signal; systematic loss biases it, and that's the line we hold. This is why
there's no request size limit, why bodies over the buffer threshold spool to disk
instead of being dropped, why compressed bodies are base64-encoded rather than
discarded as unparseable, and why failed events go to a dead-letter table instead of
disappearing.

Loss is also measured, not hidden — `alo_gateway_events_dropped_total{reason}`, broken
out by cause, on the health dashboard. We accept loss; we don't hide it.

This is a stance, not a law — a base assumption we hold today because near-complete
has been good enough for the decisions this data drives. If that demand tightens, the
answer changes, and the dropped-events metric is exactly what would tell us it's time
to revisit it.

### Kafka — a natural alternative we didn't pursue

Kafka is the obvious thing to reach for when the concern is queueing and event loss,
and it came up as a natural idea. We didn't evaluate it deeply — no trial, no
prototype — so what follows is reasoning about the shape it would have taken, not a
verdict from experience.

The shape would have been: no Logstash, no orchestrator — the gateway writes to
Kafka directly, and the analyzer consumes, enriches, and writes to ClickHouse itself.
On inspection this looked like it would cost more than it bought. It would put a
Kafka producer in the gateway's hot path, where the design goal is minimal logic. It
loses the `split` step that fans one gateway event into N records for `_msearch`
batches — that would become application code. ClickHouse batching (flush size, flush
interval, async insert) would also become application code, and dead-letter routing
along with it. Consumer offsets would make the analyzer stateful, which breaks a
principle we hold elsewhere: the analyzer is stateless and its errors never
propagate. And it's also a platform-level system nobody here operates, which is
itself most of why it never went further than a passing thought.

None of this rules Kafka out for good — it's a fair option if durability requirements
ever tighten. It just isn't something we can claim to have seriously weighed against
what we built.

### Why not NiFi

The first implementation used NiFi, not Logstash — it's the tool the organization
already operates, so on paper it satisfied the constraint above better than Logstash
did. It was replaced in Docker Compose the following day, though NiFi
and Logstash were maintained side by side in the Helm chart for roughly two and a half
months afterward, until the ClickHouse migration finally removed it along with every
other alternative the chart had been carrying (Elasticsearch, Kibana, the pipeline-mode
toggle). Changing the sink is what forced the pipeline decision we'd been deferring.

Passing the constraint on paper wasn't enough. NiFi's flows are stored as JSON —
`flow.json`, hundreds of lines of generated graph — which is not reviewable and not
diffable the way the rest of this stack is; nobody can look at a pull request and see
what changed. Building and iterating on flows with LLM assistance was also
consistently painful in a way the rest of the stack wasn't: simple changes routinely
took far longer than they should have, because the tool's UI-first, canvas-based model
doesn't map onto text-based tooling at all. Logstash's pipeline is 57 lines of text
that any editor, diff tool, or model can read directly.

### Why not Vector — not yet a drop-in

Vector is not a drop-in replacement for what Logstash does today, whatever else it
might be. The pipeline calls the analyzer synchronously, mid-stream, and merges the
response back into the event before writing it out.

VRL gained an `http_request()` function in mid-2025
([vectordotdev/vrl#1360](https://github.com/vectordotdev/vrl/pull/1360)), so this is
no longer a hard gap the way it once was. It still isn't a match for what we need: it
has no parameter for a request body, and our enrichment call is a POST carrying a
JSON payload — there's nothing to attach it to. Even where it does apply, Vector's own
source documents it as synchronous and blocking, and explicitly says: *"not
recommended for frequent or performance-critical workflows... avoid using this
function in latency-sensitive contexts"* — a fair description of the pipeline's hot
path. Enrichment tables remain a separate mechanism and still load at startup rather
than per-event. Adopting Vector means moving the analyzer call out of the pipeline
and giving it its own hop — a re-architecture, not a config change.

Separately, the plugin connecting Logstash to ClickHouse
(`logstash-output-clickhouse`) has been archived since January 2021, and its author's
own README says he switched to Vector. Nothing about it is currently broken, but
nothing about it is maintained either, and as installed today it isn't even
version-pinned. Pinning it is a one-line mitigation available now. Whether the
eventual answer is Vector, something else, or reworking the analyzer call so more
options become drop-in, is left open here rather than decided.

### Why not a hand-rolled service

Not separately evaluated — same reasoning as Kafka above: whatever replaces Logstash
needs to either be something we already operate, or something the analyzer's
synchronous-enrichment requirement doesn't force us to rebuild from scratch.

---

## 3. The sink (where records are stored) — Elasticsearch to ClickHouse

### Why we started on Elasticsearch

ALO's first sink was Elasticsearch, for the same reason the first pipeline was
NiFi: it was the tool already running, and it got the project to something useful
quickly. It also meant one fewer technology in an already new stack.

### Why we moved

Performance and scale, not a search-engine judgment. ALO is meant to run against a
large, growing number of Elasticsearch clusters — the schema already assumes it: the
sort key leads with `cluster_name`, and the sharding key hashes on `cluster_name` and
operation. At that scale the observability data itself becomes the cost problem,
independent of the clusters being watched.

Elasticsearch stores a field three ways: an inverted index for search, `doc_values`
for aggregation, and raw in `_source`. Our rows are never searched by relevance — only
GROUP-BY'd and percentile-rolled over templates, providers and operations — so the
inverted index is a write we never read. `index: false` would drop it but leaves
`_source` untouched, and doesn't touch how the summary is built.

The bigger reason was how the rollup is maintained. On Elasticsearch, the summary was
a pivot transform running on a five-minute `frequency`: each cycle re-queried the raw
indices with a composite aggregation and wrote hourly buckets to a destination index.
The aggregation is query-driven — its cost lands on the raw data on a schedule, and the
summary trails ingest by up to a cycle. ClickHouse's incremental materialized view is
insert-driven: each inserted block updates the aggregate state as it lands, and nothing
queries the raw table to keep the summary current.

This is a right-sizing of Elasticsearch's role for ALO's own data, not a vote against
Elasticsearch generally — the monitored clusters keep doing search, which is what
they're for.

### The dashboards, compared like for like

Before the migration, Grafana already ran against Elasticsearch as an alternative to
Kibana — the same panels, pointed at a different datasource. After the migration, the
same Grafana panels were re-pointed at ClickHouse. The same dashboards went from
barely usable to effectively instant. We didn't record numbers, so this is an
observation, not a benchmark — but the comparison was genuinely like for like: same
tool, same panels, only the store underneath changed.

(Kibana was dropped in the same release, for an unrelated reason — maintaining one
dashboard UI instead of two.)

### Materialized views: where the cost win is

`alo_summary` is built by an incremental materialized view: each raw insert updates
the aggregate state (counts, sums, averages, percentile sketches) once. Dashboards
read that state instead of recomputing from raw rows.

It's why raw is kept 3 days and summary 120: the summary isn't raw data, it's small
aggregate state, cheap to store and scan. Pay the aggregation cost once at insert
time, not on every query.

### What we gave up

ClickHouse asks you to commit to a sort key up front. Ours is
`(cluster_name, request_operation, identity_applicative_provider, timestamp)`. Any
dashboard query that filters or groups on a column outside that key forces a full
column scan — which several of ours do, which is why five `bloom_filter` skip indexes
exist on the raw table today, added after the fact. Elasticsearch doesn't force this
decision the same way; you can add an inverted index on nearly anything, whenever you
like. New skip indexes here also don't retroactively cover existing data — that
requires an explicit backfill, left as an operator's call rather than something we run
automatically.

Related, and not yet resolved: the summary table's grouping key includes
`request_template`, which is unbounded. At the scale ALO is meant to run, this hasn't
been validated, and it's the first thing worth measuring before we get there.

---

*Sources for the restored HAProxy analysis were preserved from the original
`docs/haproxy-gateway-analysis.md`, removed from the tree in March 2026 and recovered
from git history for this document.*
