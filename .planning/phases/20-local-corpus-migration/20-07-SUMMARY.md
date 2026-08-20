---
phase: 20-local-corpus-migration
plan: 07
subsystem: local-source-inventory
tags:
  - migration
  - source-boundary
  - metadata
  - tdd
dependency_graph:
  requires:
    - 20-03 frozen snapshot and exact oracle contract
  provides:
    - lossless source-shape inventory evidence
    - snapshot drift rejection
  affects:
    - 20-04
    - 20-05
tech_stack:
  added: []
  patterns:
    - lossless source validation
    - bounded value-free aggregation
    - start-end snapshot digest gate
key_files:
  created:
    - .planning/phases/20-local-corpus-migration/20-07-SUMMARY.md
  modified:
    - scripts/inventory-solidstats-memory.py
    - tests/test-solidstats-memory-migration.py
decisions:
  - Source admission uses only source-safe bounds, not target mapping eligibility.
  - Source-shape evidence records categories and counts, never observed values.
metrics:
  duration: 0m
  tasks_completed: 2
  files_modified: 2
actuals:
  tokens: 5342
  tasks: 2
  commits: 4
completed: 2026-08-20
status: complete
---

# Phase 20 Plan 07: Source-Boundary Repair Summary

The private inventory now preserves arbitrary valid legacy metadata while
emitting deterministic, bounded, value-free shape evidence for later mapping
review.

## Accomplishments

- Removed the source timestamp and target wing/room eligibility gates from
  source inventory admission without weakening metadata, document, vector,
  identifier, or bounds validation.
- Added synthetic end-to-end proof that legacy-shaped metadata and agent/other
  source wings retain exact object, canonical-byte, and digest evidence.
- Added value-free metadata type/format and source-label shape counts, with
  deterministic output ordering and bounded distinct-field tracking.
- Added a start/end snapshot digest equality gate that rejects drift and removes
  incomplete private output.

## TDD Gate Compliance

- RED: `f154e1a` adds the real-shape source-boundary regression, which failed
  because `source_timestamp` was mandatory.
- GREEN: `4df3d5d` removes target eligibility from source admission and passes
  the tracer verification.
- RED: `27f76ef` adds value-free shape and digest-drift regressions, which
  failed because the evidence and drift gate were absent.
- GREEN: `690c598` adds deterministic source-shape evidence and the digest gate.

## Validation

- `timeout 25s python3 -m unittest tests/test_inventory_solidstats_memory.py`
  `tests/test-solidstats-memory-migration.py`
  `tests/test-solidstats-memory-policy.py` — PASS (30 tests).
- `timeout 10s python3 -m py_compile scripts/inventory-solidstats-memory.py` — PASS.
- `timeout 10s python3 scripts/inventory-solidstats-memory.py --help` — PASS.
- `git diff --exit-code -- config/solidstats-memory/migration-policy.json`
  `scripts/validate-solidstats-memory-policy.py` — PASS.

## Unresolved Blockers Before 20-05

- Timestamp precedence and timestamp normalization remain undecided; this plan
  only counts source-side forms.
- Source wing-to-target-wing mapping remains undecided.
- Source room mapping and archive treatment remain undecided.
- The disposition of agent and other source wings remains undecided.
- The target preservation representation, including any transform-time field
  mapping or exclusion, remains undecided.

Plan 20-04 must report real source shapes before those decisions can be made.
Plan 20-05 must not begin until the mapping owner explicitly resolves them.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- Both modified implementation and test files exist.
- All four TDD commits exist in Git history.
- Only the declared source, test, and summary files changed for this plan.
