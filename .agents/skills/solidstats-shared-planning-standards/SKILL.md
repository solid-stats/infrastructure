---
name: solidstats-shared-planning-standards
description: >
  Shared planning foundation for every SolidStats repo (server-2, replays-fetcher,
  replay-parser-2, web, infrastructure) — read by the GSD planning agents (gsd-planner,
  gsd-plan-checker, gsd-executor), not triggered for a coding task. Owns
  plan provenance: the `[src: file#anchor]` source-anchor format on every load-bearing premise,
  the premises ledger (claim + src + a one-line verify command the checker runs), and the
  carried-forward-learnings block — so a wrong input assumption can't propagate silently into a
  broken plan. Also owns the knowledge-graph consultation step (GSD-IMPROVEMENTS C6): query the
  project graph at discuss/plan time, fold the blast radius into the plan, and refresh it after
  execution. The planning agents read it via agent_skills injection in each repo's
  .planning/config.json; do NOT trigger it directly for planning — use the GSD planning commands.
  Triggers (meta only): "planning standard", "plan provenance", "premises ledger", "source
  anchors", "carried-forward learnings", "graphify in planning", "стандарт планирования",
  "провенанс плана", "реестр предпосылок", "якоря источников", "граф знаний в планировании".
---

# SolidStats Planning Standards — Shared Foundation

This skill is the single source of truth for **how a SolidStats plan sources and anchors its
inputs** — the parts that must hold no matter which repo or phase is being planned. The GSD
planning commands own *how* a plan is structured (task breakdown, `must_haves`, `<context>`,
verification loop); this skill owns the *provenance*: where each load-bearing claim came from, how
the checker re-verifies it instead of trusting prose, and how the project knowledge graph feeds the
plan before a line of it is written.

It is **not** a standalone planner. The planning agents (`gsd-planner`, `gsd-plan-checker`,
`gsd-executor`) read this first, then layer their own workflow on top. If you
reached this skill directly to write a plan, stop and use the matching GSD planning command —
this defines the standard those commands apply.

**Why this exists.** A `PLAN.md` is already detailed — frontmatter `must_haves`, a `<context>`
block, per-task action/verify/done. What it lacks is **traceability of input premises**. Load-bearing
facts ride along as prose with informal pointers — "per D1", "RESEARCH A", "the running engine is
PostgreSQL 17" — that a checker can't mechanically re-open. A false premise (the classic:
"`rotation_id` is NOT NULL today" when it is already nullable) then propagates silently into a broken
migration. The fix is **provenance, not more detail**: anchor every premise to its source, and give
the checker a command to re-verify it.

---

## A. Source anchors — `[src: …]`

Every load-bearing claim in a task's `<action>` carries a source anchor in the same citation idiom
the reviews already use (`[conv: …]` / `[std: …]`). The anchor names *where the fact lives*, so a
checker — or a future reader — can re-open it instead of taking the prose on faith.

- `[src: file#anchor]` — a repo file and a heading/line anchor. "per D1" →
  `[src: CONTEXT.md#D1]`; "RESEARCH A" → `[src: RESEARCH.md#A-existing-constraints]`; "PostgreSQL 17"
  → `[src: AGENTS.md#Stack-Direction]`; "`rotation_id` is nullable" →
  `[src: 0001_v1_domain_schema.sql#L120]`.
- `[src: graph:<community-or-node>]` — a fact taken from the project knowledge graph (see §D):
  which feature a file belongs to, or what depends on it. `[src: graph:Statistics Repository Core]`.
- `[src: SUMMARY.md#deviations]` — a learning carried forward from a prior phase (see §C).

A claim with **no** anchor is either common knowledge (no anchor needed) or an **unverified
assumption** — and an unverified assumption that the plan leans on is the exact failure mode this
standard exists to catch. When you can't anchor a load-bearing claim, that is the signal to make it
a premise (§B) and verify it, not to write it as settled fact.

---

## B. The premises ledger

A short ledger of the plan's **input assumptions** — distinct from `must_haves.truths`, which are
*post-conditions* (what must be true after the work). Premises are *inputs* (what was already true
when the plan was written, and that the plan relies on). Each entry is three fields:

- `claim:` — the assumption, stated so it can be true or false.
- `src:` — the `[src: …]` anchor where it can be checked.
- `verify:` — a one-line command (a `grep`, a `psql`, a `cargo`/`pnpm` check) that confirms or
  refutes it.

