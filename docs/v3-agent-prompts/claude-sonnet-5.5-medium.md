# ALO v3 — instructions for Claude Sonnet 5.5 (medium effort)

You will carry out the whole ALO v3 redesign in this repository, steps 0 to 8, alone and
in order. Work on **one sub-task at a time**: do it, check it, commit it, record it, then
move on. Don't make design choices of your own. The spec and the defaults below cover
them; if they don't, stop and ask.

---

## 1. What this is

- **Today:** gateway (OpenResty) → Logstash → analyzer → ClickHouse → Grafana.
- **v3:** gateway → Kafka → analyzer → Kafka → ClickHouse → Grafana. The gateway strips
  document content before producing.
- **Spec:** `docs/REDESIGN.md`. Work plan: §10. Repo cleanup: §10.1.

## 2. Rules

1. The spec's decisions are final (§13). Do not reopen them.
2. Open details: use §3 "Defaults". Not covered there → stop and ask.
3. Spec ambiguous, or contradicts the code → stop and ask.
4. **Gateway rule (§5.1):** nothing proportional to body size on the nginx event loop.
   Proxy overhead ≤ 2 ms at p99.
5. Don't invent APIs. Check every nginx/OpenResty, `ngx.*`, `lua-resty-kafka`, librdkafka
   and ClickHouse setting in its docs or source first. Note where.
6. No secrets or real on-prem hostnames in git.
7. Every "Done when" item needs a command and its output in `V3_PROGRESS.md`. Never weaken
   a test or gate.
8. Never push, tag, release or touch `main` unless the human says so.
9. Change only what the sub-task says. Put anything else under "Noticed, not changed".

## 3. Defaults for details the spec leaves open

| Detail | Default |
|---|---|
| Env var names | The name used in the spec if there is one; otherwise `ALO_` + upper snake case (e.g. `ALO_KAFKA_BROKERS`, `ALO_KAFKA_TOPIC_EVENTS`, `ALO_KAFKA_TOPIC_RESULTS`, `ALO_KAFKA_USERNAME`, `ALO_KAFKA_PASSWORD`, `ALO_CAPTURE_MODE`) |
| Helm values | camelCase, under the existing component key or the `kafka:` block shown in §6 |
| New dependency versions | Latest stable that works, pinned exactly; record the version in `V3_PROGRESS.md` |
| Python tests | pytest, under `tests/unit/<package>/` |
| Lua tests | busted, under `gateway/spec/`, run inside the gateway image |
| Metrics names | `alo_<component>_<thing>_total` (matches existing metrics) |
| Logging | Reuse `analyzer/_logging.py` |
| Two options both satisfy the spec | The one with fewer lines and fewer new files |
| Commit messages | `v3 step N.k: <what changed>` |

## 4. Setup (once)

1. Read `docs/REDESIGN.md` fully, then `CONTRIBUTING.md`.
2. Run and record: `git --version`, `docker compose version`, `python3 --version` (must be
   ≥ 3.11), `uv --version`, `helm version`. Any missing → stop and ask.
3. Base branch = the one containing `docs/REDESIGN.md` (`main` if merged, else
   `docs/v3-redesign`). Run `git switch -c v3/integration <base>`. Don't name a branch
   just `v3`.
4. Create `V3_PROGRESS.md` (template in §7) and commit it.
5. `uv pip install -e ".[dev]"`, then run the baseline checks and record the result:
   `ruff check . && ruff format --check . && mypy analyzer/ && pytest`

## 5. The loop

For each step N:
1. `git switch -c v3/step-N-<slug> v3/integration`
2. Read the spec sections the step names.
3. Copy the step's sub-tasks into `V3_PROGRESS.md` as checkboxes.
4. For each sub-task, in order:
   1. read the files it touches;
   2. make the change;
   3. run the checks that apply (Python: the four checks; chart:
      `helm template helm/alo`; compose: `docker compose config`; Lua:
      `scripts/ci.sh lua` once it exists);
   4. commit;
   5. tick the box, write one line of evidence, and commit `V3_PROGRESS.md`.
5. When every box is ticked, prove the step's "Done when" (§10) and record it.
6. `git switch v3/integration && git merge --no-ff v3/step-N-<slug>`

**Resuming:** always read `V3_PROGRESS.md` first. Continue at the first unticked box.
Re-run the previous sub-task's checks before continuing.

## 6. Stop and wait for the human when

- step 0 fails its gate;
- a download fails (ask for a mirror; never copy code from an unknown source);
- the spec is unclear or contradicts the code;
- a detail isn't covered by the spec or §3;
- a check fails and can't be fixed inside the sub-task.

Write the question under "Blocked on" in `V3_PROGRESS.md`, commit, and end your turn with
the question.

## 7. `V3_PROGRESS.md` template

```markdown
# v3 progress
## Status
Current: step N, sub-task N.k — <in progress | blocked | done>
Blocked on: <question, or "nothing">
## Environment
<tool versions; docker-compose.override.yml setup>
## Steps
### Step N — <title> — <status>
- [ ] N.1 … — evidence: …
"Done when" evidence: …
Noticed, not changed: …
## Final report
## Human checklist
```

## 8. Steps and sub-tasks

> **Local test environment:** use `docker-compose.override.yml` (git-ignored) for a
> single-node Elasticsearch and a single-node Kafka (KRaft) with SCRAM-SHA-256, a test user
> and two test topics. Record the setup.
> **Transition:** steps 3–5 are tested through the override; the main compose file
> switches in step 6. The analyzer's HTTP `/analyze` stays until step 8 (B2).

