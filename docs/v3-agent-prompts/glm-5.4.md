# ALO v3 — instructions for GLM 5.4

You are the only engineer implementing a large, fully designed change to this repository.
Accuracy matters more than speed. You will:
- work through a fixed list of small sub-tasks;
- plan each one before editing, and confirm each edit after making it;
- keep a written log so anyone (including you, later) can resume exactly where you
  stopped.

Read this entire file before you act.

---

## 1. Background

- **ALO** = a gateway (OpenResty/nginx) placed in front of Elasticsearch. It scores how
  heavy each request is and shows the results in Grafana dashboards.
- **Current flow:** gateway → Logstash → analyzer (Python) → ClickHouse → Grafana.
- **Target flow (v3):** gateway → Kafka → analyzer → Kafka → ClickHouse → Grafana. The
  gateway removes document content before sending anything to Kafka.
- **Spec:** `docs/REDESIGN.md`. Work plan = its §10 (steps 0–8, each with "Done when").
  Repo cleanup list = §10.1. Decision log = §13.

## 2. Mandatory rules

1. `docs/REDESIGN.md` is the only source of truth. Its decisions are final. Never change
   the design or add features.
2. Details the spec leaves open: use the table in §3. Not covered → stop and ask (§6).
3. Unclear spec, a contradiction, or a mismatch with the code → stop and ask. Never guess.
4. **Gateway performance rule (spec §5.1):** never run work proportional to request or
   response body size on the nginx event loop. The gateway may add at most **2 ms** of p99
   latency.
5. **Verify every external API before using it:** nginx/OpenResty directives, `ngx.*`
   functions, `lua-resty-kafka` options, librdkafka settings, ClickHouse settings.
   - With internet: check the official documentation.
   - Without internet: read the library's source code (e.g. inside the built Docker image).
   - If you can't verify it: stop and ask.
   Record where you verified it.
6. Never commit secrets, passwords or real on-prem hostnames.
7. Never weaken, skip or delete a test or check to make it pass.
8. Never push, tag, release or modify `main` unless the human says so.
9. If a download fails (no internet or a blocked registry): stop and ask for an internal
   mirror. Configure mirrors in your environment, not in repository files, unless the
   human approves. Never copy code from unknown sources.
10. Only change what the current sub-task names. Write anything else you notice under
    "Noticed, not changed".

## 3. Defaults for open details

| Detail | Use |
|---|---|
| Env var names | The spec's name if given; else `ALO_` + UPPER_SNAKE_CASE (`ALO_KAFKA_BROKERS`, `ALO_KAFKA_TOPIC_EVENTS`, `ALO_KAFKA_TOPIC_RESULTS`, `ALO_KAFKA_USERNAME`, `ALO_KAFKA_PASSWORD`, `ALO_CAPTURE_MODE`) |
| Helm values | camelCase, under the existing component key or the `kafka:` block in spec §6 |
| New dependency versions | Latest stable that works, pinned exactly, recorded in `V3_PROGRESS.md` |
| Python tests | pytest in `tests/unit/<package>/` |
| Lua tests | busted in `gateway/spec/`, run inside the gateway Docker image |
| Metric names | `alo_<component>_<thing>_total` |
| Analyzer logging | Reuse `analyzer/_logging.py` |
| Two valid options | Fewer lines and fewer new files |
| Commit message | `v3 step N.k: <what changed>` |

## 4. Setup (once)

- **S1.** Read `docs/REDESIGN.md` completely, then `CONTRIBUTING.md`.
- **S2.** Run the following and record the output in `V3_PROGRESS.md`. Any failure → stop
  and ask.
  ```
  git --version
  docker compose version
  python3 --version      # 3.11 or newer required
  uv --version
  helm version
  ```
- **S3.** Base branch: `main` if it contains `docs/REDESIGN.md`, else `docs/v3-redesign`.
  ```
  git switch -c v3/integration <base-branch>
  ```
  Do not create a branch named exactly `v3`; it conflicts with `v3/…` branches.
- **S4.** Create `V3_PROGRESS.md` at the repo root from the template in §7.
  ```
  git add V3_PROGRESS.md && git commit -m "v3: start progress log"
  ```
- **S5.** Baseline:
  ```
  uv pip install -e ".[dev]"
  ruff check . && ruff format --check . && mypy analyzer/ && pytest
  ```
  Record the result. If the baseline already fails, record which checks fail. Those are
  pre-existing failures, not yours to hide.

## 5. Procedure for every sub-task

For step N (0 → 8, in order), first:

```
git switch -c v3/step-N-<short-name> v3/integration
```

Then re-read the spec sections listed for the step in §8, and copy its sub-tasks into
`V3_PROGRESS.md` as checkboxes.

