---
phase: 08-automated-restore-drill
plan: "01"
subsystem: restore-drill
tags: [kubernetes, postgres, backup, restore, drill, s3]
dependency_graph:
  requires:
    - k8s/staging/60-postgres-backup.yaml (backup source — S3 paths and secret wiring)
    - k8s Secret postgres-auth (POSTGRES_PASSWORD)
    - k8s Secret server-2-runtime (S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY)
  provides:
    - k8s/staging/restore-drill/70-restore-drill.yaml (on-demand restore drill Job)
    - scripts/restore-drill.sh (operator trigger script)
  affects:
    - k8s/staging/restore-drill/ (new subdirectory, excluded from CD glob by DRILL-04)
tech_stack:
  added: []
  patterns:
    - Scratch postgres via pg_ctl initdb on emptyDir (no sidecar, single container)
    - Captured-result teardown (drill_result saved before cleanup, exit $drill_result)
    - DRILL_RESULT=PASS/FAIL structured evidence line
    - DRILL-04 subdirectory isolation from CD apply glob
key_files:
  created:
    - k8s/staging/restore-drill/70-restore-drill.yaml
    - scripts/restore-drill.sh
  modified: []
decisions:
  - "Scratch postgres in same container via pg_ctl (not sidecar) — simpler, no inter-container auth"
  - "Lexicographic max of s3 ls output selects latest backup_id"
  - "|| true on pg_restore tolerates harmless 'already exists' warnings without masking real failures"
  - "backoffLimit: 0 — fail loud on first run, no silent retries"
  - "job_name fixed as restore-drill in manifest; operator script deletes pre-existing Job for idempotency"
metrics:
  duration_s: 88
  completed: "2026-06-13"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
status: complete
---

# Phase 08 Plan 01: Restore Drill Artifacts Summary

Ephemeral scratch-postgres restore drill Job (DRILL-01..04) with captured-result teardown and operator trigger script.

## What Was Built

**k8s/staging/restore-drill/70-restore-drill.yaml** — ServiceAccount + Job pair:
- Scratch postgres via `pg_ctl initdb` on `emptyDir` (fsGroup 999, never touches live `postgres-data` PVC or Service)
- DRILL-01 safety barrier verbatim before any initdb: refuses if `POSTGRES_HOST`/`PGHOST` != localhost
- Guarded DB name `solid_stats_drill` — createdb/dropdb/pg_restore target only this DB
- Sanity assertions: table_count >= 5, total_rows > 0, dump list non-empty
- `DRILL_RESULT=PASS/FAIL backup_id=... table_count=... total_rows=... duration_s=...` evidence line
- Teardown with `|| true` on all cleanup steps; `exit $drill_result` preserves assertion code
- Pod hardening: `automountServiceAccountToken: false`, `allowPrivilegeEscalation: false`, `fsGroup: 999`, resources requests+limits
- `backoffLimit: 0`, `ttlSecondsAfterFinished: 3600`
- DRILL-04: stored in subdirectory — CD glob `find k8s/staging -maxdepth 1 -name '*.yaml'` never matches

**scripts/restore-drill.sh** — operator trigger:
- Mirrors `backup-postgres-now.sh` style (`set -euo pipefail`, kubectl pattern)
- Deletes pre-existing `restore-drill` Job (idempotency), applies manifest, waits with timeout
- Extracts `DRILL_RESULT=` line; exits 1 on FAIL, 0 on PASS
- Cleans up Job object after successful run

## Tasks

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Restore-drill Job manifest | 8b78925 | k8s/staging/restore-drill/70-restore-drill.yaml |
| 2 | Operator script restore-drill.sh | 3501504 | scripts/restore-drill.sh |

## Verification Results

- `bash -n scripts/restore-drill.sh` — PASS
- `python3 scripts/validate-staging.py` — PASS (script syntax, manifest shape, workload safety, app image pins, rendered secret structure)
- DRILL-04 placement check (no manifest at depth-1) — PASS
- Structural grep: solid_stats_drill, DRILL-04, automountServiceAccountToken, allowPrivilegeEscalation, fsGroup, DRILL_RESULT= — all PASS

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints or trust boundary surface introduced beyond what the threat model documents (T-08-01..T-08-08). All mitigations implemented as specified.

## Self-Check: PASSED

- k8s/staging/restore-drill/70-restore-drill.yaml — FOUND
- scripts/restore-drill.sh — FOUND
- Commit 8b78925 — FOUND
- Commit 3501504 — FOUND
