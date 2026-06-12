---
phase: 08-automated-restore-drill
plan: "02"
subsystem: infra
tags: [kubernetes, postgres, backup, restore, drill, validate, ci]
dependency_graph:
  requires:
    - phase: 08-automated-restore-drill
      plan: "01"
      provides: scripts/restore-drill.sh and k8s/staging/restore-drill/70-restore-drill.yaml
  provides:
    - DRILL-04 offline regression guard in scripts/validate-staging.py
    - bash -n syntax check for scripts/restore-drill.sh in validate_scripts()
  affects:
    - CI validate step (python3 scripts/validate-staging.py)
tech_stack:
  added: []
  patterns:
    - MANIFEST_DIR.glob("*.yaml") stem filter for DRILL-04 placement check
    - Captured-result teardown pattern (negative test proves guard fires)
key_files:
  created: []
  modified:
    - scripts/validate-staging.py
key-decisions:
  - "Guard uses f.stem.lower() string containment (not grep) — immune to comment-stripping and reliable against T-08-D4-03"
  - "Token set ('drill', 'restore-drill') catches both generic and specific drill naming"
  - "restore-drill.sh added to bash -n loop via list extension — no structural change to validate_scripts()"
patterns-established:
  - "DRILL-04: depth-1 guard pattern for subdirectory-only manifests"
requirements-completed: [DRILL-04]
duration: 10min
completed: "2026-06-12"
status: complete
---

# Phase 08 Plan 02: DRILL-04 Regression Guard Summary

**DRILL-04 machine-enforced: offline CI guard blocks any drill manifest accidentally placed at k8s/staging depth-1, plus restore-drill.sh added to bash -n checks**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-12T18:28:00Z
- **Completed:** 2026-06-12T18:38:21Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- `validate_manifest_shape()` now contains a DRILL-04 guard that scans `MANIFEST_DIR.glob("*.yaml")` for stems containing `drill` or `restore-drill` and raises `ValidationError` with a clear message on match
- `validate_scripts()` now checks `scripts/restore-drill.sh` with `bash -n` alongside `scripts/backup-postgres-now.sh`
- Negative test confirmed: placing `restore-drill-test.yaml` at `k8s/staging/` depth-1 causes `validate-staging.py` to exit 1 with `DRILL-04 violation:` message; removing the file restores exit 0

## Task Commits

1. **Task 1: DRILL-04 depth-1 guard + restore-drill.sh syntax check** - `56b3308` (feat)

**Plan metadata:** see final commit below

## Files Created/Modified

- `scripts/validate-staging.py` — added 14-line DRILL-04 guard block in `validate_manifest_shape()` after the `missing` require; extended `validate_scripts()` bash -n loop to include `scripts/restore-drill.sh`

## Decisions Made

- Guard checks `f.stem.lower()` for tokens `("drill", "restore-drill")` — catches both `restore-drill-test.yaml` and `70-drill-job.yaml`-style names; accepts deliberate subdir placement unchanged
- No new imports added — `pathlib.Path` already used via `MANIFEST_DIR`
- Negative test (temp file at depth-1 then immediate removal) verified guard fires before other checks run (`ok: script syntax` prints first, then `error: DRILL-04 violation:`, exit 1)

## Deviations from Plan

None — plan executed exactly as written.

## Negative Test Evidence (DRILL-04 Guard Verification)

```
# Command run:
touch k8s/staging/restore-drill-test.yaml && python3 scripts/validate-staging.py 2>&1; EXIT=$?; rm k8s/staging/restore-drill-test.yaml && echo "exit_code=$EXIT"

# Output:
error: DRILL-04 violation: drill manifests must be in a subdirectory (k8s/staging/restore-drill/), not depth-1; found: restore-drill-test.yaml
ok: script syntax
exit_code=1
```

Guard fires at manifest shape check (after script syntax passes). File removed; subsequent `python3 scripts/validate-staging.py` exits 0.

## Issues Encountered

None.

## Threat Surface Scan

No new network endpoints or trust boundaries introduced. Guard is a pure filesystem read in offline CI context — no secrets, no cluster access.

## Next Phase Readiness

- Phase 08 Wave 1 complete: both plans (01 and 02) delivered their artifacts
- DRILL-04 is now machine-enforced in CI; placement constraint cannot regress silently
- DRILL-05 (scheduled CronJob + alerting) remains deferred to v2.x per CONTEXT.md

## Self-Check: PASSED

- scripts/validate-staging.py — FOUND (modified, committed 56b3308)
- DRILL-04 string in validate-staging.py — FOUND
- restore-drill.sh string in validate-staging.py — FOUND
- Commit 56b3308 — FOUND
- python3 scripts/validate-staging.py exits 0 — CONFIRMED
- Negative test (depth-1 yaml) exits 1 with DRILL-04 message — CONFIRMED

---
*Phase: 08-automated-restore-drill*
*Completed: 2026-06-12*
