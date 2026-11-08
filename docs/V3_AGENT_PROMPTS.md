# v3 — Prompts for coding agents

Copy-paste prompts for starting the v3 work described in [REDESIGN.md](REDESIGN.md) with
different models. Every prompt points the agent at the **shared rules** below, so the
rules live in one place.

> This file is temporary, like REDESIGN.md: delete it once v3 ships (REDESIGN.md §10.1, B6).

---

## How to use this file

1. Pick a step from REDESIGN.md §10 and a model from the table below.
2. Copy that model's prompt and fill in the `{…}` placeholders.
3. Run **one step (or one part of a step) per agent session, on its own branch**, and
   review the PR before starting anything that depends on it.

### Which model for which step

| Step | What | Depends on | Recommended | Also fine |
|---|---|---|---|---|
| 0 | Gateway spike (go/no-go) | — | Opus 5.5 high | — |
| 1 | Repo cleanup, part A | — (can run alongside step 0) | Sonnet 5.5 high | Sonnet 5.5 medium, Kimi 2.7, GLM 5.4 — one sub-part (A1…A6) per session |
| 2 | Event contract + analyzer parsers | 0 | Opus 5.5 medium | Sonnet 5.5 high |
| 3 | Gateway (Lua modules, thread pool, producer) | 0, 2 | Opus 5.5 high | — |
| 4 | Analyzer Kafka transport | 2 | Opus 5.5 medium | Sonnet 5.5 high |
| 5 | ClickHouse Kafka engine + views | 4 | Sonnet 5.5 high | Opus 5.5 medium |
| 6 | Deployment (compose, Helm, release, dashboards) | 3, 4, 5 | Sonnet 5.5 high | Opus 5.5 medium |
| 7 | Tests (integration, resilience, latency gate) | 6 | Sonnet 5.5 medium | Kimi 2.7, GLM 5.4 |
| 8 | Cleanup part B + docs + release prep | 7 | Opus 5.5 medium | Sonnet 5.5 high (one sub-part B1…B6 per session) |

Why this split:
- **Steps 0 and 3** decide whether the proxy stays fast. They need judgment, measurement
  and the most care, so they go to the strongest setting.
- **Steps 1, 5, 6 and 7** are mostly following a precise checklist.
- **Kimi and GLM** get the most tightly scoped work, each step or sub-part checked against
  an explicit list.

---

## Shared rules (every agent must follow these)

**Source of truth**
1. `docs/REDESIGN.md` is the spec. Read §1–§4, the section for your step, §10, and the
   decision log (§13) before changing anything.
2. The decisions there are final. Don't reopen them, don't "improve" the architecture, and
   don't add scope. If the spec and the code disagree, or the spec is ambiguous, **stop and
   write the question down** (see "When to stop") instead of guessing.

**Git**
3. Branch from the branch that contains `docs/REDESIGN.md` (`main` once the redesign PR is
   merged; `docs/v3-redesign` until then). Name it `v3/step-{N}-{short-slug}`.
4. Commit in small, reviewable commits. **Don't push, tag, release, or touch `main`**
   unless the human running you says so.
5. Never commit secrets: no Kafka or ClickHouse credentials, no real hostnames from
   on-prem environments. Use placeholders and Kubernetes Secret references.

**Code**
6. Follow `CONTRIBUTING.md`. Python: `ruff check .`, `ruff format --check .`,
   `mypy analyzer/`, `pytest` must all pass. Install with `uv pip install -e ".[dev]"`.
7. **Gateway rule (REDESIGN.md §5.1):** nothing proportional to body size may run on the
   nginx event loop. If you are about to add such work, stop.
8. Don't invent APIs. Before using any OpenResty/nginx directive, `ngx.*` function,
   `lua-resty-kafka` option, librdkafka setting or ClickHouse engine setting, confirm it
   in that project's documentation or source, and cite where in your PR notes.
9. Change only what your step lists. If you notice something else that's wrong, add it
   to the PR notes under "Noticed, not changed".

**Verification**
10. Every item in your step's "Done when" (REDESIGN.md §10) must be shown, not claimed:
    paste the command and its relevant output into the PR notes.
11. If a check fails and you can't fix it within your step's scope, report it as failing.
    Never weaken a test or a CI gate to make it pass.

