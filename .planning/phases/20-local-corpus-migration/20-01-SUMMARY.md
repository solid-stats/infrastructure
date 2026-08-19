---
phase: 20-local-corpus-migration
plan: "01"
subsystem: migration-validation
tags: [python, unittest, sha256, offline, fail-closed]
requires:
  - phase: 19-solidstats-memory-foundation
    provides: the initial migration policy validator
provides:
  - checksummed offline freeze-to-parity bundle contract
  - bounded untrusted-input validation with secret-safe diagnostics
  - MemPalace v3.5.0 mapping and ranked-parity evidence contracts
affects: [20-02, 20-03, 20-04, 20-05, 20-06, phase-21-cutover]
actuals:
  tokens: 10669
  tasks: 3
  commits: 7
tech-stack:
  added: []
  patterns:
    - standard-library-only bounded JSON and JSONL validation
    - checksum-bound fail-closed evidence chain
key-files:
  created:
    - tests/test-solidstats-memory-migration.py
  modified:
    - config/solidstats-memory/migration-policy.json
    - scripts/validate-solidstats-memory-policy.py
key-decisions:
  - Synthetic parity reports are explicitly non-production evidence.
  - UUIDv5 identity and collection derivation require pinned oracle evidence.
patterns-established:
  - Validate checksums and containment before semantic artifact parsing.
  - Report only artifact paths and JSON locations, never source values.
requirements-completed: [MIG-01, MIG-02]
coverage:
  - id: D1
    description: Synthetic freeze-to-parity bundle validation
    requirement: MIG-01
    verification:
      - kind: unit
        ref: tests/test-solidstats-memory-migration.py#MigrationContractTests
        status: pass
    human_judgment: false
  - id: D2
    description: Hostile bundle containment and bounded validation
    requirement: MIG-01
    verification:
      - kind: unit
        ref: tests/test-solidstats-memory-migration.py#UntrustedBundleTests
        status: pass
    human_judgment: false
  - id: D3
    description: Mapping, vector, collection, and recall evidence contract
    requirement: MIG-02
    verification:
      - kind: unit
        ref: tests/test-solidstats-memory-migration.py#MappingContractTests
        status: pass
    human_judgment: false
duration: 7m
completed: 2026-08-19
status: complete
---

# Phase 20 Plan 01: Local Corpus Migration Summary

**Offline validator contract for checksummed freeze, source inventory,
transform, and synthetic parity evidence without a real migration claim.**

## Performance

- **Duration:** 7m
- **Started:** 2026-08-19T23:01:05Z
- **Completed:** 2026-08-19T23:08:30Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added a checksum-bound synthetic tracer from write-freeze evidence to a
  non-production parity report through `validate_bundle`.
- Rejected unsafe and symlinked paths, lossy records, oversized artifacts,
  and credential-shaped evidence without reporting their values.
- Required deterministic UUIDv5 mappings, pinned collection derivation,
  explicit vector strategy evidence, and ranked recall fixtures.

## Task Commits

1. **Task 1: Validate one synthetic record from freeze attestation to parity report**
   - `1e184f5` (RED), `4a630d7` (GREEN)
2. **Task 2: Reject hostile paths, lossy records, unbounded work, and
   secret-shaped evidence**
   - `2b64006` (RED), `ef21830` (GREEN)
3. **Task 3: Freeze the v3.5.0 identity, collection, vector, and recall report contracts**
   - `39a4ecb` (RED), `3f8f003` (GREEN), `6820781` (fix)

## Files Created/Modified

- `config/solidstats-memory/migration-policy.json` — declarative artifact,
  mapping, and resource-bound contract.
- `scripts/validate-solidstats-memory-policy.py` — fail-closed bundle,
  source, transform, parity, containment, and disclosure validation.
- `tests/test-solidstats-memory-migration.py` — non-secret synthetic
  contract, hostile-input, and mapping fixtures.

## Decisions Made

- Synthetic parity carries `synthetic: true` and `real_parity_evidence: false`.
- Reuse requires complete compatibility evidence; otherwise only a pinned
  local re-embedding branch is valid.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Bound source and oracle evidence to verified artifacts**

- **Found during:** Task 3
- **Issue:** Initial semantic checks did not prove that the inventory checksum
  matched its listed source file or that collection derivation used the same
  oracle as ID mapping.
- **Fix:** Added checksum and oracle-equality checks before accepting bundle
  evidence.
- **Files modified:** `scripts/validate-solidstats-memory-policy.py`
- **Verification:** Full offline suite passed.
- **Committed in:** `6820781`

**Total deviations:** 1 auto-fixed (1 bug)

**Impact on plan:** The fix enforces the planned evidence chain without
expanding the migration scope.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plans 20-02 through 20-06 can consume the validator contract. A real transform
and parity claim remain blocked on the operator freeze, the reviewed v3.5.0
environment, and isolated local Qdrant availability.

## Self-Check: PASSED

- Created test module exists.
- All seven task commits exist in the current branch history.

---

*Phase: 20-local-corpus-migration*
*Completed: 2026-08-19*
