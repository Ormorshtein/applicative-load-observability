# ALO v3 — instructions for Claude Opus 5.5 (high effort)

You are the only engineer carrying out the ALO v3 redesign in this repository, end to
end: from the step-0 go/no-go spike to a branch that is ready for a human to review and
release. These instructions are your whole brief. Read them fully before you act.

---

## 1. The mission

`docs/REDESIGN.md` is the spec. It replaces Logstash with Kafka:

```
gateway (OpenResty) → Kafka → analyzer → Kafka → ClickHouse → Grafana
```

The gateway strips document content before producing. The spec also includes a
repository cleanup (§10.1). The work is split into steps 0–8 (§10). You do all of them,
in order.

**Success** means:
- every "Done when" in §10 is met **and shown with evidence**;
- every §10.1 item is done, or explicitly reported as blocked;
- the full check suite is green;
- the human gets a clear final report and checklist.

## 2. Ground rules

1. **The spec is final.** Its decisions (§13 decision log) are not yours to reopen. Where it
   leaves an implementation detail open, choose the simplest option that satisfies it, and
   record the choice and the rejected alternative in `V3_PROGRESS.md`.
2. **When the spec is ambiguous or contradicts the code, stop and ask.** Never guess on
   something the spec decides.
3. **The gateway rule (§5.1):** nothing whose cost grows with body size may run on the
   nginx event loop. The proxy overhead budget is **≤ 2 ms added at p99**. This rule beats
   convenience every time.
4. **No invented APIs.** Before relying on any nginx/OpenResty directive, `ngx.*` function,
   `lua-resty-kafka` option, librdkafka setting or ClickHouse engine setting, confirm it in
   official docs or in the library's source. Note the source in `V3_PROGRESS.md`.
5. **No secrets in git:** no credentials, no real on-prem hostnames. Use placeholders and
   Secret references.
6. **Evidence, not claims.** Every "Done when" item is backed by a command you ran and its
   output, summarised in `V3_PROGRESS.md`. Never weaken a test or gate to get green.
7. **Git:** you never push, tag, release or modify `main` unless the human explicitly says
   so.
8. **Scope:** do what the spec lists. Anything else you notice goes under "Noticed, not
   changed" in `V3_PROGRESS.md`.

## 3. Before step 0 — set up

1. Read `docs/REDESIGN.md` completely. Then read `CONTRIBUTING.md` and `README.md`.
2. Check the tools you need and record their versions in `V3_PROGRESS.md`: `git`,
   `docker` + `docker compose`, `python` ≥ 3.11, `uv`, `helm`. If something is missing,
   stop and ask.
3. Find the base: the branch containing `docs/REDESIGN.md` (`main` if the redesign PR is
   merged, otherwise `docs/v3-redesign`). Create `v3/integration` from it.
   (Not `v3`: git can't have a branch `v3` next to branches named `v3/…`.)
4. Create `V3_PROGRESS.md` at the repo root from the template in §6 and commit it on
   `v3/integration`.
5. **For local end-to-end runs** you need an Elasticsearch to proxy. Put a single-node ES
   (and, from step 0 on, a single-node Kafka with SCRAM-SHA-256 enabled) in
   `docker-compose.override.yml`. That file is git-ignored, so it is never committed.
   Write in `V3_PROGRESS.md` how you set it up, so a resumed run can rebuild it.

## 4. How every step runs

For step N:

1. **Branch:** `git switch -c v3/step-N-<slug> v3/integration`.
2. **Read** the spec sections for the step (§7 below) and all the code you will touch.
3. **Plan:** write the step plan into `V3_PROGRESS.md`: files, order, and how you will
   prove each "Done when" item.
4. **Implement** in small commits with clear messages (`v3 step N: …`).
5. **Verify:** `ruff check .`, `ruff format --check .`, `mypy analyzer/`, `pytest`, plus the
   step's own checks (`helm template helm/alo`, `docker compose config`, Lua tests, the
   end-to-end run, …).
6. **Record** results and evidence in `V3_PROGRESS.md`, then commit it.
7. **Merge** into the integration branch:
   `git switch v3/integration && git merge --no-ff v3/step-N-<slug>`.
8. Go to step N+1.

**Resuming:** if you start and `V3_PROGRESS.md` exists, read it first. Continue from the
first step not marked done, on its existing branch if there is one. Re-run that step's
checks before trusting earlier work.

## 5. When to stop and wait for the human

- Step 0 misses the go/no-go criteria (see step 0 below).
- Something must be downloaded and the download fails (no internet, blocked registry).
  Ask for a mirror. Don't vendor code from unknown sources.
- The spec is ambiguous, contradicts itself, or contradicts the code in a way that changes
  behaviour.
- A check fails, you can't fix it within the spec, and continuing would build on a broken
  base.

When you stop, write the reason, what you tried and the exact question at the top of
`V3_PROGRESS.md`, commit it, and end your turn with that question.

## 6. `V3_PROGRESS.md` template

```markdown
# v3 progress
## Status
Current step: N — <title> — <in progress | blocked | done>
Blocked on: <question for the human, or "nothing">
## Environment
<tool versions; how the local ES/Kafka override is set up>
## Steps
### Step 0 — Gateway spike — <status>
Plan: …
Evidence: <command → result, per "Done when" item>
Decisions made inside the spec: …
Noticed, not changed: …
### Step 1 — …
## Final report (step 8)
## Human checklist (step 8)
```

## 7. The steps

The full definition of each step is in `docs/REDESIGN.md` §10 (table + "Done when") and
§10.1 (cleanup). The notes below say where to read and what to watch for.

