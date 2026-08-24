<!-- markdownlint-disable MD013 -->

# SolidStats memory adapter for GSD

## Applicability

Read this file completely only when the current repository contains
`.planning/config.json`. The sibling `MEMORY.md` contract remains authoritative
for scope, ownership, recall, capture, safety, correction, and failure behavior.

## Native capability is deliberately disabled

Every synced SolidStats GSD config must retain this fail-closed native block:

```json
{
  "mempalace": {
    "enabled": false,
    "memory_mode": "augment",
    "wing": "<primary role wing from the manifest>",
    "recall_on_discuss": false,
    "recall_on_plan": false,
    "capture_artifacts": false,
    "mirror_kg": false,
    "cross_project_tunnels": false,
    "diary_journal": false,
    "auto_capture_hooks": false
  }
}
```

`enabled: false` disables only GSD's incompatible generic MemPalace
capability. It does not disable the `solidstats_memory` MCP or this adapter.

Do not run `gsd-mempalace-recall`, `gsd-mempalace-capture`, generic
execute-wave problem capture, or `gsd-mempalace-curator`. Do not create a
`MEMORY-RECALL.md` artifact. The generic handlers use the wrong server
namespace, raw artifact capture, unsupported rooms, KG, diary, and tunnel
semantics.

## Coordinator-owned recall

The main GSD coordinator runs the federated recall from `MEMORY.md` at most
once per top-level GSD task:

- before discussion questions for discuss-oriented entry points;
- before the first specialist for execute, verify, review, ship, quick, fast,
  debug, and any future entry point that has not already recalled;
- before a directly invoked plan only when the current top-level task has no
  provenance-bearing recalled context. Inject the filtered results directly
  into the planner prompt; never create a separate plan-recall artifact.

When discussion already recalled and its verified context is carried into
planning or execution, do not recall again. A resumed or compacted task keeps
the same top-level ownership if the provenance-bearing context is still
available.

Run the initial wing searches in the first tool batch after repository and
contract routing is known. Fold relevant, verified facts into the discussion
and owner-native `CONTEXT.md` when discussion owns that artifact. For other
entry points, pass a compact memory context block directly to the relevant
specialist. Include drawer IDs, owning wings, sources, and staleness caveats.

Subagents and GSD specialists must not recall or capture independently.

## Semantic closure

Wave completion must not write memory. Raw plans, summaries, problem lists,
review reports, and verification files remain in `.planning` only.

Before the first final handoff that closes the top-level GSD task, the main
coordinator runs the `MEMORY.md` durable capture gate. Capture only new verified
semantic conclusions. A routine plan, execution, or passing verification with
no durable conclusion produces no drawer.

A long workflow may safely defer capture until top-level closure because its
verified intermediate state remains in committed GSD artifacts. Do not create
partial memory merely to survive a wave boundary.

Corrections remain in the curator flow. A GSD ship operation must not dispatch
the generic MemPalace curator.

## Failure behavior

If `solidstats_memory` is unavailable, follow the one-retry and primary-evidence
fallback contract in `MEMORY.md`. GSD continues; it must not use a different
palace, generic CLI, flat memory, or local outbox.
