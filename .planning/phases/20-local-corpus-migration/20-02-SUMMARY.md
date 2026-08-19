---
phase: 20-local-corpus-migration
plan: "02"
subsystem: migration-inventory
tags: [python, unittest, sha256, offline, fail-closed]
requires:
  - phase: 20-local-corpus-migration
    provides: migration policy and synthetic bundle validator
provides:
  - bounded offline source inventory CLI
  - deterministic private source recall fixtures
  - containment and secret-safe inventory diagnostics
affects: [20-03, 20-04, 20-05, 20-06, phase-21-cutover]
actuals:
  tokens: 8117
  tasks: 2
  commits: 6
tech-stack:
  added: []
  patterns:
    - standard-library-only private JSONL inventory
    - lstat and O_NOFOLLOW snapshot containment
    - deterministic source-only recall fixtures
key-files:
  created:
    - scripts/inventory-solidstats-memory.py
  modified:
    - tests/test-solidstats-memory-migration.py
key-decisions:
  - Source fixture selection is deterministic and records no query text.
  - Check-only validates only paths, freeze evidence, policy, and oracle.
patterns-established:
  - Private output directories must be newly created and non-symlinked.
  - Diagnostics use indexes and SHA-256 digests instead of corpus values.
requirements-completed: [MIG-01, MIG-02]
coverage:
  - id: D1
    description: Bounded lossless synthetic source inventory
    requirement: MIG-01
    verification:
      - kind: unit
        ref: tests/test-solidstats-memory-migration.py#InventoryContractTests
        status: pass
    human_judgment: false
  - id: D2
    description: Deterministic source recall fixtures and redacted evidence
    requirement: MIG-02
    verification:
      - kind: unit
        ref: tests/test-solidstats-memory-migration.py#InventoryContractTests
        status: pass
    human_judgment: false
duration: 5m
completed: 2026-08-20
status: complete
---

# Phase 20 Plan 02: Local Corpus Inventory Summary

**Offline bounded source inventory with lossless synthetic records, private
vectors, and deterministic source recall fixtures.**

## Performance

- **Duration:** 5m
- **Started:** 2026-08-19T23:14:44Z
- **Completed:** 2026-08-19T23:19:29Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added a standard-library CLI that validates the freeze attestation, pinned
  v3.5.0 oracle source, snapshot containment, records, metadata, and vectors.
- Emits private canonical JSONL records and vectors plus deterministic,
  source-only recall fixtures in a new owner-only output directory.
- Rejects symlinks, special files, duplicate IDs, unsupported metadata,
  secret-shaped values, invalid scope, and record-bound violations.

## Task Commits

1. **Task 1: Extract one complete synthetic collection through the v3.5.0 contract**
   - `4199016` (RED), `c330cc7` (GREEN)
2. **Task 2: Build deterministic bounded recall fixtures and sanitized evidence**
   - `b082f7a` (RED), `502fe77` (GREEN)

## Files Created/Modified

- `scripts/inventory-solidstats-memory.py` — bounded private inventory CLI.
- `tests/test-solidstats-memory-migration.py` — synthetic contract and
  hostile-input tests.

## Decisions Made

- Source fixture selection is deterministic and keeps query vectors and text
  private.
- `--check-only` does not read corpus records; it only validates operator
  prerequisites.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Kept the inventory module import-safe for the existing
test loader**

- **Found during:** Task 1
- **Issue:** `dataclass` initialization required a registered module during
  dynamic test loading.
- **Fix:** Replaced it with an explicit stdlib-only limits class.
- **Files modified:** `scripts/inventory-solidstats-memory.py`
- **Verification:** Full offline suite passed.
- **Committed in:** `c330cc7`

**2. [Rule 1 - Bug] Avoided allocation from the theoretical record ceiling**

- **Found during:** Task 1
- **Issue:** The source JSON limit multiplied record and byte ceilings before reading.
- **Fix:** Bound the synthetic collection file by the policy artifact ceiling.
- **Files modified:** `scripts/inventory-solidstats-memory.py`
- **Verification:** Full offline suite passed.
- **Committed in:** `c330cc7`

**Total deviations:** 3 auto-fixed bugs

**Impact on plan:** Both fixes preserve bounded, offline fail-closed behavior
without expanding scope.

**3. [Rule 1 - Bug] Replaced the synthetic collection file as the inventory source**

- **Found during:** Post-plan migration gate review.
- **Issue:** The inventory accepted only a preassembled `chroma-collection.json`,
  so it did not prove extraction from a complete frozen Chroma palace.
- **Fix:** Required raw `palace/chroma.sqlite3` plus manifest, identity,
  configuration, and embedder sidecars. The new isolated v3.5.0 oracle
  process uses `ChromaCollection.get` with `limit`, `offset`, and embeddings,
  derives the Qdrant mapping from the exact backend, and fails on protocol loss.
- **Files modified:** `scripts/inventory-solidstats-memory.py`,
  `tests/test-solidstats-memory-migration.py`
- **Verification:** 26 offline migration-policy and migration contract tests pass;
  Python compilation and CLI help pass.
- **Committed in:** `38aa055` (RED), `d2693d2` (GREEN)

## Known Stubs

None.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 20-03 can require real operator freeze and reviewed v3.5.0 runtime
evidence. This plan makes no real-corpus or target-parity claim.

## Self-Check: PASSED

- Inventory CLI and migration test module exist.
- All four TDD commits exist in the current branch history.

---

*Phase: 20-local-corpus-migration*
*Completed: 2026-08-20*