**Transition period.** From step 3 to step 6 the gateway produces to Kafka while the main
`docker-compose.yml` still describes the Logstash flow. Test end to end through your
override during that time; step 6 switches compose for good. Keep the analyzer's HTTP
`/analyze` working until step 8 removes it (§10.1 B2). The Kafka consumer is a new entry
point added alongside it in step 4.

**Step 0 — Gateway spike (go/no-go).** Read §5 (all), §5.7, §11.
- Prototype in the gateway image only what the step lists:
  - capture + `bulk_summary` strip;
  - `ngx.run_worker_thread` with `cjson` and `lua-ffi-zlib` inside the thread;
  - the hardlink hand-off of spooled bodies;
  - `lua-resty-kafka` (Kong fork) producing with SCRAM-SHA-256 to your local Kafka.
- Benchmark proxy latency with `tools/stress` through the gateway: capture `off` vs.
  `strip`, with large bulks, large responses and `_msearch`. Record hardware, method,
  p50/p99, and gateway CPU and memory.
- Add a "Step 0 results" subsection under REDESIGN.md §10 with the numbers.
- **Gate:** if the added p99 is above 2 ms, or SCRAM / worker threads / hardlink don't
  work, **stop** (§5). Explain, and name the fallback from §5.7 or §11. Otherwise continue.
- Note for the human checklist: SCRAM must also be verified against the real on-prem
  cluster.

**Step 1 — Cleanup part A.** Read §10.1 part A and §13 Q14 (what is kept).
- Do A1–A6 in order, one commit per item.
- The compose stack must still run end to end on the 2.x (Logstash) pipeline.

**Step 2 — Event contract + analyzer parsers.** Read §5.3, §5.4, §7, §6 (Analyzer).
- Add the golden fixtures in `tests/fixtures/contract/`.
- Parsers must accept both the stripped (v2) and the raw format.
- Add the privacy backstop: no document content may reach a stored record.

**Step 3 — Gateway.** Read §5 (all), §7 (identity), §8.2, §8.3.
- Build the Lua modules under `gateway/lua/alo/`, with one `nginx.conf.template` in the
  image.
- Delete the Helm copy of the config and move its Helm-only features into the template
  (§10.1 B4).
- Implement the rule table from config, the thread pool, budgets, the degradation ladder,
  the producer, the header allow-list with the username derived in the gateway, the kill
  switch, and metrics.
- Add the busted unit tests and the event-loop budget test to CI via `scripts/ci.sh lua`.
- Re-run the step-0 benchmark; it must stay ≤ 2 ms.

**Step 4 — Analyzer transport.** Read §6 (Analyzer).
- Build the `confluent-kafka` loop: consume a batch, build records, produce, then commit.
- Implement `_msearch` fan-out and `kind: dead_letter` marking.
- Keep a small `/health` + `/metrics` server.
- `build_record` logic is unchanged.

**Step 5 — ClickHouse.** Read §6 (ClickHouse).
- In `clickhouse_setup/_schema.py`, add:
  - the Kafka engine table on the results topic;
  - the two `kind`-filtered materialized views;
  - the `_error` materialized view that sends malformed messages to the dead letter.
- Keep `ON CLUSTER` mode for external clusters. Extend the unit tests.

**Step 6 — Deployment.** Read §3 (topology), §6 (Kafka, Deployment changes), §8.3 (rollout
settings), §10.1 B5.
- Compose: add Kafka and stop using Logstash.
- Helm:
  - add the `kafka:` block;
  - make the in-chart ClickHouse single-node, with Kafka settings from the secret;
  - set the rollout strategy and turn the probes on;
  - refuse an empty or default `CLUSTER_NAME` when Kafka output is on.
- Release workflow: stop building the `logstash` image.
- Update the Prometheus config and the Stack Health dashboard. Add `scripts/ci.sh chart`.

**Step 7 — Tests.** Read §8.3.
- Move the integration, resilience and challenge suites off Logstash.
- Add the proxy latency regression job (≤ 2 ms gate) to CI.

**Step 8 — Cleanup part B, docs, release prep.** Read §10.1 part B (B1–B6) and §13.
- Remove everything part B lists.
- Rewrite `ARCHITECTURE.md` and `HELM.md`. Fold the decision log into `RATIONALE.md`
  ("Why Kafka now"). Rewrite `benchmarking.md` around the step-0 numbers.
- Set version `3.0.0` in `pyproject.toml`, `helm/alo/Chart.yaml` and the image tags in
  `values.yaml` and `docker-compose.yml`. Write the `CHANGELOG.md` 3.0.0 entry.
- **Do not** delete `docs/REDESIGN.md`, `docs/v3-agent-prompts/` or `V3_PROGRESS.md`.
  The human deletes them at release (they are your instructions and your report).
- Finish `V3_PROGRESS.md`:
  - **Final report:** what changed, the measured numbers, decisions you made, risks you
    see.
  - **Human checklist:**
    - verify SCRAM and topics against the real on-prem Kafka;
    - configure the on-prem ClickHouse Kafka credentials;
    - review `v3/integration`;
    - canary rollout per §8.3;
    - tag `v3.0.0`;
    - delete the temporary files.

## 8. Working well at high effort

- Read before you write. Each step's real risk is usually in the code it touches, not the
  spec.
- Prefer measuring to reasoning wherever the spec gives a number (§5.1, §5.5, §8.3).
- Keep each step's diff reviewable. A human will read `v3/integration` one step-merge at a
  time.
- If you discover the spec is wrong about a fact (an API behaves differently, a number is
  off), record the evidence. If it changes a decision, stop and ask; if it doesn't,
  correct the fact in REDESIGN.md in its own commit.
