# TODO — Backlog

Unvalidated candidates for `analyzer/stress/`, `analyzer/parser/`, and the
Grafana dashboards. None of these are implemented. As with the existing
scoring weights and thresholds (`docs/ARCHITECTURE.md` §2.4): all numbers
below are best-effort starting points, not conclusions — they must be tuned
against real production data before or shortly after landing.

Moved out of `ARCHITECTURE.md` §9 (2026-09-07) so that file stays a
description of what ships, not a wishlist. See git history on that file for
the original, unpruned version of this list.

---

## Tier 1 — concrete, implementable now

No new data needed; each is a bounded addition to an existing mechanism.

- **`timed_out` indicator** — capture ES's `timed_out` response flag. Also
  interacts with `unbound_hits`: a timed-out search underreports `hits` the
  same way a `track_total_hits` cutoff does, so the two should probably be
  cross-referenced on dashboards.
- **`has_highlight`** — extra per-result CPU from `highlight` blocks. Same
  shape as the existing 11 cost indicators (`analyzer/stress/_cost_indicators.py`):
  one clause count, one presence flag, one multiplier.
- **Bulk action breakdown** — half-built already.
  `analyzer/parser/_request_body.py:32-63` extracts the distinct action-type
  set (`index`/`create`/`update`/`delete`) and target indices per `_bulk`
  request; what's missing is per-type *counts* and columns to expose them,
  for a sharper signal than the flat action-line count
  (`request_bulk_doc_count`).
- **Auto-generated vs user-provided `_id`** — `POST /<index>/_doc` skips
  the existence check; `PUT /<index>/_doc/<id>` does not. Detectable from the
  path segment after `_doc` in `analyzer/parser/_path.py`.
- **Upsert detection** — `_update` with `upsert` / `doc_as_upsert` follows a
  conditional create-vs-update path. Directly observable: ES's `_update`
  response includes `result: created|updated|noop`. No need to wait for
  hit/miss rate modeling — just capture the field.
- **Join queries and `function_score`** — `has_child` / `has_parent` and
  `function_score` clause counts, same pattern as the existing structural
  counters in `clause_counts_*`.
- **Deep pagination scoring** — record `from` as a new component, then apply
  the same bonus shape already used everywhere else in
  `analyzer/stress/_formulas.py` (`min(weight · ln(1 + count − threshold), cap)`,
  see `_CONTINUOUS_BONUSES`) rather than a standalone formula. ES must score
  and discard all preceding docs, so deep pagination is a genuine cost
  signal — the mechanism just needs to match the rest of the file.
- **Scroll detection** — `_scroll` currently rides the plain query formula
  (`_STRESS_DISPATCH["_scroll"] = _stress_query`,
  `analyzer/stress/_formulas.py:67`), which scores `took`/`shards`/`hits` but
  misses that a scroll holds a long-lived shard-level search context across
  requests — a cost with no equivalent in a one-shot `_search`. Needs its own
  `has_scroll` indicator at minimum.

## Tier 2 — needs production data first

Correct direction, but the right weight/threshold can't be picked without
real firing-rate or distribution data.

- **`response_size_bytes` as a stress factor** — the formulas use
  `es_took_ms`, which is blind to transfer cost: a query with `es_took=30ms`
  returning 5 MB imposes real serialization load the score ignores. Would add
  signal for heavy documents, missing source filtering, highlight /
  `script_fields` inflation, and large aggregation payloads. Deferred because
  it's partly redundant with `hits`, penalizes "fat" indexes regardless of
  query quality, and has a skewed distribution that makes baseline selection
  hard. If undetected response-heavy patterns show up in production, add it
  to `StressContext` with a low weight (0.05–0.10) carved from the latency
  share.
- **Cost indicator threshold and multiplier tuning** — against real firing
  rates and their correlation with `response_es_took_ms`.
- **Per-operation write weights** — `_create`, `index`, `delete`, and `get`
  all share `_stress_doc_write` today (`analyzer/stress/_formulas.py:74-77`)
  despite different read depth: `PUT` is a pure write, `DELETE` reads
  version/seq_no, `_update` reads the full `_source`.
