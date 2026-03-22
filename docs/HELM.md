# Helm Deployment Guide

This guide covers what needs to be configured when deploying the ALO chart and areas that require special attention.

---

## 1. Pipeline Mode

Choose which pipeline processor to use by setting `pipelineMode`:

```yaml
pipelineMode: logstash   # or "nifi"
```

- `logstash` — deploys Logstash, skips NiFi
- `nifi` — deploys NiFi, skips Logstash

---

## 2. Using an External Elasticsearch Cluster

In production you will typically point ALO at an existing Elasticsearch cluster rather than deploying one internally.

```yaml
elasticsearch:
  external:
    enabled: true
    url: "https://es.prod.internal:9200"
    auth:
      enabled: true
      type: basic              # or "apiKey"
      username: "elastic"
      password: "changeme"
      # -- OR reference a pre-existing Secret:
      # existingSecret: "my-es-credentials"
      #   basic  → secret must have keys: "username", "password"
      #   apiKey → secret must have key:  "apiKey"
    tls:
      # Secret containing "ca.crt" key — mounted into gateway and Kibana
      caSecret: "my-es-ca"
      insecureSkipVerify: false
```

When `external.enabled=true`:
- No Elasticsearch pods are deployed by the chart
- The `url` field is **required** — the chart will fail at install time if left empty
- Auth credentials are injected into the gateway and Kibana via Secrets

---

## 3. Using an External Kibana

To skip deploying Kibana and point the setup job at an existing instance:

```yaml
kibana:
  external:
    enabled: true
    url: "https://kibana.prod.internal:5601"
```

When `external.enabled=true`:
- No Kibana pods are deployed
- The `url` field is **required**

### Running the Setup Job on External Kibana

The setup job (`kibana.setup`) creates index templates in Elasticsearch and imports dashboards into Kibana. It runs automatically as a `post-install` / `post-upgrade` Helm hook.

When using an external Kibana, make sure:

1. **The setup job image is accessible** — it uses `alo-kibana-setup` which contains `setup.py` and the `.ndjson` dashboard exports. Push this image to a registry reachable from your cluster.

2. **Network connectivity** — the setup job pod must be able to reach both the external Kibana URL and the external Elasticsearch URL from within the cluster.

3. **Verify the job completed** — after install/upgrade, check that the job succeeded:
   ```bash
   kubectl get jobs -l app.kubernetes.io/component=kibana-setup
   kubectl logs job/<release-name>-alo-kibana-setup
   ```

4. **Re-running the setup job** — the job runs on every `helm install` and `helm upgrade`. To re-run it manually without upgrading:
   ```bash
   kubectl delete job <release-name>-alo-kibana-setup
   helm upgrade <release-name> ./helm/alo
   ```

---

## 4. Gateway DNS Resolver (Init Container)

The gateway uses OpenResty (Nginx + Lua). Unlike normal applications, OpenResty requires an explicit DNS resolver IP to resolve service hostnames at runtime.

The chart handles this automatically via an **init container** that reads the cluster's DNS server from `/etc/resolv.conf` and injects it into the nginx config before the gateway starts. This works on both Kubernetes and OpenShift.

### Verifying DNS Resolution

If the gateway cannot reach Elasticsearch or the pipeline, check that the init container ran successfully:

```bash
# Check init container status
kubectl describe pod -l app.kubernetes.io/component=gateway

# Check the resolved nginx config
kubectl exec <gateway-pod> -- cat /usr/local/openresty/nginx/conf/nginx.conf | grep resolver
```

The `resolver` line should show a valid IP (e.g. `10.96.0.10` on standard K8s, `172.30.0.10` on OpenShift).

### Manual Override

If auto-detection fails for any reason, you can explicitly set the DNS resolver IP:

```yaml
gateway:
  dnsResolver: "172.30.0.10"   # OpenShift example
```

---

## 5. Using an External Logstash

```yaml
logstash:
  external:
    enabled: true
    url: "http://logstash.prod.internal:8080/"
```

When `external.enabled=true`:
- No Logstash pods are deployed
- The `url` field is **required**
- The gateway sends observation payloads to this URL via the `PIPELINE_URL` env var

---

## 6. Using an External NiFi

```yaml
pipelineMode: nifi

nifi:
  external:
    enabled: true
    listenUrl: "https://nifi.prod.internal:8080/observe"
    auth:
      enabled: true
      headerName: Authorization
      headerValue: "Bearer <token>"
      # -- OR reference a pre-existing Secret:
      # existingSecret: "my-nifi-token"
      #   secret must have key: "authHeaderValue"
    tls:
      caSecret: "my-nifi-ca"
      insecureSkipVerify: false
```

When `external.enabled=true`:
- No NiFi pods are deployed
- The `listenUrl` field is **required**

---

## 7. Custom Images

The chart uses four custom images that you must build and push to your registry:

| Image | Source | Purpose |
|-------|--------|---------|
| `alo-gateway` | `gateway/` | OpenResty proxy |
| `alo-analyzer` | `analyzer/` | FastAPI stress scorer |
| `alo-logstash` | `logstash/` | Logstash with http filter plugin |
| `alo-kibana-setup` | `kibana/` | Dashboard + template setup |

Image tags default to `Chart.AppVersion` when not specified. Override per component:

```yaml
analyzer:
  image:
    repository: my-registry.io/alo-analyzer
    tag: "1.2.0"
```

---

## 8. Helm Tests

After deploying, verify connectivity between components:

```bash
helm test <release-name>
```

This runs test pods that check:
- Gateway is reachable
- Analyzer is reachable
- Pipeline (Logstash or NiFi) is reachable (when deployed internally)

---

## 9. Environment Variables Reference

All configurable environment variables with their defaults:

| Variable | Default | Component | Purpose |
|----------|---------|-----------|---------|
| `pipelineMode` | `logstash` | Chart-wide | Pipeline processor selection |
| `gateway.dnsResolver` | `""` (auto-detect) | Gateway | OpenResty DNS resolver IP |
| `gateway.pipelineTimeout` | `1000` | Gateway | Pipeline notification timeout (ms) |
| `gateway.proxyReadTimeout` | `60s` | Gateway | ES proxy read timeout |
| `gateway.workerProcesses` | `auto` | Gateway | Nginx worker processes |
| `gateway.workerConnections` | `4096` | Gateway | Connections per worker |
| `logstash.monitoring.enabled` | `false` | Logstash | Ship pipeline metrics to ES |
| `gateway.exporter.enabled` | `false` | Gateway | Deploy nginx-prometheus-exporter sidecar |
| `logstash.exporter.enabled` | `false` | Logstash | Deploy logstash-exporter sidecar |
| `elasticsearch.exporter.enabled` | `false` | Elasticsearch | Deploy elasticsearch-exporter sidecar |
| `serviceMonitors.enabled` | `false` | Prometheus | Deploy ServiceMonitor CRDs |