**Step 0 — Gateway spike (go/no-go).** Read §5, §5.7, §10 row 0, §11.
- 0.1 Override with Elasticsearch + Kafka (SCRAM-SHA-256, user, test topics).
- 0.2 `gateway/Dockerfile`: add `lua-resty-kafka` (Kong fork) and `lua-ffi-zlib`, pinned.
- 0.3 Prototype: head + size capture.
- 0.4 Prototype: `bulk_summary` in `ngx.run_worker_thread` (load `cjson` and `lua-ffi-zlib`
  in the thread).
- 0.5 Prototype: hardlink hand-off of spooled bodies.
- 0.6 Prototype: async producer with SCRAM-SHA-256. Read the message back with a console
  consumer.
- 0.7 Benchmark with `tools/stress`:
  - workloads: mixed, bulk, search, `_msearch`;
  - modes: capture `off` vs `strip`;
  - 3 runs each.
  Record p50/p99 and gateway CPU/memory.
- 0.8 Add "Step 0 results" under REDESIGN.md §10.
- 0.9 **Gate:** added p99 > 2 ms, or any of 0.3–0.6 failing → stop and ask (§6).

**Step 1 — Cleanup part A.** Read §10.1 part A, §13 Q14.
- 1.1 A1 · 1.2 A2 · 1.3 A3 · 1.4 A4 · 1.5 A5 · 1.6 A6. Each table row is one checkbox.
- 1.7 Compose + override still run end to end on the 2.x pipeline (rows appear in
  `alo_raw`).

**Step 2 — Contract + parsers.** Read §5.3, §5.4, §7, §6 "Analyzer".
- 2.1 Golden fixtures in `tests/fixtures/contract/`:
  - search, count;
  - bulk (plain, gzip, update+script);
  - doc PUT, `_update`;
  - `_msearch`;
  - gzip response, error response, oversized body.
- 2.2 Response-head and `_msearch`-window parsers (missing fields → flags, not exceptions).
- 2.3 Gzip-head and bulk-summary parsers.
- 2.4 Raw (v1) path still works; all old tests green.
- 2.5 Privacy backstop plus tests.

**Step 3 — Gateway.** Read §5, §7, §8.2, §8.3, §10.1 B4.
- 3.1 Modules in `gateway/lua/alo/` per §5.6.
- 3.2 One `nginx.conf.template`. Move the Helm-only features in as env vars. Delete
  `helm/alo/templates/gateway/configmap.yaml`.
- 3.3 Capture modes and the rule table from config.
- 3.4 Thread pool, budgets, degradation ladder, metrics.
- 3.5 Header allow-list plus the username derived in the gateway.
- 3.6 busted specs (step-2 fixtures) and the event-loop budget test, via `scripts/ci.sh lua`.
- 3.7 Re-benchmark: ≤ 2 ms.

**Step 4 — Analyzer transport.** Read §6 "Analyzer".
- 4.1 Dependencies and env config.
- 4.2 New entry point `python -m analyzer.consumer`: poll → build → produce (`kind`) →
  flush → commit.
- 4.3 `_msearch` fan-out and dead-letter marking.
- 4.4 `/health` + `/metrics` server.
- 4.5 Unit tests with fakes, and an integration run against local Kafka.

**Step 5 — ClickHouse.** Read §6 "ClickHouse".
- 5.1 Kafka engine table plus the two `kind` views.
- 5.2 `_error` view to the dead letter.
- 5.3 Settings from CLI/env (no credentials). `ON CLUSTER` kept.
- 5.4 Unit tests, and an end-to-end check in the override.

**Step 6 — Deployment.** Read §3, §6, §8.3, §10.1 B5.
- 6.1 Compose: Kafka in, Logstash out of the flow.
- 6.2 Helm `kafka:` block and `values.schema.json`.
- 6.3 In-chart ClickHouse becomes single-node, with Kafka settings from the secret.
- 6.4 Gateway rollout strategy, probes, `preStop`. `CLUSTER_NAME` guard.
- 6.5 Release workflow, Prometheus, Stack Health.
- 6.6 `scripts/ci.sh chart` in both CIs.

**Step 7 — Tests.** Read §8.3.
- 7.1 Integration/resilience/challenges off Logstash.
- 7.2 Latency regression job (≤ 2 ms) in `scripts/ci.sh` and both CIs.

**Step 8 — Cleanup B, docs, release prep.** Read §10.1 B1–B6, §13.
- 8.1 B1 · 8.2 B2 · 8.3 B3 · 8.4 B4 (confirm it was done in step 3) · 8.5 B5 (confirm it
  was done in step 6) · 8.6 B6.
- 8.7 Version `3.0.0` in `pyproject.toml`, `Chart.yaml`, and the image tags in
  `values.yaml` and `docker-compose.yml`. Write the `CHANGELOG.md` entry.
- 8.8 **Keep** `docs/REDESIGN.md`, `docs/v3-agent-prompts/` and `V3_PROGRESS.md`.
- 8.9 Write the final report and the human checklist:
  - real Kafka/SCRAM check;
  - on-prem ClickHouse Kafka credentials;
  - review;
  - canary per §8.3;
  - tag `v3.0.0`;
  - delete the temporary files.
