# Applicative Load Observability — Usage Gateway

**Product specification & vision**

This spec is **database-agnostic**: it applies to **Elasticsearch** (e.g. ECK), **MongoDB**, **PostgreSQL**, and similar data platforms. Backend-specific details (e.g. query types, auth) are called out where relevant.

---

## 1. Product Overview

This project aims to provide **applicative load observability** for **database deployments** (Elasticsearch, MongoDB, PostgreSQL, etc.). Given a client’s cluster or instance, the system should:

1. **Identify the most loading operations and queries** — which requests consume the most resources and contribute most to contention.
2. **Enable panel creation** — surface this data in dashboards so operators and developers can analyze and act on it.

The end goal is to **understand what is causing resource contention** (storage, CPU, memory, network) and **correlate it with operations, queries, and users** so the source of load can be clearly attributed.

---

## 2. Core Concepts

### 2.1 Stress Score

A **stress score** is a synthetic metric that quantifies how “heavy” or costly an **operation** (or query) is.

**Simple example (Elasticsearch).** Best-effort weights; use `norm(x) = x / baseline` (e.g. baseline 1000 ms, 10k hits, 100 docs).

- **Search / query:**  
  `stress_score = 0.5 * norm(took_ms) + 0.3 * norm(hits_or_response_bytes) + 0.2 * norm(complexity)`
- **Index / bulk:**  
  `stress_score = 0.4 * norm(took_ms) + 0.6 * norm(bulk_size)`

Operation/query type (e.g. bulk vs. single, update by query vs. single) is reflected in these inputs and in how you bucket and compare stress.

---

The stress score allows **ranking** operations and queries by impact. **Aggregating and bucketing the sum of stress score** then lets you compare impact across different parameters — for example:

- Same **template** (e.g. total load per query template).
- Same **target** (table / index / collection) — e.g. total load per index.
- Same **user** (e.g. total load per username or applicative provider).
- **Operation kind** (e.g. insert vs. update vs. delete vs. query [select]).
- **Query type** (e.g. agg vs. text vs. geo when the operation is a query).

That way you can answer questions like “which template / user / operation contributes most?” and correlate high aggregate stress with resource contention.

---

### 2.2 Operation & Query Analysis

For each **operation** (request), the system should capture:

| Dimension | Description |
|-----------|-------------|
| **Operation kind** | Whether the request is **insert**, **update**, **delete**, or **query** (select). This separates writes from reads. |
| **Target (table / index / collection)** | Which table (PostgreSQL), index (Elasticsearch), or collection (MongoDB) is queried or written to. Essential for attributing load to a specific data set. |
| **Operation / query type** | For **queries** (select): e.g. **agg**, **text**, **geo**, **kNN** (Elastic); find vs. aggregation (MongoDB); simple vs. join-heavy (PostgreSQL). For **insert**: single vs. **bulk**. For **update**: single vs. **by query**. For **delete**: single vs. **by query**. Backend-specific. This is also taken into account in the stress score. |
| **Scrubbing / templating** | Normalize the request (e.g. remove literal values, IDs, dates) to get a **request template**. This enables: <br>• Detecting **repeated** or **high-frequency** patterns. <br>• Grouping identical logical operations for aggregation and stress scoring. |

Outcomes:

- “Top N most loading operation/query templates.”
- “Which tables/indexes/collections and which operations/query types contribute most to CPU/memory/network.”
- “Which templates run most often and at what stress.”

---

### 2.3 User / Requester Analysis

To attribute load to **who** and **what** is sending it:

| Dimension | Description |
|-----------|-------------|
| **Hostname** | Machine or pod from which the request originated. |
| **Username** | Elasticsearch user (or API key identity) performing the query. |
| **Applicative provider** | Name of the application or service that uses Elasticsearch (e.g. “search-api”, “recommendation-service”). |

Outcomes:

- “Which host/application/user is driving the most load.”
- Correlation with stress score and query templates for root-cause analysis.

---

### 2.4 Custom Labels (`x-alo-*` Headers)

You can attach **custom labels** to any request by setting HTTP headers prefixed with `x-alo-`. The gateway forwards these to the analyzer, which strips the prefix and stores them under `labels.*` in the observability record.

| Header sent | Field stored |
|-------------|-------------|
| `x-alo-team` | `labels.team` |
| `x-alo-env` | `labels.env` |
| `x-alo-feature-name` | `labels.feature-name` |

This lets you slice dashboards by any dimension meaningful to your organization — team, environment, feature, tenant, etc.

**Important:** Use **hyphens** (`-`), not underscores (`_`), in header names. The gateway runs on Nginx/OpenResty, which drops headers containing underscores by default.

---

## 3. Dashboard: Applicative Load Observability

All panels live in a **single dashboard**.

### Row 1 — Top Loading Operations & Queries

**Purpose:** See which templates contribute most to load and how stress evolves over time.

| Panel | Type | What it shows |
|-------|------|---------------|
| Top templates by stress | Bar chart | Top N operation/query templates ranked by total stress score |
| Stress over time | Time series | Stress score over time, broken down by template, target, operation kind, or operation/query type |

### Row 2 — Template Frequency & Repetition (by dimension)

**Purpose:** Spot repeated or noisy patterns across all key dimensions.

| Panel | Type | What it shows |
|-------|------|---------------|
| Execution count per template | Time series | How often each template runs over time |
| Execution count by operation kind | Time series | query vs. insert vs. update/delete over time |
| Execution count by operation/query type | Time series | agg, bulk, text, geo, by query, etc. over time |
| Execution count by target | Time series | Per index / table / collection over time |
| Execution count by application / host | Time series | Per applicative provider or hostname over time |

### Row 3 — Load by User / Application / Host

**Purpose:** Attribute load to who and what is sending it.

| Panel | Type | What it shows |
|-------|------|---------------|
| Top apps/hosts by stress | Bar chart | Top hostnames or applications ranked by total stress score |
| Stress/rate over time by app | Time series | Stress or request rate split by application or host |

---

## 4. Summary

| Goal | How it's achieved |
|------|-------------------|
| Find most loading operations & queries | Stress score + template aggregation; Row 1. |
| Quantify "heaviness" | Stress score (time, result size, complexity, bulk size). |
| Operation & query analysis | Target + operation kind + operation/query type + scrubbing/templating; Rows 1–2. |
| User/requester analysis | Hostname, username, applicative provider; Row 3. |
| Resource contention & source | Use dashboard rows together: correlate Row 1/2 spikes with Row 3 breakdown and Row 3 attribution. |


This README describes the **intended product and analysis experience**. Implementation details and code may evolve; this document serves as the specification for what “done” looks like from an observability and dashboard perspective.

---

## 5. User Story: Finding the Source of Resource Contention

*As an operator, I notice a CPU spike on the cluster. Here is how I use the dashboard to find the root cause:*

1. **Start at Row 1** — Look at the stress score time series. The spike is visible. The top templates bar shows `search:agg:products` leading by a wide margin.
2. **Move to Row 2** — The "by operation kind" panel confirms the spike aligns with **query** traffic, not inserts or updates. The "by operation/query type" panel narrows it to **agg** type. The "by target" panel shows `products` index is the hotspot. The "by application" panel points to `search-api`.
3. **Confirm at Row 3** — The top apps bar ranks `search-api` highest. The time series shows its stress rate spiking in the same window.

**Conclusion:** *“The CPU spike was driven by agg-type queries on the `products` index, originating from `search-api`. The top contributing template was `search:agg:products`.”*
