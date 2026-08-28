# Helm Deployment Guide

This guide covers what needs to be configured when deploying the ALO chart
(`helm/alo/`) and the areas that need special attention. Values referenced here live in
`helm/alo/values.yaml`; every new value must also be added to `values.schema.json`.

The chart deploys five components: **gateway**, **analyzer**, **logstash**,
**clickhouse** (optional), and **grafana** (optional), plus two post-install Jobs
(`ch-setup`, `grafana-setup`).

> Two ES-shaped things, different roles: `gateway.elasticsearch.*` is the **monitored**
> cluster ALO proxies and never writes to; `clickhouse.*` is the analytics **sink** ALO
> writes observability rows to. Kibana, NiFi, and `pipelineMode` were removed in 2.0.

---

## 1. The monitored Elasticsearch cluster

Required whenever `gateway.enabled=true`. The gateway proxies this cluster verbatim.

```yaml
gateway:
  elasticsearch:
    url: "https://es.prod.internal:9200"     # REQUIRED
    auth:
      # When true the gateway injects credentials on proxied requests.
      # Leave false to pass client credentials straight through.
      injectAuth: false
      type: basic                # or "apiKey"
      username: "elastic"
      password: "changeme"
      # apiKey: "<base64 id:key>"
      # -- OR reference a pre-existing Secret:
      # existingSecret: "my-es-credentials"
      #   basic  → keys "username", "password"
      #   apiKey → key  "apiKey"
    tls:
      caCert: ""                 # inline PEM (with create: true)
      caCertSecret: "my-es-ca"   # -- OR an existing Secret holding "ca.crt"
      create: false
      insecureSkipVerify: false
```

Note the identity trade-off: with `injectAuth: false`, per-client credentials reach ES
and `identity_username` is populated from the client's own `Authorization` header. With
`injectAuth: true`, every proxied request authenticates as the same principal.

---

## 2. ClickHouse (the analytics sink)

### Embedded (default)

```yaml
clickhouse:
  enabled: true
  database: alo
  image: {repository: clickhouse/clickhouse-server, tag: "24.8"}
  persistence: {enabled: true, size: 20Gi, storageClass: ""}
  service: {httpPort: 8123, nativePort: 9000}
  auth: {enabled: false, username: default, password: ""}
  exporter: {enabled: false, port: 9363}   # built-in /metrics, no sidecar needed
```

### External

```yaml
clickhouse:
  external:
    enabled: true
    url: "https://ch.prod.internal:8443"   # REQUIRED — scheme + port
    host: ""                               # Grafana datasource host; empty = parsed from url
    auth:
      enabled: true
      username: "alo"
      password: "changeme"
      # existingSecret: "my-ch-credentials"   # keys "username", "password"
    tls:
      caCert: ""
      caCertSecret: ""
      create: false
      insecureSkipVerify: false
```

When `external.enabled=true` no ClickHouse pods are deployed; the URL is required, and
the ch-setup Job still runs against it (so it needs DDL rights).

### Distributed / replicated mode

```yaml
clickhouse:
  cluster:
    enabled: true
    name: alo_cluster
    shards: 1
    replicas: 1
    shardingKey: "cityHash64(cluster_name, request_operation)"
    keeper:
      external: "zk1:2181,zk2:2181"   # REQUIRED — the chart does not deploy Keeper
```

Every table becomes a `Replicated*MergeTree` `<name>_local` plus a `Distributed`
`<name>` front. Clients keep using the unsuffixed names, so no other component changes.

---

## 3. Retention and table tuning (`tableSettings`)

Passed to the ch-setup Job, which turns them into DDL (`clickhouse_setup/_schema.py`).

```yaml
tableSettings:
  rawRetentionDays: 3            # alo_raw + alo_dead_letter TTL
  summaryRetentionDays: 120      # alo_summary TTL
  rawPartitionBy: "toYYYYMMDD(timestamp)"
  summaryPartitionBy: "toYYYYMM(time_bucket)"
  # Full TTL clause overrides — any expression ClickHouse parses, incl. tier moves:
  rawTtlClause: ""               # e.g. "timestamp + INTERVAL 1 DAY TO VOLUME 'warm', timestamp + INTERVAL 7 DAY DELETE"
  summaryTtlClause: ""
  rawExtraSettings: {}           # e.g. {storage_policy: hot_warm_cold}
  summaryExtraSettings: {}
  shardingKey: "cityHash64(cluster_name, request_operation)"
  summaryExcludeUnknownOperation: false
```

**`summaryExcludeUnknownOperation`** — when `true`, the materialized view drops rows whose
`request_operation` didn't parse (`unknown`), which also removes that traffic from the
dashboard variables. Default `false` (keep them). Changing it triggers a **DROP + recreate
of the MV** (ch-setup detects the definition change) and **does not backfill** — only
traffic ingested afterwards reflects the new filter.

---

## 4. Setup Jobs

### `ch-setup` (schema DDL)

Runs as a post-install / post-upgrade hook; all statements are idempotent.