```yaml
premises:
  - claim: rotation_id is already nullable on the four aggregate tables
    src: 0001_v1_domain_schema.sql#L120
    verify: grep -n 'rotation_id' migrations/0001_v1_domain_schema.sql
  - claim: the public OpenAPI contract is frozen at info.version 1.0.0
    src: AGENTS.md#Contract-Freeze
    verify: rg '"version": "1.0.0"' src/openapi/openapi.json
```

The plan-checker **runs each `verify`** instead of trusting the prose — a refuted premise is caught
before execution, not after a migration breaks. The ledger is small by design: only the assumptions
the plan would break on if they were wrong, not every fact in the file.

---

## C. Carried-forward learnings

Learnings already captured in a prior phase's `*-SUMMARY.md#deviations` (and injected via
`learnings.max_inject`) become part of *this* plan's contract rather than background the planner
might or might not have read. Add a short block citing them with `[src: …]` anchors, so a deviation
the last phase paid for is a stated premise this one honors — not a trap it re-discovers.

```yaml
carried_forward:
  - claim: recalc must run as a 2Gi job — the 1Gi app pod OOMs on the full corpus
    src: 03-01-SUMMARY.md#deviations
```

If a carried-forward learning contradicts a fresh premise, that contradiction is itself a finding for
the checker — surface it, don't silently pick one.

---

## D. Consult the knowledge graph before planning (C6)

The project knowledge graph (`graphify`, built into `.planning/graphs/`) is a **map of the code**:
communities (feature clusters), the files in each, and what depends on what. GSD builds it but, on
its own, never consults it — so it sits idle. This standard wires it into planning **through the
skill** (the agent-skills injection lever), which avoids forking gsd-core; the heavier alternative is
to give the `graphify` capability `steps`/`contributions` in its gsd-core descriptor (ADR-857) so it
injects at `discuss:pre`/`plan:pre` like `mempalace` does. Until that lands, this section is the
bridge that makes the graph pull weight.

**Gate.** Only when `.planning/config.json` has `graphify.enabled: true` and `.planning/graphs/`
exists. Otherwise skip — no graph, no step.

**At discuss / plan, before drafting the plan:**

1. **Query the graph for the phase topic** — the files, modules, or symbols the phase will touch.
   Use the `gsd-graphify` skill (`/gsd-graphify query <term>`) or read the named communities in
   `.planning/graphs/GRAPH_COMMUNITIES.md`.
2. **Fold the result into the plan.** Two concrete uses:
   - **`<context>`** — name the community/feature the change lives in and the sibling files in it, so
     the planner places work in the right slice instead of guessing.
   - **Blast radius** — the graph's edges show what *depends on* the files being changed. Every
     dependent is a downstream surface the plan must account for (a consumer to update, a test to
     extend, a contract to keep). Record load-bearing graph facts as premises (§B) with
     `[src: graph:<community>]` anchors so the checker can re-open them.

**After execution, refresh the graph.** Once code changed (`verify:post` / wave-post), refresh the
graph so the next phase queries a current map — run `/gsd-graphify build` (it runs `graphify update .`
then re-snapshots; no LLM, mechanical). Check freshness with `/gsd-graphify status`; a stale graph
misleads the next plan, so a known-stale graph is itself worth a one-line note.

This is the planning half of C6. The review half — mapping a *change* onto the same graph to get its
blast radius at review time — lives in `solidstats-shared-review-standards` (the discovery step).

---

## E. How this is wired

This standard only takes effect when the planning agents actually read it. Wiring is per-repo
config, not a behavior this skill can switch on by itself:

- **Inject it** into the `agent_skills` lists for `gsd-planner`, `gsd-plan-checker`, and
  `gsd-executor` in each repo's `.planning/config.json` — the same mechanism that injects the
  `solidstats-shared-*` standards into the reviewers.
- **Add a plan-checker checklist item:** "every load-bearing premise resolves via `[src:]`;
  spot-verify N." The checker runs the ledger's `verify` commands and reports any refuted premise as
  a finding before execution.
- **Keep it additive.** Provenance is metadata on top of the existing plan format — a plan with no
  anchors still plans; this standard raises the floor, it doesn't gate a plan from existing.

The agent-skills injection and the plan-checker checklist item are consumer-repo changes
(`.planning/config.json`), tracked outside this skills repo. This file defines *what* the standard is;
turning it on is a wiring step per repo.
