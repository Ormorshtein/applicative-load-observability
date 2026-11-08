# ALO v3 — instructions for Kimi 2.7

ROLE: You are a careful software engineer. You alone will carry out a large, already-designed
change to this repository, one small task at a time. The design is finished; your job is
to implement it exactly, prove each part works, and keep a written log so the work can be
resumed at any time.

Read this whole file before doing anything.

---

## 1. What the project is and what changes

- **ALO** is a gateway (OpenResty/nginx) in front of Elasticsearch. It measures how heavy
  each request is and shows the results in Grafana.
- **Today:** gateway → Logstash → analyzer (Python) → ClickHouse → Grafana.
- **v3 (what you build):** gateway → Kafka → analyzer → Kafka → ClickHouse → Grafana. The
  gateway removes document content from requests and responses before sending them to
  Kafka.
- **The complete spec** is `docs/REDESIGN.md`. The ordered work plan is its §10 (steps 0–8,
  each with a "Done when"). The repo cleanup list is §10.1.

## 2. Rules — always follow these

DO:
1. Treat `docs/REDESIGN.md` as the only source of truth. Its decisions (§13) are final.
2. For details the spec leaves open, use the defaults in §3 of this file.
3. **Re-read** the spec sections for a step at the start of that step. Do not rely on
   memory from earlier steps.
4. Prove every "Done when" item by running a command. Paste the command and its key output
   into `V3_PROGRESS.md`.
5. Commit after every sub-task, and update `V3_PROGRESS.md` after every sub-task.
6. Before using any nginx/OpenResty directive, `ngx.*` function, `lua-resty-kafka` option,
   librdkafka setting or ClickHouse setting, confirm it exists and behaves as you expect:
   - read its official documentation; or, if you have no internet,
   - read the library's own source code (for example inside the built Docker image).
   Write where you confirmed it.

DO NOT:
1. Do not change the design, add features, or "improve" things the spec doesn't ask for.
2. Do not guess. If the spec is unclear, contradicts itself, or contradicts the code, stop
   (§6).
3. Do not do any work proportional to body size on the nginx event loop (spec §5.1). The
   gateway may add at most **2 ms at p99** latency.
4. Do not commit secrets, passwords, or real on-prem hostnames.
5. Do not weaken, skip, or delete a test or check to make it pass.
6. Do not push, tag, release, or change the `main` branch unless the human tells you to.
7. Do not copy code from unknown sources. If a download fails, stop and ask for a mirror.

## 3. Defaults for details the spec leaves open

| Detail | Use |
|---|---|
| Env var names | The name in the spec if given; otherwise `ALO_` + UPPER_SNAKE_CASE (e.g. `ALO_KAFKA_BROKERS`, `ALO_KAFKA_TOPIC_EVENTS`, `ALO_KAFKA_TOPIC_RESULTS`, `ALO_KAFKA_USERNAME`, `ALO_KAFKA_PASSWORD`, `ALO_CAPTURE_MODE`) |
| Helm values | camelCase, under the existing component key or the `kafka:` block in spec §6 |
| New dependency versions | Latest stable that works, pinned to an exact version; record it in `V3_PROGRESS.md` |
| Python tests | pytest, in `tests/unit/<package>/` |
| Lua tests | busted, in `gateway/spec/`, run inside the gateway Docker image |
| Metric names | `alo_<component>_<thing>_total` |
| Logging in the analyzer | Reuse `analyzer/_logging.py` |
| Two valid options | The one with fewer lines and fewer new files |
| Commit message | `v3 step N.k: <what changed>` |

Anything not covered by the spec or this table → stop and ask.

## 4. Setup — do once, in this order

1. Read `docs/REDESIGN.md` (all of it), then `CONTRIBUTING.md`.
2. Run these and save the output in `V3_PROGRESS.md`:
   ```
   git --version
   docker compose version
   python3 --version        # must be 3.11 or newer
   uv --version
   helm version
   ```
   If any command fails → stop and ask.
