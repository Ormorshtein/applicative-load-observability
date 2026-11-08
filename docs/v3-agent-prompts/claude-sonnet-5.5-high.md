# ALO v3 — instructions for Claude Sonnet 5.5 (high effort)

You will carry out the whole ALO v3 redesign in this repository on your own: steps 0 to 8,
in order, ending with a branch ready for human review. These instructions break each step
into sub-tasks. Work through them one at a time and check each before moving on.

---

## 1. Context in one paragraph

ALO is a transparent gateway (OpenResty) in front of Elasticsearch that scores how heavy
each request is and shows it in Grafana. Today the gateway posts full request/response
bodies to Logstash, which calls the analyzer and writes to ClickHouse. **v3** removes
Logstash:

```
gateway → Kafka (topic 1) → analyzer → Kafka (topic 2) → ClickHouse
```

The gateway strips document content first. The full spec is `docs/REDESIGN.md`. The work
plan is §10, and the repo cleanup is §10.1.

## 2. Rules (apply to every step)

1. **The spec decides.** Its decisions (§13) are final. If a detail is open, take the
   simplest option that satisfies the spec and record it in `V3_PROGRESS.md`.
2. **Ambiguity or contradiction → stop and ask** (see §5). Don't guess.
3. **Gateway rule (§5.1):** nothing proportional to body size on the nginx event loop.
   Proxy overhead ≤ **2 ms at p99**.
4. **No invented APIs.** Check each nginx/OpenResty, `ngx.*`, `lua-resty-kafka`, librdkafka
   and ClickHouse setting in its docs or source before using it. Note where.
5. **No secrets or real on-prem hostnames** in git.
6. **Evidence:** each "Done when" item needs a command and its output in
   `V3_PROGRESS.md`. Never weaken a test or gate.
7. **Never push, tag, release or touch `main`** unless the human says so.
8. **Scope:** only what the spec lists. Other findings go under "Noticed, not changed".

## 3. Setup (once)

1. Read `docs/REDESIGN.md` from start to finish, then `CONTRIBUTING.md`.
2. Run and record: `git --version`, `docker compose version`, `python3 --version` (≥ 3.11),
   `uv --version`, `helm version`. If one is missing, stop and ask.