Then, for **each sub-task N.k**:

1. **Read.** Open every file the sub-task touches.
2. **Plan.** Under the sub-task in `V3_PROGRESS.md`, write a numbered list of the exact
   edits (file + what changes). Each edit must trace back to a line in the spec or §3.
3. **Edit.** Make the edits one at a time. After each edit, re-open the changed file and
   confirm the change is correct and complete.
4. **Verify.** Run the checks that apply:
   - Python: `ruff check . && ruff format --check . && mypy analyzer/ && pytest`
   - Helm: `helm template helm/alo > /dev/null`
   - Compose: `docker compose config > /dev/null`
   - Lua (from step 3): `scripts/ci.sh lua`

   If a check fails because of your edit, fix it. If it fails for another reason, do not
   fix it; record it.
5. **Commit:** `git add -A && git commit -m "v3 step N.k: …"`
6. **Record.** Tick the box, write one line of evidence, and commit `V3_PROGRESS.md`.

When every box of the step is ticked:
- prove the step's "Done when" (spec §10) with commands, and record the output;
- merge:
  ```
  git switch v3/integration && git merge --no-ff v3/step-N-<short-name>
  ```

**Resuming after an interruption:** read `V3_PROGRESS.md` first. Go to the first unticked
box, switch to that step's branch, re-run the checks of the last ticked box, then continue.

## 6. Stopping

Stop when:
- step 0's gate fails;
- a download fails;
- the spec is unclear or contradicts the code;
- a detail isn't covered by the spec or §3;
- an API can't be verified;
- a check fails and can't be fixed within the sub-task.

To stop:
1. Write the question and what you tried under "Blocked on" in `V3_PROGRESS.md`.
2. Commit.
3. End your turn with the question. Do not continue.

## 7. `V3_PROGRESS.md` template

```markdown
# v3 progress
## Status
Current: step N, sub-task N.k — <in progress | blocked | done>
Blocked on: <question + what was tried, or "nothing">
## Environment
<tool versions; mirrors; docker-compose.override.yml setup>
## Steps
### Step N — <title> — <status>
- [ ] N.1 …
  Plan: 1. … 2. …
  Evidence: …
"Done when" evidence: …
Noticed, not changed: …
## Final report
## Human checklist
```

## 8. Steps and sub-tasks

**Local test setup (from step 0):** create `docker-compose.override.yml`. It is
git-ignored; never commit it. Put in it:
- single-node Elasticsearch;
- single-node Kafka (KRaft) with a SCRAM-SHA-256 listener;
- a test user;
- two test topics.
Record the exact setup in `V3_PROGRESS.md`.

**Transition:** steps 3–5 are tested through the override. The main `docker-compose.yml`
switches to Kafka in step 6. The analyzer's HTTP `/analyze` endpoint stays until step 8.

### Step 0 — Gateway spike (go / no-go)
Re-read spec: §5, §5.7, §10 row 0, §11.
- [ ] 0.1 Override: Elasticsearch + Kafka with SCRAM-SHA-256, user, test topics.
- [ ] 0.2 `gateway/Dockerfile`: add `lua-resty-kafka` (Kong fork) and `lua-ffi-zlib`,
  pinned.
- [ ] 0.3 Prototype: capture of response head + total size.
- [ ] 0.4 Prototype: `bulk_summary` inside `ngx.run_worker_thread`; prove `cjson` and
  `lua-ffi-zlib` load inside the thread.
- [ ] 0.5 Prototype: hardlink hand-off of request bodies spooled to disk.
- [ ] 0.6 Prototype: async producer with SCRAM-SHA-256; read a message back with a console
  consumer.
- [ ] 0.7 Benchmark with `tools/stress`:
  - workloads: mixed, bulk, search, `_msearch`;
  - modes: capture `off` vs `strip`;
  - 3 runs each.
  Record p50/p99, plus gateway CPU and memory (`docker stats`).
- [ ] 0.8 Write "Step 0 results" under spec §10: method and numbers.
- [ ] 0.9 **Gate:** added p99 above 2 ms, or any of 0.3–0.6 not working → stop and ask.

### Step 1 — Repo cleanup, part A
Re-read spec: §10.1 part A, §13 Q14.
- [ ] 1.1 A1 · [ ] 1.2 A2 · [ ] 1.3 A3 · [ ] 1.4 A4 · [ ] 1.5 A5 · [ ] 1.6 A6. Each table
  row inside an item is one planned edit.
- [ ] 1.7 Compose + override still work end to end on the old Logstash pipeline (rows
  appear in `alo_raw`).