3. Find the base branch: `main` if it contains `docs/REDESIGN.md`, otherwise
   `docs/v3-redesign`. Then:
   ```
   git switch -c v3/integration <base-branch>
   ```
   (Never create a branch named exactly `v3`. Git can't have it next to `v3/…` branches.)
4. Create `V3_PROGRESS.md` at the repository root using the template in §7, then:
   ```
   git add V3_PROGRESS.md
   git commit -m "v3: start progress log"
   ```
5. Install and run the baseline checks. Save the result:
   ```
   uv pip install -e ".[dev]"
   ruff check . && ruff format --check . && mypy analyzer/ && pytest
   ```
6. **If you have no internet access** (for example on-prem), downloads of Python packages,
   Docker images or Lua libraries will fail. Ask the human for the internal mirrors, and
   configure them in your environment (pip config, Docker registry mirror). Do not
   hard-code mirror URLs into repository files without asking.

## 5. How to do each step

For step N (0 to 8, in order):

1. `git switch -c v3/step-N-<short-name> v3/integration`
2. Re-read the spec sections listed for the step in §8.
3. Copy the step's sub-tasks into `V3_PROGRESS.md` as checkboxes. Commit.
4. For each sub-task:
   - a. Read every file the sub-task touches.
   - b. Make the change.
   - c. Run the checks:
     - Python changed: `ruff check . && ruff format --check . && mypy analyzer/ && pytest`
     - Helm changed: `helm template helm/alo > /dev/null`
     - Compose changed: `docker compose config > /dev/null`
     - Lua changed (from step 3 on): `scripts/ci.sh lua`
   - d. Commit: `git commit -am "v3 step N.k: …"` (add new files with `git add` first).
   - e. Tick the box in `V3_PROGRESS.md`, add one line of evidence, and commit.
5. When all boxes are ticked, prove the step's "Done when" (spec §10) and record the proof.
6. Merge:
   ```
   git switch v3/integration
   git merge --no-ff v3/step-N-<short-name>
   ```

**If you are starting again after an interruption:** read `V3_PROGRESS.md` first. Find
the first unticked box. Switch to that step's branch. Re-run the checks for the last
ticked box. Then continue.

## 6. When to stop and ask the human

Stop when:
- step 0's gate fails;
- a download fails;
- the spec is unclear or contradicts the code;
- something isn't covered by the spec or §3;
- a check fails and you can't fix it inside the current sub-task;
- you can't confirm an API (rule DO 6).

How to stop:
1. Write the question under "Blocked on" at the top of `V3_PROGRESS.md`. Include what you
   tried.
2. Commit.
3. End your turn by asking that question. Do not continue past it.

## 7. `V3_PROGRESS.md` template

```markdown
# v3 progress
## Status
Current: step N, sub-task N.k — <in progress | blocked | done>
Blocked on: <question and what was tried, or "nothing">
## Environment
<tool versions; mirrors used; how docker-compose.override.yml is set up>
## Steps
### Step N — <title> — <status>
- [ ] N.1 … — evidence: …
"Done when" evidence: …
Noticed, not changed: …
## Final report
## Human checklist
```

## 8. The steps

**Local test setup (needed from step 0):** create `docker-compose.override.yml`. It is
git-ignored, so it is never committed. Put in it:
- a single-node Elasticsearch;
- a single-node Kafka (KRaft mode) with a SCRAM-SHA-256 listener;
- a test user;
- two test topics.
Write the exact setup into `V3_PROGRESS.md`.

**Transition:** in steps 3–5, test through the override. The main `docker-compose.yml`
switches to Kafka in step 6. The analyzer's HTTP endpoint `/analyze` stays until step 8.

### Step 0 — Gateway spike (decides go / no-go)
Re-read: spec §5, §5.7, §10 row 0, §11.
- [ ] 0.1 Override: Elasticsearch + Kafka with SCRAM-SHA-256, user, test topics.
- [ ] 0.2 `gateway/Dockerfile`: add `lua-resty-kafka` (Kong fork) and `lua-ffi-zlib`,
  pinned.
- [ ] 0.3 Prototype head + size capture of responses.
- [ ] 0.4 Prototype `bulk_summary` inside `ngx.run_worker_thread`; confirm `cjson` and
  `lua-ffi-zlib` load inside the thread.
- [ ] 0.5 Prototype the hardlink hand-off of request bodies spooled to disk.
- [ ] 0.6 Prototype the async Kafka producer with SCRAM-SHA-256. Read a message back with a
  console consumer.
- [ ] 0.7 Benchmark with `tools/stress` through the gateway:
  - workloads: mixed, bulk, search, `_msearch`;
  - modes: capture `off` vs `strip`;
  - 3 runs each.
  Record p50 and p99 latency, and gateway CPU and memory (`docker stats`).
- [ ] 0.8 Write a "Step 0 results" subsection under spec §10 with the method and numbers.
- [ ] 0.9 **Gate:** if the added p99 is above 2 ms, or any of 0.3–0.6 does not work →
  stop and ask.

### Step 1 — Repo cleanup, part A
Re-read: spec §10.1 part A, §13 Q14.
- [ ] 1.1 Item A1 · [ ] 1.2 A2 · [ ] 1.3 A3 · [ ] 1.4 A4 · [ ] 1.5 A5 · [ ] 1.6 A6
  (each table row inside an item is one change; do them in order).
- [ ] 1.7 Compose + override still run end to end on the old Logstash pipeline: send
  traffic, see rows in ClickHouse table `alo_raw`.

### Step 2 — Event contract + analyzer parsers
Re-read: spec §5.3, §5.4, §7, §6 "Analyzer".
- [ ] 2.1 Golden fixtures in `tests/fixtures/contract/`: raw input → expected stripped
  event → expected record. Cover:
  - search, count;
  - bulk (plain, gzip, update+script);
  - doc PUT, `_update`;
  - `_msearch`;
  - gzip response, error response, oversized body.
- [ ] 2.2 Response-head and `_msearch`-window parsers. Missing fields set flags, never raise.
- [ ] 2.3 Gzip-head and bulk-summary parsers.
- [ ] 2.4 The old raw format still works; all old tests pass.
- [ ] 2.5 Privacy backstop (document content never reaches a stored record) plus tests.

### Step 3 — Gateway
Re-read: spec §5 (all), §7, §8.2, §8.3, §10.1 B4.
- [ ] 3.1 Lua modules in `gateway/lua/alo/` following the pseudo-code in spec §5.6.
- [ ] 3.2 One `gateway/nginx.conf.template`. Move the Helm-only features into it as env
  vars: ES auth, upstream TLS, worker settings, timeouts. Delete
  `helm/alo/templates/gateway/configmap.yaml`.
- [ ] 3.3 Capture modes (`off`, `meta`, `strip`, `raw`) and the rule table from config.
- [ ] 3.4 Thread pool, budgets, degradation ladder, metrics.
- [ ] 3.5 Header allow-list; the username is derived in the gateway; `Authorization` is
  never sent.
- [ ] 3.6 busted specs using the step-2 fixtures, plus the event-loop budget test, run by
  `scripts/ci.sh lua`.
- [ ] 3.7 Re-run the step-0 benchmark: the added p99 must be ≤ 2 ms.

### Step 4 — Analyzer transport
Re-read: spec §6 "Analyzer".
- [ ] 4.1 Dependencies (`confluent-kafka`, `prometheus-client`) and env config.
- [ ] 4.2 New entry point `python -m analyzer.consumer`: poll batch → build records →
  produce with `kind` → flush → commit offsets.
- [ ] 4.3 `_msearch` fan-out, and dead-letter marking.
- [ ] 4.4 Small `/health` + `/metrics` HTTP server.
- [ ] 4.5 Unit tests with fake consumer/producer, plus an integration run against local
  Kafka.

### Step 5 — ClickHouse
Re-read: spec §6 "ClickHouse".
- [ ] 5.1 In `clickhouse_setup/_schema.py`: Kafka engine table plus the two views filtered
  by `kind`.
- [ ] 5.2 View on `_error` → `alo_dead_letter`.
- [ ] 5.3 Broker, topic and group come from CLI/env (no credentials). Keep `ON CLUSTER`
  mode.
- [ ] 5.4 Unit tests, plus an end-to-end check in the override.

### Step 6 — Deployment
Re-read: spec §3, §6, §8.3, §10.1 B5.
- [ ] 6.1 `docker-compose.yml`: add Kafka; take Logstash out of the flow.
- [ ] 6.2 Helm `kafka:` block plus `values.schema.json`.
- [ ] 6.3 In-chart ClickHouse becomes single-node, with Kafka settings from the secret.
- [ ] 6.4 Gateway rollout strategy, probes, `preStop`. Refuse an empty or default
  `CLUSTER_NAME`.
- [ ] 6.5 Release workflow (no `logstash` image), Prometheus targets, Stack Health
  dashboard.
- [ ] 6.6 `scripts/ci.sh chart`, called from both `.github/workflows/ci.yml` and
  `.gitlab-ci.yml`.

### Step 7 — Tests
Re-read: spec §8.3.
- [ ] 7.1 Integration, resilience and challenge suites no longer use Logstash.
- [ ] 7.2 Proxy latency regression job (fails above 2 ms added p99) in `scripts/ci.sh` and
  both CIs.

### Step 8 — Cleanup part B, docs, release preparation
Re-read: spec §10.1 B1–B6, §13.
- [ ] 8.1 B1 · [ ] 8.2 B2 · [ ] 8.3 B3 · [ ] 8.4 B4 (check it was done in step 3) ·
  [ ] 8.5 B5 (check it was done in step 6) · [ ] 8.6 B6.
- [ ] 8.7 Version `3.0.0` in `pyproject.toml`, `helm/alo/Chart.yaml`, and the image tags in
  `helm/alo/values.yaml` and `docker-compose.yml`. Add a `CHANGELOG.md` 3.0.0 entry that
  lists the breaking changes.
- [ ] 8.8 Do **not** delete `docs/REDESIGN.md`, `docs/v3-agent-prompts/` or
  `V3_PROGRESS.md`. The human deletes them.
- [ ] 8.9 Write the "Final report" in `V3_PROGRESS.md`: what changed, measured numbers,
  decisions, risks. Write the "Human checklist":
  - verify SCRAM and topics against the real on-prem Kafka;
  - set the on-prem ClickHouse Kafka credentials;
  - review `v3/integration`;
  - canary rollout per spec §8.3;
  - tag `v3.0.0`;
  - delete the temporary files.

When step 8 is merged into `v3/integration`, stop and tell the human the work is ready
for review.
