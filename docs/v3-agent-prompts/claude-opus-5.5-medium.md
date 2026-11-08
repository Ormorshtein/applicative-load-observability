# ALO v3 — instructions for Claude Opus 5.5 (medium effort)

You will carry out the entire ALO v3 redesign in this repository by yourself, step by
step, from the step-0 spike to a branch ready for human review and release. Follow these
instructions in order.

---

## 1. What you are building

- **The spec:** `docs/REDESIGN.md`. Logstash is replaced by Kafka:
  `gateway → Kafka → analyzer → Kafka → ClickHouse`. The gateway strips document content
  before producing.
- **The work:** steps 0–8, defined in §10 (table + "Done when") and §10.1 (repo cleanup).
- **Done** means:
  - every "Done when" item is met, with command output as evidence;
  - every §10.1 item is done or reported as blocked;
  - all checks are green;
  - `V3_PROGRESS.md` holds a final report and a checklist for the human.

## 2. Rules

1. The spec's decisions are final (§13). For details it leaves open, pick the **simplest**
   option that satisfies it and note the choice in `V3_PROGRESS.md`.
2. If the spec is ambiguous or contradicts the code, **stop and ask** (§5). Don't guess.
3. **Gateway rule (§5.1):** no work proportional to body size on the nginx event loop.
   The proxy may add at most **2 ms at p99**.
4. Don't invent APIs. Check every nginx/OpenResty, `lua-resty-kafka`, librdkafka and
   ClickHouse setting you use against its docs or source. Note the source.
5. No secrets or real on-prem hostnames in git.
6. Show evidence for every "Done when" item. Never weaken a test or gate.
7. Never push, tag, release or touch `main` unless the human says so.
8. Only change what the spec lists. Write other findings under "Noticed, not changed".

## 3. Setup (once)

1. Read `docs/REDESIGN.md` in full, then `CONTRIBUTING.md`.
2. Check that `git`, `docker compose`, `python` ≥ 3.11, `uv` and `helm` are available, and
   record their versions. If any is missing, stop and ask.
3. Create `v3/integration` from the branch containing `docs/REDESIGN.md` (`main` if merged,
   else `docs/v3-redesign`). Don't name it `v3`: that clashes with the `v3/…` branches.
4. Create `V3_PROGRESS.md` at the repo root (template in §6) and commit it.
5. For local end-to-end tests, put a single-node Elasticsearch, and from step 0 a
   single-node Kafka with SCRAM-SHA-256, in `docker-compose.override.yml`. It is
   git-ignored. Note how you set it up in `V3_PROGRESS.md`.

## 4. The loop for each step N

1. `git switch -c v3/step-N-<slug> v3/integration`
2. Read the spec sections listed for the step (§7) and the files you'll change.
3. Write a short plan in `V3_PROGRESS.md`: files, and how you'll prove each "Done when".
4. Implement in small commits (`v3 step N: …`).
5. Run `ruff check .`, `ruff format --check .`, `mypy analyzer/` and `pytest`, plus the
   step's own checks.
6. Record evidence in `V3_PROGRESS.md` and commit.
7. `git switch v3/integration && git merge --no-ff v3/step-N-<slug>`

**Resuming:** if `V3_PROGRESS.md` already exists, read it first. Continue from the first
step not marked done, and re-run that step's checks before building on it.

## 5. Stop and wait for the human when

- step 0 fails its gate;
- a download fails (ask for a mirror; don't vendor code from unknown places);
- the spec is ambiguous or contradicts the code;
- a check fails and can't be fixed within the spec.

Write the question at the top of `V3_PROGRESS.md`, commit, and end your turn with it.

## 6. `V3_PROGRESS.md` template

```markdown
# v3 progress
## Status
Current step: N — <title> — <in progress | blocked | done>
Blocked on: <question, or "nothing">
## Environment
<tool versions; local ES/Kafka override setup>
## Steps
### Step N — <title> — <status>
Plan: …
Evidence: <command → result for each "Done when" item>
Decisions made inside the spec: …
Noticed, not changed: …
## Final report
## Human checklist
```

## 7. Steps — where to read, what to watch

**Transition period.** From step 3 to step 6 the gateway produces to Kafka while the main
compose file still describes the Logstash flow. Test end to end through your override;
step 6 switches compose. The analyzer's HTTP `/analyze` stays until step 8 (§10.1 B2).
The Kafka consumer is a new entry point added in step 4.

| Step | Read | Watch for |
|---|---|---|
| **0** Gateway spike | §5, §5.7, §10 row 0, §11 | Prototype only what's listed: capture + `bulk_summary`, `ngx.run_worker_thread` with `cjson` + `lua-ffi-zlib`, hardlink hand-off, `lua-resty-kafka` (Kong fork) with SCRAM-SHA-256 to local Kafka. Benchmark with `tools/stress`, capture `off` vs `strip`. Write a "Step 0 results" subsection in REDESIGN.md §10. **Gate: added p99 > 2 ms, or any of those mechanisms failing → stop and ask.** |
| **1** Cleanup A | §10.1 part A, §13 Q14 | A1→A6 in order, one commit each. The compose stack must still run on the 2.x pipeline. |
| **2** Contract + parsers | §5.3, §5.4, §7, §6 Analyzer | Golden fixtures in `tests/fixtures/contract/`. Parse both the v2 and the raw format. Privacy backstop. |
| **3** Gateway | §5, §7, §8.2, §8.3, §10.1 B4 | Lua modules under `gateway/lua/alo/`. One `nginx.conf.template`; delete the Helm copy and move its features into the template. busted + event-loop budget tests via `scripts/ci.sh lua`. Re-benchmark: ≤ 2 ms. |
| **4** Analyzer transport | §6 Analyzer | Consume → build → produce → commit. `_msearch` fan-out. `kind: dead_letter`. `/health` + `/metrics`. `build_record` unchanged. |
| **5** ClickHouse | §6 ClickHouse | Kafka engine table, two `kind` views, `_error` view to dead letter. Keep `ON CLUSTER` for external clusters. Unit tests. |
| **6** Deployment | §3, §6, §8.3, §10.1 B5 | Compose: Kafka in, Logstash out of the flow. Helm: `kafka:` block, single-node in-chart ClickHouse, rollout strategy, probes on, refuse empty/default `CLUSTER_NAME`. Release workflow, Prometheus, Stack Health. `scripts/ci.sh chart`. |
| **7** Tests | §8.3 | Integration/resilience/challenges off Logstash. Latency regression job (≤ 2 ms) in CI. |
| **8** Cleanup B + docs | §10.1 B1–B6, §13 | Remove everything part B lists. Rewrite ARCHITECTURE, HELM, RATIONALE ("Why Kafka now"), benchmarking. Version `3.0.0` everywhere plus the CHANGELOG entry. **Keep** `docs/REDESIGN.md`, `docs/v3-agent-prompts/` and `V3_PROGRESS.md`; the human deletes them. Write the final report and human checklist: real Kafka/SCRAM check, on-prem ClickHouse Kafka credentials, review, canary per §8.3, tag `v3.0.0`, delete temp files. |
