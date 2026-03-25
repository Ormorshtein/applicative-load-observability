# Grafana Dashboard Support

## Motivation

ALO dashboards are currently Kibana-only. Adding Grafana as an alternative provider gives teams the flexibility to use their preferred observability tool without changing the underlying data pipeline. Data continues to flow through the same Gateway -> Logstash -> Analyzer -> Elasticsearch pipeline; only the visualization layer changes.

## Architecture

```
                    ┌─────────────────────┐
                    │   Elasticsearch     │
                    │  (logs-alo.*-*)     │
                    └────────┬────────────┘
                             │
                 ┌───────────┴───────────┐
                 │                       │
          ┌──────▼──────┐         ┌──────▼──────┐
          │   Kibana    │         │   Grafana   │
          │  :5601      │         │  :3000      │
          │  Lens API   │         │  ES datasrc │
          └─────────────┘         └─────────────┘
```

Both tools query the same Elasticsearch indices. No Prometheus agent or exporter is needed — Grafana connects to Elasticsearch directly as a datasource.

## Data Source

Grafana's built-in **Elasticsearch datasource** is used:

| Setting        | Value                                       |
|----------------|---------------------------------------------|
| Type           | `elasticsearch`                             |
| URL            | `http://elasticsearch:9200` (container) or configurable |
| Index pattern  | `logs-alo.*-*`                              |
| Time field     | `@timestamp`                                |
| ES version     | 8.0+                                        |

The datasource is auto-provisioned via Grafana's file-based provisioning system — no manual configuration required on startup.

## Dashboard Provisioning

Grafana supports **provisioning** — placing YAML config and JSON dashboard files in specific directories so they are loaded automatically on startup.

```
grafana/provisioning/
├── datasources/
│   └── elasticsearch.yml       # ES datasource definition
└── dashboards/
    ├── dashboards.yml          # Tells Grafana where to find dashboard JSON
    ├── alo-main.json           # Main stress analysis dashboard
    └── alo-cost-indicators.json # Cost indicators dashboard
```

These files are mounted into the Grafana container at `/etc/grafana/provisioning/`.

## Dashboard Mapping (Kibana -> Grafana)

### Panel Type Translation

| Kibana Type       | Grafana Type   | Usage                          |
|-------------------|----------------|--------------------------------|
| `lnsMetric`       | `stat`         | KPI metrics (total stress, etc.) |
| `lnsPie`          | `piechart`     | Stress distribution by dimension |
| `lnsXY` (area)    | `timeseries`   | Stress over time               |
| `lnsXY` (line)    | `timeseries`   | Response time panels            |
| `lnsXY` (bar_h)   | `barchart`     | Horizontal bar rankings         |
| `lnsDatatable`    | `table`        | Top-N tables                   |
| `markdown`        | `text`         | Cheat sheet / guide             |

### Main Dashboard Panels

1. **Cheat sheet** — Text panel with dashboard usage guide
2. **Total Stress Score** — Stat panel, sum of `stress.score`
3. **Stress by Application** — Pie chart, terms on `identity.applicative_provider`
4. **Stress by Target** — Pie chart, terms on `request.target`
5. **Stress by Operation** — Pie chart, terms on `request.operation`
6. **Stress Trend (Overall)** — Time series, avg `stress.score` + request count
7. **Stress by Template** — Pie chart, terms on `request.template`
8-12. **Stress Over Time** — Time series per dimension (Application, Target, Operation, Cost Indicator, Template)
13. **Top 10 Templates** — Table with sum stress, avg latencies, cost indicators, request count
14-16. **Avg ES Response Time** — Time series by Cost Indicator, Operation, Template
17-19. **Avg Gateway Response Time** — Time series by Cost Indicator, Operation, Template
20. **Most Recurring Templates** — Table (request count)
21. **Most Cost Indicators** — Table (avg CI count + request count)

### Cost Indicators Dashboard Panels

1-4. **KPI row** — Stat panels: Flagged Requests, Avg Indicator Count, Avg/Max Stress Multiplier
5. **Indicator Type Frequency** — Bar chart on `stress.cost_indicator_names`
6. **Flagged vs Total Requests** — Time series (two series: filtered count + total count)
7. **Clause Count Trends** — Time series (terms_values, agg, script, wildcard averages)
8. **Bool Clause Breakdown** — Stacked area (must, should, filter, must_not averages)
9. **Top Templates by CI Count** — Table (avg indicators, requests, avg multiplier, avg stress)
10. **Stress Multiplier by Application** — Bar chart
11. **CI Count by Target** — Bar chart

## Elasticsearch Query Format in Grafana

Grafana queries Elasticsearch using its own query editor which translates to:
- **Lucene query string** for filtering
- **Metric aggregations**: `sum`, `avg`, `max`, `count`
- **Bucket aggregations**: `terms` (top-N), `date_histogram` (time series)

Example query structure in dashboard JSON:
```json
{
  "datasource": {"type": "elasticsearch", "uid": "alo-elasticsearch"},
  "targets": [{
    "query": "",
    "metrics": [{"type": "sum", "field": "stress.score", "id": "1"}],
    "bucketAggs": [
      {"type": "terms", "field": "identity.applicative_provider", "id": "2",
       "settings": {"size": "8", "order": "desc", "orderBy": "1"}},
      {"type": "date_histogram", "field": "@timestamp", "id": "3",
       "settings": {"interval": "auto"}}
    ]
  }]
}
```

