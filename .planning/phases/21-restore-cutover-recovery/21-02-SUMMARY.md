---
phase: 21-restore-cutover-recovery
plan: 02
subsystem: memory-backup-restore
tags:
  - qdrant
  - kubernetes
  - backup
  - isolated-restore
  - provenance
requires:
  - phase: 20-local-corpus-migration
    provides: Digest-bound retained corpus handoff and exact parity oracle
  - phase: 21-restore-cutover-recovery
    plan: 01
    provides: Value-free evidence schema and fail-closed transition contracts
provides:
  - Provenance-bound one-shot Qdrant and MemPalace backup package
  - Download-verified immutable object-store backup evidence
  - Proven-absent isolated Qdrant restore with exact parity
  - Exact-image alias compatibility proof with restored pre-state
affects:
  - 21-03 reversible cutover
  - 21-04 recovery and final seal
actuals:
  tokens: 47580
  tasks: 2
  commits: 30
tech-stack:
  added: []
  patterns:
    - Digest-bound resumable operator journal
    - Snapshot-priority isolated Qdrant recovery
    - Aggregate value-free live evidence
key-files:
  created:
    - scripts/restore-solidstats-memory.py
    - .planning/phases/21-restore-cutover-recovery/21-BACKUP-RESTORE-EVIDENCE.json
    - .planning/phases/21-restore-cutover-recovery/21-02-SUMMARY.md
  modified:
    - scripts/validate-phase-21.py
    - tests/test-memory-cutover-contract.py
    - k8s/memory/10-qdrant.yaml
    - k8s/memory/20-mempalace.yaml
    - k8s/memory/30-network-policy.yaml
    - k8s/memory/40-backup.yaml
key-decisions:
  - The restore lock remains a mode-0600 machine-local operator artifact and is excluded from Git.
  - Only the closed aggregate evidence envelope is committed; private rendered manifests and raw operator responses remain outside Git.
  - Source manifest operator markers remain unresolved by design and fail closed until runtime-only rendering supplies measured values.
patterns-established:
  - Recompute every public and retained binding before private reads or live calls.
  - Accept exact resumptions while rejecting unequal run, prefix, package, and target collisions.
  - Verify active, public, client, legacy, and recurring-schedule pre-state after every isolated drill.
requirements-completed:
  - ISO-03
  - OPS-02
  - OPS-03
  - OPS-05
coverage:
  - id: D1
    description: Complete immutable backup package is locally and remotely checksum-verified.
    requirement: OPS-02
    verification:
      - kind: e2e
        ref: 21-BACKUP-RESTORE-EVIDENCE.json object_checks and package_checks
        status: pass
      - kind: integration
        ref: python3 scripts/validate-phase-21.py --evidence 21-BACKUP-RESTORE-EVIDENCE.json
        status: pass
    human_judgment: false
  - id: D2
    description: Proven-absent isolated target passes health, configuration, count, and exact parity.
    requirement: OPS-03
    verification:
      - kind: e2e
        ref: 21-BACKUP-RESTORE-EVIDENCE.json target_absence, restore_checks, and parity_checks
        status: pass
      - kind: unit
        ref: tests/test-memory-cutover-contract.py
        status: pass
    human_judgment: false
  - id: D3
    description: Exact MemPalace image resolves the temporary alias and the alias pre-state is restored.
    requirement: OPS-05
    verification:
      - kind: e2e
        ref: 21-BACKUP-RESTORE-EVIDENCE.json alias_compatibility
        status: pass
    human_judgment: false
  - id: D4
    description: Qdrant remains private and active alias, nginx, client, legacy runtime, routing, and schedule state remain unchanged.
    requirement: ISO-03
    verification:
      - kind: e2e
        ref: 21-BACKUP-RESTORE-EVIDENCE.json quiescence and rollback_state
        status: pass
    human_judgment: false
duration: 17h 28m
completed: 2026-08-21
status: complete
---

# Phase 21 Plan 02: Backup and Isolated Restore Summary

**A provenance-bound, download-verified backup restored into a proven-absent
Qdrant target with exact parity and reversible exact-image alias compatibility,
without changing active, public, client, legacy, or recurring state.**

## Performance

- **Duration:** 17h 28m across operator checkpoints
- **Started:** 2026-08-20T13:01:31Z
- **Completed:** 2026-08-21T06:29:46Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments

- Implemented the standard-library restore controller with complete Phase 20
  provenance recomputation, deterministic package verification, collision-safe
  resumability, absent-target checks, measured capacity gates, and
  snapshot-priority recovery.
- Created and download-verified one immutable four-member backup package
  containing the Qdrant snapshot, quiescent MemPalace metadata archive,
  checksums, and manifest.
- Restored 19,534 records into an isolated physical target and proved exact
  fields, identifiers, metadata, timestamps, vectors, exclusions, and ANN
  behavior.