```yaml
clickhouse:
  setup:
    enabled: true
    image: {repository: oracle1012/applicative-load-observability, tag: ch-setup-2.1.20}
    database: true
    rawTable: true
    deadLetterTable: true
    summaryTable: true
    materializedView: true
```

```bash
kubectl get jobs -l app.kubernetes.io/component=ch-setup
kubectl logs job/<release>-alo-ch-setup
```

### `grafana-setup` (datasource + dashboards)

```yaml
grafana:
  setup:
    enabled: true
    image: {repository: oracle1012/applicative-load-observability, tag: grafana-setup-2.1.20}
    datasource: true      # create/update the ClickHouse datasource via the Grafana API
    dashboards: true      # import/update the five dashboards via the Grafana API
    connection:
      protocol: native    # "native" (port 9000) or "http" (e.g. 8123 / 80 behind an ingress)
      port: ""            # empty = derive from protocol
      path: ""            # optional HTTP path prefix; ignored for native
      secure: ""          # "" = sniff TLS from the clickhouse url scheme; "true"/"false" to force
    variableOptionLimit: 1000
```

`connection.*` matters when your ClickHouse only exposes the HTTP port — the default
`native`/9000 will silently fail there. The same knobs exist as `grafana/setup.py` flags:
`--protocol`, `--ch-port`, `--ch-path`, `--ch-secure`.

`variableOptionLimit` caps how many distinct values a dashboard variable dropdown
returns. Variable queries are scoped to the dashboard time range and bounded with
`GROUP BY`. (The former `variableLookbackDays` / `variableScanRowCap` values were removed
in 2.1.19 — a fixed 7-day window plus a row cap made values invisible in large
deployments.)

---

## 5. Grafana

```yaml
grafana:
  enabled: true
  image: {repository: grafana/grafana, tag: "11.6.7"}
  adminPassword: admin
  adminPasswordExistingSecret: ""
  prometheusUrl: ""      # set to add a Prometheus datasource for the Stack Health dashboard
  service: {type: ClusterIP, port: 3000}
```

To use an existing Grafana instead:

```yaml
grafana:
  external:
    enabled: true
    url: "https://grafana.prod.internal"
    auth:
      username: admin
      password: admin
      # existingSecret: "my-grafana-credentials"
```

With `external.enabled=true` no Grafana pods are deployed and the grafana-setup Job pushes
the datasource and dashboards to that URL via the API. `prometheusUrl` is opt-in — leave
it empty and no Prometheus datasource is created, which leaves the Stack Health
dashboard's Prometheus panels empty (its ClickHouse panels still work).

---

## 6. Gateway tuning

| Value | Default | Purpose |
|-------|---------|---------|
| `gateway.workerProcesses` | `2` | Nginx workers. Pin a fixed count rather than `auto` in cgroup-limited containers on many-core hosts |
| `gateway.workerConnections` | `4096` | Connections per worker |
| `gateway.clientBodyBufferSize` | `64m` | In-memory request body buffer; larger bodies spool to disk |
| `gateway.pipelineTimeout` | `1000` | Timeout (ms) for the async POST to Logstash |
| `gateway.proxyReadTimeout` / `proxyConnectTimeout` | `60s` / `10s` | Upstream ES timeouts |
| `gateway.errorLogLevel` | `warn` | Nginx error log level |
| `gateway.probes.enabled` | `false` | TCP socket liveness/readiness on the gateway port. Off by default — there is no HTTP health endpoint to probe |
| `gateway.exporter.enabled` | `false` | nginx-prometheus-exporter sidecar (`port: 9113`) **and** the internal metrics server on `stubStatusPort: 9145` — the Lua `/metrics` endpoint only exists when this is on |
| `gateway.replicas` / `pdb.enabled` | `2` / `false` | Availability |

### DNS resolver (init container)

OpenResty needs an explicit DNS resolver IP to resolve service hostnames at runtime. The
chart handles this with an init container that reads the cluster DNS server from
`/etc/resolv.conf` and injects it into the nginx config. This works on Kubernetes and
OpenShift.

```bash
# Check the init container ran
kubectl describe pod -l app.kubernetes.io/component=gateway

# Check the resolved config
kubectl exec <gateway-pod> -- cat /usr/local/openresty/nginx/conf/nginx.conf | grep resolver
```

The `resolver` line should show a valid IP (e.g. `10.96.0.10` on K8s, `172.30.0.10` on
OpenShift). Override manually if auto-detection fails:

```yaml
gateway:
  dnsResolver: "172.30.0.10"
```

---

## 7. Logstash and analyzer tuning