**When to stop**
12. Stop and report (don't guess) when:
    - the spec is ambiguous or contradicts the code;
    - the step needs something you don't have (e.g. access to the real Kafka cluster);
    - a measurement misses its threshold (e.g. step 0 adds more than 2 ms at p99).

**What to hand back** — a file `PR_NOTES.md` at the repo root (not committed), with:
```
## Step {N}: {title}
### Done
- … (each "Done when" item, with the command + output that proves it)
### Not done / blocked
- …
### Decisions I had to make inside the spec's boundaries
- … (what, why, alternatives)
### Noticed, not changed
- …
### Sources checked (for any external API used)
- …
```

---

## Claude Opus 5.5 — high effort

Best for steps 0 and 3. Runs a whole step on its own and makes small decisions within the
spec.

```text
You are implementing step {N} ("{STEP TITLE}") of the ALO v3 redesign in this repository.

Start by reading docs/V3_AGENT_PROMPTS.md, section "Shared rules", and follow every rule
in it. Then read docs/REDESIGN.md: §1–§4, the section(s) for step {N}, §10 (work plan and
"Done when"), and §13 (decision log). The spec's decisions are final; your job is to
implement them, not to redesign them.

Scope: everything step {N} lists in §10 (and §10.1 if it is a cleanup step) — nothing
more.

How to work:
- Before writing code, read the existing code this step touches and write a short plan
  (files to change, order, how you will verify each "Done when" item) at the top of
  PR_NOTES.md. Then execute it.
- Where the spec leaves an implementation detail open, choose the simplest option that
  satisfies it, and record the choice and the alternative you rejected in PR_NOTES.md.
- Verify every "Done when" item by running something, and paste the evidence.
- {STEP-SPECIFIC NOTE — for step 0: "This is a go/no-go spike. Prototype only what
  §10 step 0 lists. Measure proxy p50/p99 through the gateway with capture off vs. strip,
  using tools/stress against the docker-compose stack with a local Kafka configured for
  SCRAM-SHA-256. Record the numbers, hardware and method. If the added p99 exceeds 2 ms,
  or SCRAM/ngx.run_worker_thread/hardlink hand-off doesn't work, say so plainly and
  propose the fallback from §5.7/§11 — do not paper over it."}
- {For step 3: "The event-loop budget test and the latency gate from §8.3 are part of
  this step and must pass."}

Stop and report instead of guessing when anything in "When to stop" applies.
Finish with PR_NOTES.md filled in, all checks green (or failures reported honestly), and
commits on branch v3/step-{N}-{slug}. Do not push.
```

---

## Claude Opus 5.5 — medium effort

Best for steps 2, 4 and 8. A whole, well-specified step, with less exploration.

```text
Implement step {N} ("{STEP TITLE}") of the ALO v3 redesign.

1. Read docs/V3_AGENT_PROMPTS.md → "Shared rules" and follow them.
2. Read docs/REDESIGN.md: §1–§4, §{SECTION(S) FOR THIS STEP}, §10 (step {N} row and its
   "Done when"), §13. Decisions there are final.
3. Read the existing code you will change before editing it.
4. Implement exactly what step {N} lists. When the spec leaves a detail open, take the
   simplest option and note it in PR_NOTES.md.
5. Run ruff, mypy and pytest, plus any step-specific check listed in "Done when". Paste
   the results into PR_NOTES.md.
6. Commit on branch v3/step-{N}-{slug}. Do not push.

Stop and report if the spec is ambiguous, contradicts the code, or a check fails that you
can't fix within this step.
```

---

## Claude Sonnet 5.5 — high effort

Best for steps 1, 5 and 6. Follows the checklist in the spec item by item.

```text
You are doing step {N} ("{STEP TITLE}") of the ALO v3 redesign. It is a checklist step:
the spec already says exactly what to change.

Before anything else:
- Read docs/V3_AGENT_PROMPTS.md → "Shared rules". Follow every rule.
- Read docs/REDESIGN.md §10 (step {N} row) and the detailed list for it:
  {§10.1 part A | §10.1 part B | §6 | …}. Also read §13 so you know which decisions are
  already made (for example, what is deliberately kept).

Then work through the list item by item, in order:
- For each item: read the files it names, make the change, run the checks that apply
  (ruff, mypy, pytest; `helm template helm/alo` for chart changes; `docker compose config`
  for compose changes), and commit with a message naming the item (e.g. "v3 step 1 A1:
  single committed copy of dashboard JSON").
- Do only what the item says. Line numbers in the spec are approximate; find the right
  spot by its content.
- If an item can't be done as written (the file is gone, the code is different, or it
  would break something not mentioned), skip it, and record why in PR_NOTES.md under
  "Not done / blocked".

At the end, run the full check suite once more, fill in PR_NOTES.md with the evidence for
each item, and leave the commits on branch v3/step-{N}-{slug}. Do not push.
```

---

## Claude Sonnet 5.5 — medium effort

Best for **one sub-part** of a checklist step (e.g. step 1 A4 only), or step 7.

```text
Do one bounded task from the ALO v3 plan: step {N}, item(s) {ITEM IDS, e.g. "A4"}.

Rules: read docs/V3_AGENT_PROMPTS.md → "Shared rules" and follow them.
Spec: docs/REDESIGN.md → {§10.1 part A, item A4 | …}. That list is your whole scope.

Steps:
1. Read the spec item(s) and every file they mention.
2. Make exactly those changes, nothing else.
3. Run: ruff check . && ruff format --check . && mypy analyzer/ && pytest
   (plus `helm template helm/alo` if you touched the chart).
4. Commit on branch v3/step-{N}-{slug} with a message naming the item.
5. Write PR_NOTES.md (format in the shared rules), including the command output.

If something in the spec doesn't match the code, stop and write it in PR_NOTES.md instead
of guessing. Do not push.
```

---

## Kimi 2.7

For one sub-part of steps 1 or 7. The prompt spells everything out and assumes nothing
about the tool it runs in.

```text
ROLE: You are a careful software engineer making ONE small, well-defined change to an
existing repository. Follow the instructions exactly. Do not expand the scope.

TASK: ALO v3 plan, step {N}, item(s) {ITEM IDS}.

READ FIRST, IN THIS ORDER (do not edit anything before reading all of them):
1. docs/V3_AGENT_PROMPTS.md — section "Shared rules". These rules are mandatory.
2. docs/REDESIGN.md — section {§10.1 part A, item X | …}. This is the complete list of
   what to change.
3. docs/REDESIGN.md — §13 "Decision log", Q14 (what is kept vs deleted).
4. Every file named in the item(s) above.

DO:
- Make only the changes the item(s) list. Line numbers in the spec are approximate;
  locate code by its content.
- After the change, run these commands and keep their full output:
    uv pip install -e ".[dev]"
    ruff check .
    ruff format --check .
    mypy analyzer/
    pytest
  If you changed anything under helm/: also run `helm template helm/alo`.
- Commit on a new branch named v3/step-{N}-{slug}. One commit per item.

DO NOT:
- Do not change files the item does not mention (except imports/paths that break
  because of your change — list each one in PR_NOTES.md).
- Do not rename, reformat or "clean up" anything else.
- Do not add dependencies.
- Do not push, tag or merge.
- Do not guess. If the spec and the code disagree, stop and write the mismatch in
  PR_NOTES.md.

OUTPUT: PR_NOTES.md at the repository root, in the exact format given in the shared
rules, with the command outputs pasted in.
```

---

## GLM 5.4

Same scope as Kimi: one sub-part of steps 1 or 7. Every step must be confirmed before
moving to the next.

```text
You will make ONE scoped change in this repository, following a written spec. Accuracy
matters more than speed. Do not do anything the spec does not ask for.

Task: ALO v3, step {N}, item(s) {ITEM IDS}.

Step 1 — Read (no edits yet):
  a) docs/V3_AGENT_PROMPTS.md, section "Shared rules" (mandatory rules).
  b) docs/REDESIGN.md, section {§10.1 part A, item X | …} (your complete scope).
  c) docs/REDESIGN.md §13, Q14 (things that must be kept).
  d) Every file the item names.
  Then write a numbered list of the exact edits you will make (file + what changes) at
  the top of PR_NOTES.md. Every edit must trace to a line in the spec.

Step 2 — Edit:
  Make the edits from your list, one at a time. After each edit, re-read the changed file
  to confirm the change is correct and complete.

Step 3 — Verify. Run, in order, and save the output:
  uv pip install -e ".[dev]"
  ruff check .
  ruff format --check .
  mypy analyzer/
  pytest
  helm template helm/alo        (only if you changed files under helm/)
  If a command fails because of your change, fix it. If it fails for another reason,
  do not fix it — record it.

Step 4 — Commit on a new branch v3/step-{N}-{slug}, one commit per item. Do not push.

Step 5 — Finish PR_NOTES.md using the format in the shared rules. Include the command
  outputs.

Hard limits: no edits outside the spec item; no new dependencies; no renames or
reformatting beyond the item; no guessing — if the spec and the code disagree, stop and
write the mismatch down.
```

---

## Filled-in example

Step 1, item A1, with Sonnet 5.5 medium:

```text
Do one bounded task from the ALO v3 plan: step 1, item(s) A1.

Rules: read docs/V3_AGENT_PROMPTS.md → "Shared rules" and follow them.
Spec: docs/REDESIGN.md → §10.1 part A, item A1 ("Dashboards: one committed copy, one
delivery path per Grafana type"). That list is your whole scope.
...
Commit on branch v3/step-1-dashboards-single-copy …
```
