---
phase: 08-automated-restore-drill
plan: "03"
subsystem: docs
tags: [docs, restore-drill, runbook, kubernetes, postgres, backup]
dependency_graph:
  requires:
    - phase: 08-automated-restore-drill
      plan: "01"
      provides: k8s/staging/restore-drill/70-restore-drill.yaml + scripts/restore-drill.sh
    - phase: 08-automated-restore-drill
      plan: "02"
      provides: DRILL-04 offline guard in scripts/validate-staging.py
  provides:
    - docs/backup-restore.md updated operator runbook for automated restore drill
  affects:
    - docs/backup-restore.md
tech_stack:
  added: []
  patterns:
    - Operator-captured evidence placeholder section (live drill deferred to operator)
key_files:
  created: []
  modified:
    - docs/backup-restore.md
decisions:
  - "Replaced entire manual drill section (kubectl exec steps) with automated Job runbook"
  - "Added operator-captured evidence placeholder section — live drill is a human-run gate, not automated"
  - "DRILL-05 deferred scheduling note carried forward from CONTEXT.md"
metrics:
  duration_s: 52
  completed: "2026-06-13"
  tasks_completed: 1
  tasks_total: 2
  files_created: 0
  files_modified: 1
status: complete
---

# Phase 08 Plan 03: Restore Drill Runbook Summary

Automated restore drill runbook replacing manual kubectl-exec drill steps in docs/backup-restore.md — DRILL-01..04 safety guarantees documented; live-drill checkpoint deferred to operator.

## What Was Built

**docs/backup-restore.md** — `## Restore Drill` section fully replaced:
- Run command: `K8S_NAMESPACE=solid-stats-staging bash scripts/restore-drill.sh`
- Script behaviour documented (5 steps: delete prior Job → apply manifest → wait 900s → print logs/evidence → delete Job)
- Expected output format with `DRILL_RESULT=PASS` example line (backup_id, table_count, total_rows, duration_s)
- `DRILL_RESULT=FAIL` triage instructions
- DRILL-01 safety guarantee: drill pod uses `PGHOST=localhost`, refuses if injected host != localhost; scratch postgres on `emptyDir`, never touches live `postgres-data` PVC
- DRILL-04 explanation: manifest in `k8s/staging/restore-drill/` subdirectory; CD glob `find k8s/staging -maxdepth 1 -name '*.yaml'` never matches it; depth-1 placement triggers `validate-staging.py` CI failure
- Read-only S3 note (no writes)
- Recommended cadence (pre-cutover Phase 11 gate, post-restore validation, monthly)
- Operator-captured evidence placeholder section (clearly marked `<!-- PLACEHOLDER -->`)
- DRILL-05 deferred scheduling note

## Task Status

| # | Name | Type | Commit | Files |
|---|------|------|--------|-------|
| 1 | Update docs/backup-restore.md — replace manual drill with automated runbook | auto | ca6e5bb | docs/backup-restore.md |
| 2 | Live drill on staging cluster — DRILL_RESULT=PASS evidence | checkpoint:human-verify | deferred | operator-run gate |

## Live-Drill Checkpoint (Deferred)

Task 2 is a `checkpoint:human-verify` (gate="blocking") — the live drill must be run by the operator
against the staging cluster. This is intentionally outside the scope of the autonomous doc executor.

**To complete Phase 8:** Run the drill per the runbook and paste the `DRILL_RESULT=PASS` line
into `.planning/phases/08-automated-restore-drill/08-03-SUMMARY.md` under the evidence placeholder,
then run `/gsd-verify-work` for phase sign-off.

## Verification

```
grep -q 'DRILL_RESULT=PASS' docs/backup-restore.md  # PASS
grep -q 'restore-drill.sh' docs/backup-restore.md   # PASS
grep -q 'postgres-data' docs/backup-restore.md      # PASS
grep -q 'DRILL-05' docs/backup-restore.md           # PASS
```

## Deviations from Plan

**1. [Rule 0 - Scope constraint] Live-drill checkpoint not executed by autonomous agent**
- **Issue:** Task 2 (checkpoint:human-verify) requires running `scripts/restore-drill.sh`
  against the live staging cluster — this is an operator gate, not automatable by this executor.
- **Fix:** Task 1 (doc update) committed; Task 2 left as clearly-marked deferred placeholder.
- **Impact:** Phase 8 sign-off pending operator running the live drill and pasting evidence.

No other deviations.

## Threat Surface Scan

No new network endpoints or trust boundaries introduced. This plan is a documentation update only.

## Self-Check: PASSED

- docs/backup-restore.md — FOUND (modified)
- DRILL_RESULT=PASS in docs/backup-restore.md — FOUND
- restore-drill.sh in docs/backup-restore.md — FOUND
- postgres-data in docs/backup-restore.md — FOUND
- DRILL-05 in docs/backup-restore.md — FOUND
- Commit ca6e5bb — FOUND
