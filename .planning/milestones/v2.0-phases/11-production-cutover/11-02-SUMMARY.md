---
phase: 11-production-cutover
plan: "02"
subsystem: infra
tags: [nginx, runbook, cutover, validator, gates, offline-ci]

requires:
  - phase: 11-production-cutover
    plan: "01"
    provides: scripts/cutover.sh — 4-gate reversible cutover script

provides:
  - docs/cutover.md — full operator runbook for production traffic cutover
  - scripts/validate-staging.py (extended) — offline CI gate for cutover artifacts

affects:
  - CI: python3 scripts/validate-staging.py now includes "ok: cutover artifacts"

tech-stack:
  added: []
  patterns:
    - "Coverage-only diff gate: strict_failures:0 is NOT an equality gate; value divergence allowlisted"
    - "Operator-gated runbook: live flip marked OPERATOR-ONLY throughout; CI never triggers cutover"
    - "Offline artifact gate: validate_cutover_artifacts() checks script+runbook existence+markers"
    - "Runbook style: six-section structure matching edge-bootstrap.md (overview/policy/pre-flight/procedure/rollback/offline-checks)"

key-files:
  created:
    - docs/cutover.md
  modified:
    - scripts/validate-staging.py

key-decisions:
  - "Green-diff gate is coverage/integrity only (strict_failures: 0) — NOT value equality; value divergence from parser rewrite is expected and human-reviewed"
  - "validate_cutover_artifacts() checks marker strings in both script and runbook; file existence alone is insufficient"
  - "Cutover evidence section in runbook is a clearly-marked placeholder — operator fills it post-flip, never fabricated"
  - "CUT-05 deferred note included; v1 is single one-edit cutover only"
  - "Task 3 (live cutover checkpoint) is operator-gated — not executed autonomously"

metrics:
  duration: ~25min
  completed: "2026-06-13"

status: complete
---

# Phase 11 Plan 02: Cutover Runbook and Offline Validator Summary

**Operator runbook (docs/cutover.md) and offline CI gate (validate_cutover_artifacts) for the Phase 11 production traffic cutover — four pre-flight gates, coverage-only diff note, proven rollback, and timing guidance**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-06-13
- **Tasks:** 2/2 autonomous (Task 3 is operator-gated checkpoint — not executed)
- **Files modified:** 2

## Accomplishments

- `docs/cutover.md` created: six-section operator runbook covering all 4 gates, one-edit upstream switch, auto-rollback, timing guidance, coverage-only note, CUT-05 deferred, operator evidence placeholder
- `scripts/validate-staging.py` extended: `validate_cutover_artifacts()` asserts both `scripts/cutover.sh` and `docs/cutover.md` exist with all required gate markers; `validate_scripts()` extended to include `cutover.sh` in bash -n loop
- `python3 scripts/validate-staging.py` exits 0 — all 10 checks pass including `ok: cutover artifacts`

## Task Commits

1. **Task 1: docs/cutover.md** — `c7f5de0` (docs)
2. **Task 2: validate-staging.py extension** — `771c02e` (feat)

## Files Created/Modified

- `docs/cutover.md` — 222-line operator runbook: gates, procedure, rollback, timing, coverage-only note
- `scripts/validate-staging.py` — +62 lines: `validate_cutover_artifacts()` + cutover.sh in bash -n loop + main() wire

## Decisions Made

- Green-diff gate is `strict_failures: 0` — coverage/integrity only, never equality. Value divergence between old and new parser is expected by design (memory: `legacy-vs-new-parser-non-identical`).
- `validate_cutover_artifacts()` checks marker strings in both the script and the runbook; file existence alone is insufficient (T-11-08 mitigation).
- Cutover evidence table in `docs/cutover.md` is a clearly-marked placeholder — operator fills it after the live flip; fabricating values is explicitly prohibited.
- Task 3 (live production flip) is `type="checkpoint:human-verify"` with `gate="blocking"` — not executed by this autonomous run.

## Deviations from Plan

None — plan executed exactly as written. The `validate_cutover_artifacts()` implementation matches the plan spec verbatim, including the `run()` helper reuse and the forbidden-secret-patterns check.

## Operator-Gated Task (Task 3)

Task 3 (`checkpoint:human-verify`) is the operator review gate. It is NOT executed autonomously. The operator must:

1. Run `python3 scripts/validate-staging.py` — expect `ok: cutover artifacts`
2. Run gate-logic dry-runs (see plan for exact commands with temp mock files)
3. Review `docs/cutover.md` for correctness
4. Run `SELF_TEST=1 ... bash scripts/cutover.sh` offline rollback proof
5. Type "approved" to signal the mechanism is ready

The live production traffic flip remains deferred until diff review passes in practice and the operator executes the cutover manually.

## Offline Verification Results

| Check | Result |
|-------|--------|
| `python3 scripts/validate-staging.py` | all 10 checks ok, exit 0 |
| `ok: cutover artifacts` present | yes |
| `bash -n scripts/cutover.sh` | ok (via validate_scripts + validate_cutover_artifacts) |
| Runbook markers (strict_failures, Status: verified, backup-gate.md, diff-readiness.md, rollback, NOT/equality) | all present |

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes. `docs/cutover.md` contains only addresses and file paths — no secrets. `validate_cutover_artifacts()` explicitly asserts the script contains no `SECRET_KEY`, `PASSWORD`, `TOKEN`, or `PRIVATE_KEY` references (T-11-08 mitigation). All threats in the plan's threat model are mitigated as specified.

## Self-Check: PASSED

- `docs/cutover.md` exists: confirmed
- `scripts/validate-staging.py` contains `validate_cutover_artifacts`: confirmed
- Commits `c7f5de0` and `771c02e` present in git log: confirmed
- `python3 scripts/validate-staging.py` exits 0: confirmed

---
*Phase: 11-production-cutover*
*Completed: 2026-06-13*