- Proved the exact MemPalace image through a temporary alias, removed the alias,
  and verified that active routing, nginx, client registrations, legacy runtime,
  and the suspended recurring schedule remained unchanged.

## Task Commits

Task 1 used TDD and Task 2 used restartable checkpoint commits:

1. **Task 1: Implement fail-closed backup and isolated restore control**
   - RED: `9dbd7e9`, `8639ee5`
   - GREEN and hardening: `dbf5db5` through `52a30f1`
2. **Task 2: Authorize and prove one live backup plus isolated restore**
   - Aggregate evidence and plan summary: committed atomically with this file

## Files Created/Modified

- `scripts/restore-solidstats-memory.py` - Owns provenance, backup, restore,
  parity, alias compatibility, rollback checks, locks, and resumable evidence.
- `scripts/validate-phase-21.py` - Validates the closed aggregate backup and
  restore schema in addition to the Phase 21 transition chain.
- `tests/test-memory-cutover-contract.py` - Covers Qdrant adapters, failures,
  collisions, concurrency, interruption, privacy, and exact replay.
- `k8s/memory/10-qdrant.yaml` - Carries the measured-storage operator contract.
- `k8s/memory/20-mempalace.yaml` - Carries immutable image, storage, and
  collection-scoped runtime authorization contracts.
- `k8s/memory/30-network-policy.yaml` - Carries exact runtime-rendered operator
  network boundaries.
- `k8s/memory/40-backup.yaml` - Defines the suspended, deterministic backup
  package producer.
- `.planning/phases/21-restore-cutover-recovery/21-BACKUP-RESTORE-EVIDENCE.json`
  - Retains only aggregate booleans, counts, byte sizes, and SHA-256 bindings.

## Decisions Made

- Kept `.21-02-restore.lock` machine-local. It is runtime coordination state,
  not a durable plan deliverable, and may contain operator journal details.
- Committed only the aggregate evidence envelope. Private runtime renderings,
  names, paths, responses, credentials, and corpus values remain outside Git.
- Preserved unresolved operator markers in source manifests. The checked-in
  validators intentionally reject them until an authorized runtime render
  supplies measured private values.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Hardened the live operator against discovered runtime API
and package-shape mismatches**

- **Found during:** Task 2 live preflight, backup, restore, and verification
- **Issue:** The first live attempts exposed idempotency, dry-run namespace,
  snapshot workspace, backup readiness, metadata archive, stored-vector,
  bounded alias-action, and stateless MCP transport mismatches.
- **Fix:** Tightened each adapter and checkpoint journal without widening the
  authorized live scope or mutating active/public/client state.
- **Files modified:** Restore controller, Phase 21 validator, contract tests,
  and the four plan-owned memory manifests.
- **Verification:** 118-test combined suite, 28 operator-contract tests, 26
  cutover-contract tests, compilation, and aggregate live evidence validation.
- **Committed in:** `7c0ccab` through `52a30f1`

---

**Total deviations:** 1 grouped Rule 1 live-hardening class.
**Impact on plan:** The fixes were required for the authorized workflow to fail
closed and complete; no cutover or adjacent Phase 21 scope was added.

## Issues Encountered

- Source manifest and nginx validators still reject unresolved
  `MEMORY_OPERATOR_*` markers. This is the intended repository boundary; the
  successful live run used restrictive runtime-only rendered inputs and did
  not copy them into Git.

## User Setup Required

None for this completed drill. Future deploy or cutover runs still require the
authorized runtime-only operator inputs.

## Validation

- Combined runtime, policy, migration, and cutover suite: 118 tests passed.
- Operator contract suite: 28 tests passed.
- Cutover contract suite: 26 tests passed.
- Phase 21 aggregate evidence validator: passed.
- Restore controller and Phase 21 validator compilation: passed.
- JSON syntax and `git diff --check`: passed.
- Evidence verdict: `pass`; all package, object, target-absence, restore,
  parity, alias, and rollback sections are green.

## Next Phase Readiness

Plan 21-03 may use the verified restored target and alias compatibility result
for an independently authorized reversible cutover. This plan did not change
the active alias, nginx, machine-local client registration, legacy runtime, or
recurring backup schedule.

## Known Stubs

None. The `MEMORY_OPERATOR_*` source markers are deliberate fail-closed
runtime-render inputs, not implementation stubs, and the live evidence proves
the authorized rendered workflow completed.

## Self-Check: PASSED

- `21-BACKUP-RESTORE-EVIDENCE.json` exists, is mode 0600, validates, and has a
  passing verdict.
- All 29 pre-summary Plan 21-02 commits exist through `52a30f1`.
- The restore lock remains untracked, mode 0600, and excluded from this commit.
- The evidence and summary contain no private names, paths, raw responses,
  credentials, or corpus values.

---

*Phase: 21-restore-cutover-recovery*
*Completed: 2026-08-21*
