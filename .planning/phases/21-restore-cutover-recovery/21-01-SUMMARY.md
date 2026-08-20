---
phase: 21-restore-cutover-recovery
plan: 01
subsystem: restore-cutover-contract
tags:
  - cutover
  - recovery
  - network-policy
  - provenance
  - tdd
requires:
  - phase: 20-local-corpus-migration
    provides: Digest-bound Phase 21 handoff and passing parity report
provides:
  - Offline Phase 21 transition and evidence validator
  - Synthetic complete-chain and adversarial contract coverage
  - Exact reciprocal MemPalace-to-Qdrant egress policy
  - Order-independent observer and migration test execution
affects:
  - 21-02 restore execution
  - 21-03 private cutover
  - 21-04 public cutover and recovery
actuals:
  tokens: 9295.25
  tasks: 2
  commits: 4
tech-stack:
  added: []
  patterns:
    - Canonical digest-chained transition evidence
    - Exact NetworkPolicy shape validation
    - Scoped standard-library clock patching
key-files:
  created:
    - scripts/validate-phase-21.py
    - tests/test-memory-cutover-contract.py
    - .planning/phases/21-restore-cutover-recovery/21-01-SUMMARY.md
  modified:
    - k8s/memory/30-network-policy.yaml
    - scripts/validate-memory-manifests.py
    - tests/test-memory-runtime-contract.py
key-decisions:
  - Public evidence accepts only exact stage schemas and recursively rejects private or corpus-bearing values.
  - Exact replays are idempotent, while unequal collisions and stale transitions fail closed.
  - The Python 3.14.4 runtime remains unchanged because the observed failure was leaked test state.
patterns-established:
  - Every transition binds its canonical payload digest to the previous accepted stage.
  - Default-deny workload paths require an exact reciprocal ingress and egress contract.
requirements-progressed:
  - ISO-01
  - ISO-03
  - OPS-02
  - OPS-03
  - OPS-05
coverage:
  - id: D1
    description: Offline validator for the complete PREPARED-to-SEALED evidence chain
    requirement: OPS-03
    verification:
      - kind: unit
        ref: python3 -m unittest tests/test-memory-cutover-contract.py
        status: pass
    human_judgment: false
  - id: D2
    description: Fail-closed replay, lock, provenance, and value-free evidence checks
    requirement: OPS-05
    verification:
      - kind: unit
        ref: tests/test-memory-cutover-contract.py adversarial contract cases
        status: pass
    human_judgment: false
  - id: D3
    description: Exact reciprocal MemPalace-to-Qdrant path and restored observer clock
    requirement: ISO-03
    verification:
      - kind: integration
        ref: python3 -m unittest tests/test-memory-runtime-contract.py tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py tests/test-memory-cutover-contract.py
        status: pass
    human_judgment: false
duration: 13min
completed: 2026-08-20
status: complete
---

# Phase 21 Plan 01: Offline Cutover Contract Summary

**A digest-chained, value-free cutover state machine now gates later restore
and recovery work, with the private MemPalace-to-Qdrant path closed under
default deny.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-08-20T12:29:07Z
- **Completed:** 2026-08-20T12:41:47Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added a canonical offline validator for all nine stages from `PREPARED`
  through `SEALED`, including exact schemas, prior-digest chaining, stage
  locks, safe resume, and idempotent exact replay.
- Bound `PREPARED` evidence to recomputed Phase 20 handoff and parity digests
  while recursively excluding secrets, corpus content, private paths,
  identifiers, vectors, metadata values, and raw responses.
- Added the exact MemPalace-selected egress path to Qdrant TCP/6333 and made
  both the validator and mutation tests reject widened selectors,
  destinations, directions, labels, and ports.
- Restored `time.monotonic` after observer fixtures so the previously failing
  runtime-before-migration order passes on Python 3.14.4.

## Task Commits

Each TDD boundary was committed atomically:

1. **Task 1: Offline cutover evidence chain**
   - RED: `037ade1` (`test`)
   - GREEN: `e0f7f90` (`feat`)
2. **Task 2: Reciprocal NetworkPolicy and clock isolation**
   - RED: `c37feda` (`test`)
   - GREEN: `f44661f` (`fix`)

## Files Created/Modified

- `scripts/validate-phase-21.py` - Validates exact evidence envelopes, stage
  order, digest binding, locks, replay semantics, and public-data privacy.
- `tests/test-memory-cutover-contract.py` - Exercises a complete synthetic
  chain and failure injections without external access.
- `k8s/memory/30-network-policy.yaml` - Adds the exact same-namespace
  MemPalace-to-Qdrant TCP/6333 egress policy.
- `scripts/validate-memory-manifests.py` - Requires the reciprocal policy and
  rejects any shape drift.
- `tests/test-memory-runtime-contract.py` - Adds exact policy mutations and
  scopes observer clock patches.

## Decisions Made

- Kept public evidence schemas closed and canonical so later operators cannot
  add unreviewed fields or value-bearing diagnostics.
- Treated a byte-identical replay for the same run and prior digest as
  idempotent; any unequal collision or stale prior digest remains an error.
- Kept Python 3.14.4 and fixed shared-module test isolation instead of
  selecting another interpreter.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Validation

- `python3 -m unittest tests/test-memory-cutover-contract.py`: 7 tests passed.
- Manifest validation accepted 28 resources with operator placeholders.
- `python3 -m unittest tests/test-memory-runtime-contract.py`: 28 tests passed.
- Combined runtime, policy, migration, and cutover suite: 96 tests passed in
  the previously failing order.
- Python compilation and `git diff --check` passed on Python 3.14.4.
- No live cluster or external endpoint was contacted.

## Next Phase Readiness

Plan 21-02 can consume the tested state and evidence contract for isolated
restore work. All live and private-artifact mutations remain gated and were
intentionally not attempted here.

## Known Stubs

None.

## Self-Check: PASSED

- All four production TDD commits exist: `037ade1`, `e0f7f90`, `c37feda`, and
  `f44661f`.
- Only the five plan-declared implementation files changed before this summary.
- `STATE.md` and `ROADMAP.md` remain unchanged.
- The work used only offline repository fixtures and validators.

---

*Phase: 21-restore-cutover-recovery*
*Completed: 2026-08-20*