## Configuration

### Environment Variables

| Variable                | Default                        | Description                    |
|-------------------------|--------------------------------|--------------------------------|
| `GRAFANA_URL`           | `http://localhost:3000`        | Grafana URL (host-side scripts)|
| `GRAFANA_ADMIN_PASSWORD`| `admin`                        | Grafana admin password         |
| `ELASTICSEARCH_URL`     | `http://elasticsearch:9200`    | ES URL (shared with existing)  |

### Docker Compose

Grafana is added as an optional service in `docker-compose.yml`:
```yaml
grafana:
  image: grafana/grafana:11.0.0
  ports:
    - "3000:3000"
  volumes:
    - ./grafana/provisioning:/etc/grafana/provisioning
  depends_on:
    elasticsearch:
      condition: service_healthy
```

### Setup

```bash
# Kibana dashboards (existing)
python kibana/setup.py

# Grafana dashboards (new) — validates provisioning and optionally tests connectivity
python grafana/setup.py

# Both can be run independently or together
```

## Using an Existing Grafana Instance

If you already have a Grafana instance running, you can import the ALO dashboards into it without deploying a new Grafana. There are two approaches depending on whether you also want ALO to create its own datasource or you want to reuse an existing one.

### Option A: Push dashboards + datasource via the setup script

The setup script can push both the datasource and dashboards to your existing Grafana via the HTTP API:

```bash
python grafana/setup.py \
  --mode api \
  --grafana http://your-grafana:3000 \
  --elasticsearch http://your-elasticsearch:9200 \
  --username admin \
  --password <your-grafana-admin-password>
```

This creates a datasource named **"Elasticsearch (ALO)"** (UID: `alo-elasticsearch`) pointing at the provided Elasticsearch URL with the index pattern `logs-alo.*-*`, then imports both dashboards.

### Option B: Use your own existing datasource

If you already have an Elasticsearch datasource configured in Grafana and want the ALO dashboards to use it instead of creating a new one, you need to update the datasource reference in the dashboard JSON files before importing.

Every panel in the dashboards references the datasource by UID:

```json
"datasource": { "type": "elasticsearch", "uid": "alo-elasticsearch" }
```

To point the dashboards at your own datasource:

1. **Find your datasource UID** — go to Grafana > Connections > Data sources, click your Elasticsearch datasource, and copy the UID from the URL or the JSON model (e.g. `my-es-datasource`).

2. **Update the dashboard JSON files** — replace the datasource UID in both files:

   ```bash
   # Replace the datasource UID in the provisioning JSON files
   sed -i 's/alo-elasticsearch/YOUR_DATASOURCE_UID/g' \
     grafana/provisioning/dashboards/alo-main.json \
     grafana/provisioning/dashboards/alo-cost-indicators.json
   ```

3. **Update the index pattern** — if your existing datasource uses a different index pattern than `logs-alo.*-*`, no changes are needed in the dashboards themselves (the index pattern is configured on the datasource, not in the panels).

4. **Import the dashboards** — either:
   - **Via Grafana UI**: Go to Dashboards > Import, paste the JSON content from each file.
   - **Via the API** (skip datasource creation):
     ```bash
     # Import main dashboard
     curl -X POST http://your-grafana:3000/api/dashboards/db \
       -H "Content-Type: application/json" \
       -u admin:<password> \
       -d "{\"dashboard\": $(cat grafana/provisioning/dashboards/alo-main.json), \"overwrite\": true}"

     # Import cost indicators dashboard
     curl -X POST http://your-grafana:3000/api/dashboards/db \
       -H "Content-Type: application/json" \
       -u admin:<password> \
       -d "{\"dashboard\": $(cat grafana/provisioning/dashboards/alo-cost-indicators.json), \"overwrite\": true}"
     ```

### Helm: Existing Grafana

When deploying via Helm, set `grafana.external.enabled=true` to skip deploying a Grafana pod and only run the setup job that pushes dashboards to your existing instance:

```yaml
grafana:
  enabled: true
  external:
    enabled: true
    url: "http://your-grafana.namespace.svc:3000"
    auth:
      username: admin
      password: <your-password>
      # Or reference an existing secret:
      # existingSecret: grafana-admin-credentials
```

The setup job will create the `alo-elasticsearch` datasource and import both dashboards via the Grafana API.

> **Note:** If you want the dashboards to use a datasource that already exists in your Grafana, you'll need to build a custom setup image with the updated datasource UID, or manually import the dashboards after editing the JSON files as described in Option B above.

## Provider Choice

Users choose their dashboard provider by:
1. **Running the respective setup script** (`kibana/setup.py` or `grafana/setup.py`)
2. **Starting the respective service** in Docker Compose (both start by default)
3. **Scaling down** the unwanted service: `docker compose up --scale kibana=0` or `--scale grafana=0`

> **Note:** The Grafana Cost Indicator pie chart does not include a "(missing)" bucket for unflagged queries. The Kibana version does via `missingBucket`. This is a Grafana ES datasource limitation.