- **Depth-weighted agg scoring** — weight aggregations by nesting depth
  instead of the current flat node count (`clause_counts_agg`).
- **Geo search area / `broad_geo` as a recommendation signal** — geo search
  area and a `broad_geo` indicator were considered and removed from
  *scoring* as redundant with `hits` (see "Geo scoring uses vertex count, not
  area" in `docs/ARCHITECTURE.md` §7 limitations). They remain valuable as a
  separate *recommendation* signal — e.g. "you're querying a 500 km radius —
  intentional?" — distinct from the stress score itself.

## Tier 3 — dashboards

- **Gateway response-time panels** — dropped from the main dashboard because
  `response_gateway_took_ms` includes gateway↔ES network time (infrastructure
  noise rather than query cost). The aggregate state already exists —
  `avg_gateway_took_ms_state` in `alo_summary`
  (`grafana/_dashboards.py:500`) — nothing currently reads it into a panel.
  Worth re-adding if network issues become a diagnostic concern.

---

## Tier 4 — route dashboards onto `alo_summary_mv`

Investigated 2026-09-07 while auditing whether Grafana panels could read the
existing materialized view (`alo_summary_mv`, `clickhouse_setup/_schema.py:342`)
instead of `alo.alo_raw`. The MV itself is not the problem — it is a genuine
incremental view, firing inside every insert into `alo_raw` with no refresh
lag, so it introduces none of the staleness a refreshable MV would. What
blocks a naive switch is that the panels and the summary table were never
built to agree on shape. None of this is implemented; recorded here so the
analysis survives past this session.

### Three bugs already live in the current summary path

Reachable today via the 5 panels that pass `summary_fallback=True`
(`mk_timeseries`, `grafana/_dashboards.py`), and become reachable by more
panels the moment MV usage expands:

- `_build_where_summary` (`grafana/_dashboards.py:118`) silently drops the
  `username` / `client_host` / `cost_indicator` predicates, because those
  columns don't exist in `alo_summary`. With a Username filter active, a
  `summary_fallback` panel draws a raw line for that one user beside a dashed
  line for everyone — wrong data on screen, not a graceful degradation.
- `_SUMMARY_AGG_OVERRIDES` (`grafana/_dashboards.py:494`) has no percentile,
  `max`, or `min` entries. When none match, `_summary_timeseries_sql` falls
  through (`grafana/_dashboards.py:519-521`) to `_agg_sql`, emitting e.g.
  `quantile(0.95)(response_es_took_ms)` *against `alo_summary`* — a column
  that table doesn't have. That's a query error, not the "NULL after TTL but
  no worse than the raw fallback" the comment there claims. Latent only
  because no current caller passes a percentile/max/min with
  `summary_fallback=True`.
- The dashed summary series overlaps the raw series across the same 3-day
  window instead of picking up where raw's TTL ends, so the two are drawn
  twice where they agree and coverage isn't actually extended.

### Panel inventory

"Qualifies" = every dimension a panel groups/filters by, and every aggregate
it needs, already exists in `alo_summary` (6 dimensions, 15 `*State` columns —
`clickhouse_setup/_schema.py:156-201`).

- **Qualify as-is (~28 panels):** the four non-cost-indicator pies (Application
  / Target / Operation / Template); Total Stress Score; Top 10 Templates by
  Stress Score (needs `quantilesMerge(0.5, 0.95, 0.99)(pct_es_took_ms_state)`);
  Stress by Application / Target / Operation / Template; Request Volume; Avg
  Documents Matched per Query; Avg Request Size; ES Latency on both
  dashboards; Avg Indicator Count and Avg Stress Multiplier KPIs; Base vs
  Final Score by Template; Top Templates by Cost Indicator Count; Avg Base /
  Avg Multiplier by Template; Avg Cost Indicators by Application; the three
  multiplier / indicator-count bars; Total Request Rate; Rate by Operation /
  Application / Target / Template; Requests by Application; Top 10
  Applications; Top 10 Indices.
- **Unlocked by new `*State` columns (~10 panels):** Documents Matched (sum
  hits), Request Size (sum), Bulk Write Volume ×2, Avg Documents per Bulk,
  Payload Sizes, Read Volume by Operation, Score Composition by Template,
  Score Components, Score Breakdown, Clause Count Trends ×2. Needs
  `sum_hits_state`, `sum_request_size_bytes_state`,
  `sum_bulk_doc_count_state`, `avg_bulk_doc_count_state`,
  `avg_response_size_bytes_state`, `max_multiplier_state`, and avg states for
  `stress_components_*` / `clause_counts_*`. No new dimensions, so no row
  growth — just wider rows. **This is the one place in this item with a real
  invisible-data risk:** rows already written keep empty states for the new
  columns, so these panels read zero over historic ranges until enough new
  data accumulates. Should be called out in the panel descriptions if built.
- **Can never move** (dimension or column not carried by `alo_summary` at
  all): Top 10 Heaviest Operations (per-request rows); everything keyed on
  `stress_cost_indicator_names` (Cost Indicator pie, Cost Indicators table,
  Indicator Frequency bar); Status Code by Operation, Error Rate, Requests by
  Status Code (`response_status`); Top 10 Users (`identity_username`); Flagged
  Requests / Flagged vs Total (row-level `stress_cost_indicator_count >= 1`
  predicate); Max Stress Multiplier (no max state, unless added above).

### Why this is coverage, not speed

At the ~300M-rows-per-window figure from `6c9c301`'s commit message,
`alo_raw` runs roughly 100M rows/day: a 15m window is ~1M rows (already
cheap), 24h is ~100M (slow), and past the 3-day raw TTL ~45 of 50 panels are
simply blank. The MV's payoff is extending the ~28 qualifying panels out to
the 120-day summary retention — not accelerating the default `now-15m` view,
which stays on raw either way. Worth keeping in mind before anyone proposes
chasing sub-hour latency out of the hourly grain below.

### Downsampling design

`alo_summary` currently buckets at `toStartOfHour`
(`clickhouse_setup/_schema.py:346`), which can't serve the dashboards'
`now-15m` default — the bucket covers data outside the window and its
timestamp usually precedes `$__from`. (Thanos and Elastic TSDB don't coarsen
in place either — they write a coarser copy and expire the finer one, routing
by window — so a tiered-tables design would be that same model, not a lesser
substitute.)

Preferred direction: one self-coarsening summary table via
`TTL … GROUP BY … SET`, MV-written at 5m grain, rolling up to hourly at ~14
days, retained 120 days overall — rather than three separate tables. Shape:

- Rollup key must be an `ORDER BY` prefix, so a coarse `time_hour DateTime`
  column leads the sort key and the fine `time_bucket` moves to the end:
  `ORDER BY (time_hour, request_template, request_operation,
  identity_applicative_provider, request_target, cluster_name, time_bucket)`,
  `PARTITION BY toYYYYMM(time_hour)`. MV writes both columns explicitly (no
  `MATERIALIZED` column — avoids the question of whether a computed column is
  legal inside a sorting key).
- Time stays first in the sort key despite `schema-pk-cardinality-order`:
  dims-first is also a legal prefix, but every dashboard query is
  time-bounded, and dims-first would leave a one-day query with only monthly
  partition pruning to work with.
- `SET` must name **every** state column — anything outside `GROUP BY` and
  outside `SET` is written as a default, i.e. an empty `AggregateFunction`
  state, silently. The list is mechanical to generate from the existing
  `_SUMMARY_AGGS` loop already shared by `summary_table_ddl` and
  `summary_mv_ddl` (`clickhouse_setup/_schema.py:166`).
- **Open question that decides the architecture:** whether `SET` accepts
  `-MergeState` combinators (`countMergeState(count_state)`,
  `quantilesMergeState(0.5, 0.95, 0.99)(pct_es_took_ms_state)`) — every
  documented ClickHouse example is `SET x = max(x)` on a plain column, not an
  `AggregateFunction`. Settle with a scratch `AggregatingMergeTree`, a few
  rows, a forced `OPTIMIZE`, and a read-back before committing to this shape.
  If it doesn't work, the known-good fallback is a second table fed by a
  cascading MV off the 5m table using `avgMergeState(...)` in its `SELECT` —
  standard rollup pattern, one more table and one more routing threshold, no
  unknowns.
- Operational edges: rollup is merge-driven and lazy
  (`merge_with_ttl_timeout` defaults to 4h and only governs when a part is
  *considered*), so parts can hold 5m rows past day 14 — aggregates stay
  correct, only point density changes; changed TTLs need
  `ALTER TABLE … MATERIALIZE TTL` for existing parts, same caveat already
  noted for `raw_table_index_additions_ddl` (`clickhouse_setup/_schema.py:455`);
  `tableSettings.summaryTtlClause` (`helm/alo/values.yaml:22`) is a
  full-clause override today and would silently delete the rollup clause if
  set — needs to become retention-only, or the rollup clause needs to compose
  separately from it; rewriting parts at the rollup boundary costs a one-time
  merge I/O spike; and `ORDER BY` is immutable
  (skill `clickhouse-best-practices`, rule `schema-pk-plan-before-creation`),
  so this is a new table plus `INSERT INTO … SELECT` from the current
  `alo_summary` — safe, since `AggregateFunction` columns copy across
  untouched, `time_hour` derives as `toStartOfHour(time_bucket)`, and
  `alo_summary` is the only source of truth past the 3-day raw TTL.

### Prerequisite measurement

The 5m grain only pays off if dimension cardinality is bounded — run this
first; `rows_per_combo` below ~5 means the 5m tier isn't worth building:

```sql
SELECT uniqExact(request_template) AS templates,
       uniqExact((request_template, request_operation,
                  identity_applicative_provider, request_target,
                  cluster_name)) AS combos,
       count() AS rows,
       count() / uniqExact((request_template, request_operation,
                            identity_applicative_provider, request_target,
                            cluster_name)) AS rows_per_combo
FROM alo.alo_raw
WHERE timestamp >= now() - INTERVAL 1 DAY
```

### Routing rule and the invariant

Raw for windows under ~1h and for every panel whose dimensions or metrics the
summary doesn't carry; summary otherwise. When a `username` / `client_host` /
`cost_indicator` filter is active, qualifying panels should fall back to raw
entirely rather than show summary data that silently ignores the filter —
past 3 days that means an empty panel, which is correct: the data to answer
the question is gone. Grafana can't pick a table per query, so the choice has
to live in SQL as branches guarded on the `$__fromTime` / `$__toTime`
literals, which ClickHouse folds to constants and prunes at query time.

Invariant to hold: **a grain's retention must exceed the largest window
routed to it.** Route a 30-day window at a 14-day-retention grain and the
chart silently starts 14 days in — the exact "invisible data" failure this
whole investigation was trying to avoid.

Also: `quantilesMerge` over rolled-up states is approximate and won't match a
raw `quantile()` exactly, so P95 will step slightly at a grain boundary —
visible, not wrong, worth a line in the panel description if this ships.

## Removed, not migrated

Two items from the original §9 list were dropped outright rather than moved:

- **Separate `cpu_stress_score` / `memory_stress_score`.** ALO has no
  cluster-side resource signal anywhere in the pipeline — nothing captures
  CPU or heap usage today, and nothing proposed would. Not a deferred task,
  a wish with no path to it.
- **`search_type` classification** (`agg`/`knn`/`geo`/`text`/`simple`).
  Redundant with the 16 `clause_counts_*` columns and 11 `cost_indicators_*`
  flags already emitted, at finer resolution. The original deferral note
  ("naive top-level detection misclassifies expensive clauses nested inside
  a `bool`") argued against the idea's own feasibility.