```yaml
logstash:
  external: {enabled: false, url: ""}    # url REQUIRED when external; gateway posts to it
  replicas: 1
  service: {httpPort: 8080, monitoringPort: 9600}
  pipeline: {workers: 4, batchSize: 125, batchDelay: 50}
  queue: {type: memory, maxBytes: 256mb}
  javaOpts: ""                            # e.g. "-Xms1g -Xmx1g"
  clickhouseOutput:
    flushSize: 5000
    deadLetterFlushSize: 1000
    idleFlushTime: 5
    automaticRetries: 3
    poolMax: 10
    chSettings: "input_format_skip_unknown_fields=1,async_insert=1,wait_for_async_insert=0"
  exporter: {enabled: false, port: 9198}

analyzer:
  replicas: 2
  port: 8000
  dynamicBaselines: {cacheTTL: "60", queryWindow: "1 HOUR"}
  stressBaselines: {tookMs: "", hits: "", shardsTotal: "", docsAffected: ""}
  requestBody: {}                         # e.g. {storeMaxBytes: 65536}; default 32768
```

`analyzer.stressBaselines.*` entries left empty fall back to dynamic baselines computed
from ClickHouse; setting one pins it statically. `analyzer.requestBody.storeMaxBytes` sets
`ALO_REQUEST_BODY_STORE_MAX_BYTES` — the cap on how much of `request_body` is persisted
(analysis always runs on the full body).

---

## 8. Exposure: Ingress and OpenShift Routes

```yaml
ingress:
  enabled: false
  className: ""
  annotations: {}
  gateway:    {host: "", path: /}
  clickhouse: {host: "", path: /}
  grafana:    {host: "", path: /}
  analyzer:   {host: "", path: /}
  logstash:   {host: "", path: /}
  tls: []

route:                              # OpenShift
  enabled: false
  tls: {enabled: true, termination: edge, insecureEdgeTerminationPolicy: Redirect}
  gateway: {enabled: true,  host: ""}
  grafana: {enabled: true,  host: ""}
  clickhouse: {enabled: false, host: ""}
  analyzer:   {enabled: false, host: ""}
  logstash:   {enabled: false, host: ""}
```

Only the gateway and Grafana routes are enabled by default — the analyzer, Logstash, and
ClickHouse endpoints are internal and should stay that way unless you have a reason.

---

## 9. Prometheus ServiceMonitors

```yaml
serviceMonitors:
  enabled: false
  labels: {}
  interval: "15s"
  clusterLabel: ""     # stamps a `cluster` label via relabeling
```

Set `clusterLabel` equal to `global.clusterName` (the ClickHouse `cluster_name`) so the
Stack Health dashboard's Prometheus panels and its ClickHouse dead-letter panels scope to
the same cluster. Requires the Prometheus Operator CRDs.

Per-component exporters are separate switches: `gateway.exporter.enabled`,
`logstash.exporter.enabled`, `clickhouse.exporter.enabled`.

---

## 10. Images

The chart uses five custom images, all published from this repo by the release workflow
(`.github/workflows/release.yml`, triggered by a `v*` tag):

| Image | Source | Purpose |
|-------|--------|---------|
| `gateway-<version>` | `gateway/` | OpenResty proxy |
| `analyzer-<version>` | `analyzer/` | FastAPI stress scorer |
| `logstash-<version>` | `logstash/` | Logstash + http filter + clickhouse output |
| `ch-setup-<version>` | `clickhouse_setup/` | ClickHouse schema DDL Job |
| `grafana-setup-<version>` | `grafana/` | Datasource + dashboard provisioning Job |

Tags are pinned per component in `values.yaml`. Override per component:

```yaml
analyzer:
  image:
    repository: my-registry.io/alo-analyzer
    tag: "2.1.20"
imagePullSecrets:
  - name: my-registry-creds
```

Mirror all five into a reachable registry for air-gapped clusters — the two setup Jobs are
easy to forget and the install will hang without them.

---

## 11. Multi-tenancy

```yaml
global:
  clusterName: prod-search     # → cluster_name column on every row, and the Prometheus `cluster` label
```

One ClickHouse can serve many monitored clusters. `cluster_name` is the separation key:
it leads the `alo_raw` sort key, drives the sharding key in distributed mode, and backs
the `$cluster` dashboard variable. Keep the Helm `global.clusterName`, the Logstash
`CLUSTER_NAME`, and `serviceMonitors.clusterLabel` identical per deployment.

---

## 12. Verifying a deployment

```bash
helm template test helm/alo/            # renders clean before committing
helm install alo helm/alo -f my-values.yaml
helm test alo                           # gateway / analyzer / pipeline reachability pods
```

Then check, in order:

```bash
kubectl logs job/<release>-alo-ch-setup          # tables + MV created
kubectl logs job/<release>-alo-grafana-setup     # datasource + 5 dashboards imported
kubectl logs -l app.kubernetes.io/component=logstash | tail   # no ClickHouse insert errors
```

Finally send a query through the gateway and confirm rows land:

```sql
SELECT count() FROM alo.alo_raw WHERE cluster_name = 'prod-search';
SELECT count() FROM alo.alo_dead_letter;   -- should stay near zero
```

A non-trivial dead-letter count means the analyzer is unreachable, erroring, or seeing
paths whose operation doesn't parse — check the analyzer logs first.
