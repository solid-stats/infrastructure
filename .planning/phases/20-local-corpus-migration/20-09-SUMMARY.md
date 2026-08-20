---
phase: 20-local-corpus-migration
plan: 09
subsystem: local-source-inventory
tags:
  - migration
  - source-admission
  - privacy
  - oracle
  - tdd
dependency_graph:
  requires:
    - 20-07 source-boundary repair and exact oracle contract
  provides:
    - lossless scalar metadata admission
    - isolated mutable-oracle execution
    - exact-image source-inventory evidence
  affects:
    - 20-04 real-source evidence publication
    - 20-08 human mapping checkpoint
tech_stack:
  added: []
  patterns:
    - source-only metadata-key validation
    - explicit private-output file modes
    - disposable isolated oracle scratch
key_files:
  created:
    - .planning/phases/20-local-corpus-migration/20-09-SUMMARY.md
  modified:
    - scripts/inventory-solidstats-memory.py
    - tests/test-solidstats-memory-migration.py
key_decisions:
  - Source admission checks metadata field shapes without scanning scalar values.
  - The mutable exact oracle runs only against a disposable validated copy.
patterns-established:
  - Private streamed output files explicitly receive restrictive permissions.
  - Snapshot integrity is measured outside mutable oracle workspace.
requirements-completed:
  - MIG-01
  - MIG-02
metrics:
  duration: continuation close-out
  tasks_completed: 2
  files_modified: 2
actuals:
  tokens: 4627.5
  tasks: 2
  commits: 7
completed: 2026-08-20
status: complete
---

# Phase 20 Plan 09: Source-Admission Gap Closure Summary

Lossless source admission, isolated exact-oracle execution, and private output
controls now pass both offline contracts and the main-owned exact-image gate.

## Accomplishments

- Kept source metadata scalar values lossless while rejecting protected-shaped
  metadata field names, without changing recursive control-plane screening.
- Made all private inventory output files explicitly restrictive, including
  streamed outputs whose permissions otherwise depended on the process umask.
- Ran the mutable exact oracle only in a disposable validated scratch copy,
  preserving the authoritative snapshot for the start/end integrity check.
- Normalized modes only inside that scratch copy so an immutable source can
  safely support the exact reader's writable workspace requirements.

## TDD Gate Compliance

- RED: `379ac86` added the lexical source-admission regression.
- GREEN: `5229e3a` limited source admission to metadata field shapes.
- Hardening: `35ee1eb` made streamed private-output modes explicit.
- RED: `85c3afb` added synthetic oracle-scratch isolation coverage.
- GREEN: `2fa3d8e` added disposable oracle scratch isolation.
- RED: `b8f3c5d` exposed inherited read-only scratch modes.
- GREEN: `8a5d6c9` normalized modes only in disposable scratch data.

## Validation

- 34 offline tests passed.
- Python compilation, inventory CLI help, and the public policy validator
  passed.
- The policy and validator files had zero diff.
- The main-owned exact-image gate used the pinned
  `personal-mempalace:3.5.0` image with networking disabled and passed with
  the sole CLI line `PASS: source inventory contract validated`.
- The gate produced 19,555 source records and 19,555 corresponding vectors.
  All private line totals matched the record count.
- Exactly four expected private output files were present; the directory mode
  was `0700` and each file mode was `0600`.
- Cross-artifact checksums matched the private summary, and a freshly computed
  authoritative snapshot digest matched its recorded value.
- Schema version 1, the private-evidence marker, and shape evidence were
  present. The completed container and temporary probe artifacts were removed;
  the immutable snapshot and successful private inventory remain retained for
  Plan 20-04.

## Unresolved Mapping Decisions

- Timestamp precedence and normalization remain unresolved.
- Wing mapping remains unresolved.
- Room and archive treatment remain unresolved.
- Agent and other-wing disposition remains unresolved.
- Preservation representation remains unresolved.

No mapping decision was selected. Plan 20-04 is next and must publish
sanitized real-source evidence from the retained successful private inventory.
Plan 20-08 remains the later blocking human checkpoint.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Privacy control] Explicit restrictive modes for streamed files**

- **Found during:** Task 1
- **Issue:** Streamed private artifacts inherited the process umask instead of
  having an explicit restrictive mode.
- **Fix:** Set the mode immediately after exclusive file creation.
- **Why required:** The private-output contract requires each output file to
  be readable only by its owner.
- **Verification:** Offline permission assertions and the exact-image gate
  confirmed one restrictive directory and four restrictive files.
- **Files modified:** `scripts/inventory-solidstats-memory.py`,
  `tests/test-solidstats-memory-migration.py`
- **Commit:** `35ee1eb`

**2. [Rule 1 - Bug] Isolated mutable oracle scratch from snapshot integrity**

- **Found during:** Task 2
- **Issue:** A mutable exact reader could write inside the tree measured by the
  authoritative snapshot integrity gate.
- **Fix:** Copied validated oracle data into disposable private scratch before
  invoking the exact reader.
- **Why required:** The integrity gate must detect external source drift rather
  than reader-owned maintenance.
- **Verification:** Synthetic full and check-only paths proved isolation,
  cleanup, and external-drift detection; the exact-image gate passed.
- **Files modified:** `scripts/inventory-solidstats-memory.py`,
  `tests/test-solidstats-memory-migration.py`
- **Commit:** `85c3afb`, `2fa3d8e`

**3. [Rule 1 - Bug] Normalized modes only in disposable oracle scratch**

- **Found during:** Task 2
- **Issue:** A read-only authoritative input produced a read-only copied
  workspace that the exact reader could not maintain.
- **Fix:** Validated scratch entries, then normalized directory and file modes
  only within the disposable copy.
- **Why required:** The exact reader needs a writable workspace while the
  authoritative source must remain immutable.
- **Verification:** Synthetic mode assertions, cleanup checks, and the
  exact-image gate passed.
- **Files modified:** `scripts/inventory-solidstats-memory.py`,
  `tests/test-solidstats-memory-migration.py`
- **Commit:** `b8f3c5d`, `8a5d6c9`

**Total deviations:** 3 auto-fixed (2 Rule 1, 1 Rule 2).
**Impact:** The changes preserve source losslessness, private-output controls,
and authoritative integrity without selecting downstream mapping semantics.

## Known Stubs

None.

## Self-Check: PASSED

- The summary exists at the required phase path.
- All seven implementation commits exist: `379ac86`, `5229e3a`, `35ee1eb`,
  `85c3afb`, `2fa3d8e`, `b8f3c5d`, and `8a5d6c9`.
- Only the declared source and test files changed during implementation.
- This close-out adds only this summary before the separate state update.