3. Base branch = the one containing `docs/REDESIGN.md` (`main` if merged, otherwise
   `docs/v3-redesign`). Run `git switch -c v3/integration <base>`. (Don't use the name
   `v3`; git can't have `v3` and `v3/…` branches together.)
4. Create `V3_PROGRESS.md` from the template in §6, then
   `git add V3_PROGRESS.md && git commit -m "v3: start progress log"`.
5. Install dev deps: `uv pip install -e ".[dev]"`. Run the four checks below once to get a
   baseline, and record the result:
   ```
   ruff check . && ruff format --check . && mypy analyzer/ && pytest
   ```

## 4. The loop for each step N

1. `git switch -c v3/step-N-<slug> v3/integration`
2. Read the spec sections named in the step, then every file you'll change.
3. Write the step plan in `V3_PROGRESS.md` (sub-tasks below plus how you'll prove "Done
   when").
4. For each sub-task: change → run the relevant checks → commit (`v3 step N.k: …`).
5. At the end of the step, run the full checks plus the step's own checks. Record the
   evidence.
6. `git switch v3/integration && git merge --no-ff v3/step-N-<slug>`
7. Mark the step done in `V3_PROGRESS.md`, commit, and continue.

**Resuming:** if `V3_PROGRESS.md` exists when you start, read it first. Continue at the
first unfinished sub-task, and re-run the checks of the last finished one before going on.

## 5. Stop and wait for the human when

- step 0 fails its gate (step 0.7);
- a download fails (no internet or a blocked registry). Ask for a mirror URL; never copy
  code from an unknown source;
- the spec is ambiguous or contradicts the code;
- a check fails and fixing it needs something outside the spec.

Put the question under "Blocked on" in `V3_PROGRESS.md`, commit, and end your turn with
the question.

## 6. `V3_PROGRESS.md` template

```markdown
# v3 progress
## Status
Current step: N.k — <title> — <in progress | blocked | done>
Blocked on: <question, or "nothing">
## Environment
<tool versions; how docker-compose.override.yml is set up>
## Steps
### Step N — <title> — <status>
Plan: …
- [ ] N.1 …
Evidence: <command → result for each "Done when" item>
Decisions made inside the spec: …
Noticed, not changed: …
## Final report
## Human checklist
```

## 7. Steps and sub-tasks

> **Local test environment.** The repo's compose file doesn't run Elasticsearch, and
> Kafka arrives only in step 6. For local end-to-end tests, use
> `docker-compose.override.yml` (git-ignored) to add a single-node Elasticsearch and a
> single-node Kafka (KRaft) with a SCRAM-SHA-256 listener, a test user, and two test
> topics. Write the setup into `V3_PROGRESS.md`.
>
> **Transition period.** From step 3 to step 6 the gateway produces to Kafka while the
> main `docker-compose.yml` still describes the Logstash flow. Test through your override
> during that time; step 6 switches compose for good. The analyzer's HTTP `/analyze`
> stays in place until step 8 (§10.1 B2) removes it.

### Step 0 — Gateway spike (go/no-go)
Read: §5 (all), §5.7, §10 row 0, §11.
- 0.1 Set up the override: Elasticsearch + Kafka with SCRAM-SHA-256, a user, test topics.
- 0.2 In `gateway/Dockerfile`, add `lua-resty-kafka` (Kong fork) and `lua-ffi-zlib`, each
  pinned to an exact version or commit.
- 0.3 Prototype only:
  - head + size capture;
  - `bulk_summary` running in `ngx.run_worker_thread` (with `cjson` and `lua-ffi-zlib`
    loaded inside the thread);
  - the hardlink hand-off of spooled bodies;
  - an async producer with SCRAM-SHA-256.
- 0.4 Prove each mechanism separately: send a request, then read the message back with a
  console consumer.
- 0.5 Benchmark with `tools/stress` through the gateway:
  - workloads: mixed, bulk-heavy, search-heavy, `_msearch`;
  - modes: capture `off` vs `strip`;
  - same duration, at least 3 runs each.
  Record p50/p99, plus gateway CPU and memory (`docker stats`).
- 0.6 Add "Step 0 results" under REDESIGN.md §10: method, hardware and numbers.
- 0.7 **Gate.** Added p99 > 2 ms, or any mechanism in 0.3 not working → **stop** (§5) and
  name the fallback from §5.7 or §11. Otherwise continue.
  Add "verify SCRAM against the real on-prem Kafka" to the human checklist.

### Step 1 — Repo cleanup, part A
Read: §10.1 part A, §13 Q14.
- 1.1–1.6 = items A1–A6, in order, one commit each. Treat each table row as a checkbox.
- 1.7 Prove the compose stack (plus your override) still runs end to end on the 2.x
  Logstash pipeline: send traffic and see rows in `alo_raw`.

### Step 2 — Event contract + analyzer parsers
Read: §5.3, §5.4, §7, §6 "Analyzer".
- 2.1 Add golden fixtures in `tests/fixtures/contract/`: raw request/response → expected
  stripped event → expected record. Cover:
  - search, count;
  - bulk (plain, gzip, with update+script);
  - single doc PUT, `_update`;
  - `_msearch`;
  - a gzip search response;
  - an error response;
  - an oversized body.
- 2.2 Write parsers for the response head and `_msearch` windows (tolerant: missing fields
  → flags, never exceptions), the gzip head, and the bulk summary.
- 2.3 Keep the raw (v1) path working. All existing tests stay green.
- 2.4 Add the privacy backstop (`doc`/`upsert` content never reaches a stored record),
  with tests.

### Step 3 — Gateway
Read: §5 (all), §7 identity, §8.2, §8.3, §10.1 B4.
- 3.1 Add modules under `gateway/lua/alo/`: `capture`, `process`, `strip`, `rules`,
  `producer`, `identity`, `budget`, `init` (§5.6 pseudo-code).
- 3.2 Use one `gateway/nginx.conf.template`. Move into it, as env vars, the Helm-only
  features: ES auth injection, upstream TLS, worker settings, timeouts. Delete
  `helm/alo/templates/gateway/configmap.yaml`, and make Helm set env instead.
- 3.3 Capture modes `off | meta | strip | raw`. Rule table from config. Thread pool, queue
  and in-flight budget. Degradation ladder with `degraded{reason}` and `dropped{reason}`
  metrics.
- 3.4 Header allow-list plus the username derived in the gateway. `Authorization` never
  leaves the gateway.
- 3.5 Add busted specs against the step-2 fixtures, and the event-loop budget test. Wire
  them into `scripts/ci.sh lua` (run inside the gateway image).
- 3.6 Re-run the step-0 benchmark; added p99 must be ≤ 2 ms.

### Step 4 — Analyzer transport
Read: §6 "Analyzer".
- 4.1 Add `confluent-kafka` and `prometheus-client`. Config through env: brokers, SASL,
  topics, group, batch size.
- 4.2 Add a new entry point (e.g. `python -m analyzer.consumer`): poll a batch → build
  records → produce with `kind` → flush → commit.
- 4.3 Implement `_msearch` fan-out, and dead-letter marking for unparseable input, unknown
  operations and build errors.
- 4.4 Add a small `/health` + `/metrics` server (lag, throughput, errors).
- 4.5 Add unit tests with fake consumer/producer, and an integration run against local
  Kafka. `build_record` stays unchanged.

### Step 5 — ClickHouse
Read: §6 "ClickHouse".
- 5.1 In `_schema.py`, add:
  - the Kafka engine table on topic 2;
  - views filtered by `kind = 'record'` / `'dead_letter'`;
  - the `_error` view to the dead letter.
- 5.2 Broker, topic and group come from setup CLI/env. No credentials.
- 5.3 Keep `ON CLUSTER` mode for external clusters. Extend `tests/unit/clickhouse_setup/`.
- 5.4 Prove it end to end in the override: records land in `alo_raw`, and a malformed
  message lands in `alo_dead_letter`.

### Step 6 — Deployment
Read: §3 topology, §6 "Kafka" and "Deployment changes", §8.3, §10.1 B5.
- 6.1 Compose: add Kafka (KRaft, dev only); the gateway → Kafka → analyzer → ClickHouse
  flow; Logstash no longer in the flow.
- 6.2 Helm: add the `kafka:` block (§6). The in-chart ClickHouse becomes single-node, with
  Kafka settings from the secret. Rollout `maxUnavailable: 0` / `maxSurge: 1`, probes on,
  `preStop`. Refuse an empty or default `CLUSTER_NAME` when Kafka is on.
  Update `values.schema.json`.
- 6.3 Release workflow: drop the `logstash` image. Prometheus: add Kafka/analyzer targets.
  Stack Health dashboard: regenerate.
- 6.4 Add `scripts/ci.sh chart` (`helm lint` + `helm template`), called from both CIs.

### Step 7 — Tests
Read: §8.3.
- 7.1 Move the integration, resilience and challenge suites off Logstash.
- 7.2 Add the proxy latency regression job (capture `off` vs `strip`, fail above 2 ms
  added p99) to `scripts/ci.sh` and both CIs.

### Step 8 — Cleanup part B, docs, release prep
Read: §10.1 B1–B6, §13.
- 8.1–8.6 = items B1–B6, one commit each. This includes deleting the analyzer HTTP app
  (B2) and every Logstash leftover (B1).
- 8.7 Set version `3.0.0` in `pyproject.toml`, `helm/alo/Chart.yaml`, and the image tags in
  `values.yaml` and `docker-compose.yml`. Write the `CHANGELOG.md` 3.0.0 entry (breaking
  changes listed).
- 8.8 **Keep** `docs/REDESIGN.md`, `docs/v3-agent-prompts/` and `V3_PROGRESS.md`; the
  human deletes them at release.
- 8.9 Write the final report (what changed, measured numbers, decisions, risks) and the
  human checklist:
  - real Kafka/SCRAM check;
  - on-prem ClickHouse Kafka credentials;
  - review `v3/integration`;
  - canary per §8.3;
  - tag `v3.0.0`;
  - delete the temporary files.
