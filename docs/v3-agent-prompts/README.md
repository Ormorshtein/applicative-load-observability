# v3 agent prompts

One coding agent carries out the **entire** v3 change described in
[../REDESIGN.md](../REDESIGN.md), from the step-0 spike to a release-ready branch. Each
file in this folder is a complete set of instructions for one model, written to suit how
that model works best.

## Which file to give the agent

| Model the agent runs on | File |
|---|---|
| Claude Opus 5.5, high effort | [claude-opus-5.5-high.md](claude-opus-5.5-high.md) |
| Claude Opus 5.5, medium effort | [claude-opus-5.5-medium.md](claude-opus-5.5-medium.md) |
| Claude Sonnet 5.5, high effort | [claude-sonnet-5.5-high.md](claude-sonnet-5.5-high.md) |
| Claude Sonnet 5.5, medium effort | [claude-sonnet-5.5-medium.md](claude-sonnet-5.5-medium.md) |
| Kimi 2.7 | [kimi-2.7.md](kimi-2.7.md) |
| GLM 5.4 | [glm-5.4.md](glm-5.4.md) |

If the model isn't listed, use the file for the closest model. When in doubt, use the more
explicit one: GLM 5.4, then Sonnet medium.

## How to start it

Give the agent exactly this, with the file name filled in:

```text
Read docs/v3-agent-prompts/<file>.md and follow it from start to finish.
```

The same sentence also **resumes** an interrupted run. Every file tells the agent to read
`V3_PROGRESS.md` first and continue from where it stopped.

## What the human still owns

The agent never pushes, tags or releases unless you tell it to. It stops and waits for you
when:
- step 0 misses its go/no-go threshold (≤ 2 ms added p99 at the gateway);
- it needs something it can't get (a dependency mirror, a tool, access);
- the spec is ambiguous or contradicts the code.

At the end it leaves you a checklist in `V3_PROGRESS.md`: verify against the real on-prem
Kafka and ClickHouse, review, canary rollout, tag `v3.0.0`, and delete the temporary files
(`docs/REDESIGN.md`, this folder, `V3_PROGRESS.md`).