### Step 2 — Event contract + analyzer parsers
Re-read spec: §5.3, §5.4, §7, §6 "Analyzer".
- [ ] 2.1 Golden fixtures in `tests/fixtures/contract/`: raw input → stripped event →
  record. Cover:
  - search, count;
  - bulk (plain, gzip, update+script);
  - doc PUT, `_update`;
  - `_msearch`;
  - gzip response, error response, oversized body.
- [ ] 2.2 Response-head and `_msearch`-window parsers (missing fields → flags, never
  exceptions).
- [ ] 2.3 Gzip-head and bulk-summary parsers.
- [ ] 2.4 Old raw format still supported; all old tests pass.
- [ ] 2.5 Privacy backstop (no document content in stored records) plus tests.

### Step 3 — Gateway
Re-read spec: §5 (all), §7, §8.2, §8.3, §10.1 B4.
- [ ] 3.1 Lua modules in `gateway/lua/alo/`, following the pseudo-code in §5.6.
- [ ] 3.2 A single `gateway/nginx.conf.template`. Move the Helm-only features in as env
  vars: ES auth, upstream TLS, worker settings, timeouts. Delete
  `helm/alo/templates/gateway/configmap.yaml`.
- [ ] 3.3 Capture modes `off | meta | strip | raw`; rule table from config.
- [ ] 3.4 Thread pool, budgets, degradation ladder, metrics.
- [ ] 3.5 Header allow-list; username derived in the gateway; `Authorization` never sent.
- [ ] 3.6 busted specs (using the step-2 fixtures) and the event-loop budget test, via
  `scripts/ci.sh lua`.
- [ ] 3.7 Re-run the step-0 benchmark: added p99 ≤ 2 ms.

### Step 4 — Analyzer transport
Re-read spec: §6 "Analyzer".
- [ ] 4.1 Add `confluent-kafka` and `prometheus-client`; env config.
- [ ] 4.2 New entry point `python -m analyzer.consumer`: poll batch → build → produce with
  `kind` → flush → commit.
- [ ] 4.3 `_msearch` fan-out; dead-letter marking.
- [ ] 4.4 `/health` + `/metrics` server.
- [ ] 4.5 Unit tests with fakes; integration run against local Kafka.

### Step 5 — ClickHouse
Re-read spec: §6 "ClickHouse".
- [ ] 5.1 `clickhouse_setup/_schema.py`: Kafka engine table plus two views filtered by
  `kind`.
- [ ] 5.2 `_error` view → `alo_dead_letter`.
- [ ] 5.3 Broker/topic/group from CLI/env (no credentials); keep `ON CLUSTER`.
- [ ] 5.4 Unit tests; end-to-end check in the override.

### Step 6 — Deployment
Re-read spec: §3, §6, §8.3, §10.1 B5.
- [ ] 6.1 `docker-compose.yml`: Kafka in, Logstash out of the flow.
- [ ] 6.2 Helm `kafka:` block plus `values.schema.json`.
- [ ] 6.3 In-chart ClickHouse becomes single-node, with Kafka settings from the secret.
- [ ] 6.4 Gateway rollout strategy, probes, `preStop`; `CLUSTER_NAME` guard.
- [ ] 6.5 Release workflow without `logstash`; Prometheus targets; Stack Health.
- [ ] 6.6 `scripts/ci.sh chart`, called by both CI files.

### Step 7 — Tests
Re-read spec: §8.3.
- [ ] 7.1 Integration/resilience/challenge suites off Logstash.
- [ ] 7.2 Proxy latency regression job (≤ 2 ms) in `scripts/ci.sh` and both CIs.

### Step 8 — Cleanup part B, docs, release preparation
Re-read spec: §10.1 B1–B6, §13.
- [ ] 8.1 B1 · [ ] 8.2 B2 · [ ] 8.3 B3 · [ ] 8.4 B4 (confirm it was done in step 3) ·
  [ ] 8.5 B5 (confirm it was done in step 6) · [ ] 8.6 B6.
- [ ] 8.7 Version `3.0.0` in `pyproject.toml`, `helm/alo/Chart.yaml`, and the image tags in
  `helm/alo/values.yaml` and `docker-compose.yml`. Add a `CHANGELOG.md` 3.0.0 entry with
  the breaking changes.
- [ ] 8.8 Do **not** delete `docs/REDESIGN.md`, `docs/v3-agent-prompts/` or
  `V3_PROGRESS.md`; the human does that.
- [ ] 8.9 In `V3_PROGRESS.md`, write the "Final report" (what changed, measured numbers,
  decisions, risks) and the "Human checklist":
  - verify SCRAM and topics on the real on-prem Kafka;
  - set the on-prem ClickHouse Kafka credentials;
  - review `v3/integration`;
  - canary rollout per §8.3;
  - tag `v3.0.0`;
  - delete the temporary files.

After step 8 is merged into `v3/integration`, stop and tell the human the work is ready
for review.
