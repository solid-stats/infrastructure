---
context: phase
phase: 21-restore-cutover-recovery
task: 0
total_tasks: 0
status: paused
last_updated: 2026-08-20T09:45:30.734Z
---

# BLOCKING CONSTRAINTS — Read Before Anything Else

> Acknowledge this constraint before resuming Phase 21.

- [ ] `phase.complete` skipped Phase 21 and corrupted the plan count after Phase
  20. Confirm that `STATE.md` names Phase 21, `ROADMAP.md` keeps the numeric
  dependency order, and no Phase 22 work starts first.

## Critical Anti-Patterns

<!-- markdownlint-disable MD013 -->
| Pattern | Description | Severity | Prevention Mechanism |
| --- | --- | --- | --- |
| Trusting automatic phase transition blindly | The Phase 20 completion command advanced STATE directly to Phase 22 and produced an impossible `23/15` count. | blocking | Before planning, read STATE and ROADMAP together and run `roadmap.analyze`; Phase 21 must remain next. |
| Exact ANN ranking across engines | Chroma and Qdrant returned stable but slightly different HNSW candidate sets despite exact field, ID, and vector parity. | advisory | Use the committed ANN-equivalence contract and report; do not silently restore the rejected exact ordered-ID assumption. |
<!-- markdownlint-enable MD013 -->

<current_state>

Phase 20 is complete and verified at 5/5 must-haves. MIG-01 and MIG-02 are
complete. Phase 21 is the next phase, but it has no directory, context, or plans.
Work is paused before any Phase 21 discussion or live restore activity.

</current_state>

<completed_work>

- Froze and inventoried the immutable legacy source through the exact v3.5.0
  oracle.
- Approved a lossless mapping contract and transformed 19,534 eligible records.
- Reconciled 21 approved exclusions without deleting their source data.
- Proved exact field, ID, metadata, timestamp, and vector parity.
- Proved strict cross-engine ANN recall equivalence and produced the committed
  parity report plus Phase 21 handoff.
- Removed the disposable Qdrant collection, container, and data directory after
  the pass-only cleanup gate.
- Revalidated retained snapshot, source, and bundle provenance after cleanup.
- Committed and pushed Phase 20 completion at `e469b9b`.

</completed_work>

<remaining_work>

- Phase 20: nothing remains.
- Phase 21: discuss requirements, plan the isolated restore, define reversible
  cutover and recovery gates, then execute only after those plans pass review.
- Phase 22: remains blocked on Phase 21.

</remaining_work>

<decisions_made>

- Preventing data loss outranks avoiding duplicate representations. Approved
  exclusions remain retained outside the target import.
- Cross-engine recall uses equal result lengths, exact top-1, at least 80%
  per-fixture overlap, exact relative order for common IDs, and bounded common
  distances. Exact data parity remains zero-tolerance.
- Phase 21 must recompute provenance and handoff bindings before any restore or
  cutover. It must not depend on the deleted disposable Qdrant target.
- The user requested a hard pause after Phase 20. Do not start Phase 21 until a
  later explicit resume.

</decisions_made>

<!-- markdownlint-disable MD033 -->
<blockers>

None. The pause is intentional.

</blockers>
<!-- markdownlint-enable MD033 -->

## Required Reading (in order)

1. `AGENTS.md` — repository rules, security boundary, and GSD workflow.
1. `.planning/STATE.md` — authoritative paused position.
1. `.planning/ROADMAP.md` — Phase 21 goal, dependencies, and requirements.
1. `.planning/phases/20-local-corpus-migration/20-VERIFICATION.md` — verified
   Phase 20 outcome and ANN deviation.
1. `.planning/phases/20-local-corpus-migration/20-PHASE21-HANDOFF.json` —
   machine-readable provenance contract for Phase 21.
1. `.planning/phases/20-local-corpus-migration/20-PARITY-REPORT.json` — passing
   public parity evidence.
1. `.planning/phases/20-local-corpus-migration/20-MAPPING-CONTRACT.json` —
   approved preservation and routing decisions.
1. `.planning/phases/20-local-corpus-migration/20-06-SUMMARY.md` — final local
   parity execution and cleanup summary.
1. `.planning/REQUIREMENTS.md` — ISO-01, ISO-03, OPS-02, OPS-03, and OPS-05 for
   Phase 21.

## Infrastructure State

- Legacy SolidStats writes remain frozen; the immutable source evidence is
  retained locally.
- The disposable local Qdrant target no longer exists.
- The provenance-bound snapshot, source quartet, transform bundle, parity
  report, and Phase 21 handoff are retained.
- Private corpus paths and values are intentionally absent from repository
  artifacts. Rediscover them privately and verify their digests before use.
- No workflow-owned server, watcher, container, or async external job remains
  running.

<!-- markdownlint-disable MD033 -->
<context>

Phase 20 succeeded after several fail-closed corrections to the exact v3.5.0
oracle protocol and the cross-engine recall contract. Do not weaken the exact
data-preservation gates. Phase 21 should consume the committed handoff, prove an
isolated restore first, and keep live cutover operator-gated and reversible.

The placeholder matches in older Phase 19 summaries describe intentional
fail-closed operator placeholders; they are not unfinished summary content.

</context>
<!-- markdownlint-enable MD033 -->

<next_action>

Start with: run `$gsd-resume-work`, verify that STATE and ROADMAP still point to
Phase 21, then run `$gsd-discuss-phase 21`.

</next_action>
