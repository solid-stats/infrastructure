---
phase: 10-s3-lifecycle-retention
plan: "01"
subsystem: s3-lifecycle
tags: [s3, retention, lifecycle, backup, offline-validation]
dependency_graph:
  requires: [phase-08-restore-drill]
  provides: [s3-lifecycle-policy, apply-script, offline-validator]
  affects: [scripts/validate-staging.py]
tech_stack:
  added: []
  patterns: [in-cluster-job-for-s3-ops, configmap-file-delivery, tdd-red-green]
key_files:
  created:
    - config/s3/backups-lifecycle.json
    - scripts/apply-s3-lifecycle.sh
    - scripts/validate-s3-lifecycle.py
  modified:
    - scripts/validate-staging.py
decisions:
  - "30-day retention window: conservative (30 daily backup points) without unbounded growth; operator can increase Days before applying"
  - "AbortIncompleteMultipartUpload 7d: AWS-recommended window; bucket-wide (Prefix='') to catch any stuck upload"
  - "ConfigMap delivery for JSON: avoids shell-escaping hazard with double-quote-heavy JSON in YAML heredoc"
  - "GET-before-PUT guard: warns on existing config, exits 1 on NotImplemented (S3-03 gate)"
  - "postgres-backup SA reused: SA is for pod identity only, not k8s API access; no new RBAC needed"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-13"
  tasks_completed: 3
  tasks_total: 3
  files_created: 3
  files_modified: 1
status: complete
---

# Phase 10 Plan 01: S3 Lifecycle Retention Summary

S3 lifecycle retention policy stored as a repo artifact with offline regression guard and in-cluster apply script — satisfying S3-01 and S3-02 fully offline.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 RED | TDD: failing validator | e9b8869 | scripts/validate-s3-lifecycle.py |
| 1 GREEN | Lifecycle JSON | 4814727 | config/s3/backups-lifecycle.json |
| 2 | Apply script | 590b2d7 | scripts/apply-s3-lifecycle.sh |
| 3 | Wire validate-staging.py | 222acb7 | scripts/validate-staging.py |

## What Was Built

### config/s3/backups-lifecycle.json
`PutBucketLifecycleConfiguration` JSON with two rules:
- `expire-postgres-backups`: `Filter.Prefix=backups/postgres/`, `Expiration.Days=30`, `Status=Enabled`
- `abort-incomplete-multipart`: `Filter.Prefix=""` (bucket-wide), `AbortIncompleteMultipartUpload.DaysAfterInitiation=7`, `Status=Enabled`

### scripts/apply-s3-lifecycle.sh
Operator script that creates a one-shot in-cluster Job to apply the policy:
- Creates a temp ConfigMap from the JSON file (`kubectl create configmap --from-file`) — avoids shell-escaping hazard
- Job mounts ConfigMap at `/config`, reads S3 creds from `server-2-runtime` secret
- GET-before-PUT: warns if existing lifecycle config found; exits 1 on `NotImplemented` (S3-03 gate)
- Cleans up Job + ConfigMap after completion; `exit 64` for missing config file

### scripts/validate-s3-lifecycle.py
Stdlib-only offline validator (json + pathlib + subprocess):
- `validate_lifecycle_json()`: asserts Expiration rule on `backups/postgres/` with `Days >= 30` + AbortIncompleteMultipartUpload rule with `DaysAfterInitiation >= 1`
- `validate_apply_script_syntax()`: `bash -n` + 6 required marker assertions (set -euo pipefail, exit 64, GET+PUT calls, endpoint URL, JSON filename)

### scripts/validate-staging.py (extended)
- `validate_scripts()`: added `py_compile` for `validate-s3-lifecycle.py` + `bash -n` for `apply-s3-lifecycle.sh`
- `validate_s3_lifecycle_config()`: strict `isinstance` checks for both rules (separate from the 30d gate in validate-s3-lifecycle.py — uses `Days >= 1` so operator can adjust window without breaking CI)
- `main()`: appended `("s3 lifecycle config", validate_s3_lifecycle_config)` after existing checks

## Verification Results

```
python3 scripts/validate-s3-lifecycle.py   → exit 0
  ok: s3 lifecycle JSON
  ok: apply script syntax and markers

python3 scripts/validate-staging.py        → exit 0
  ok: s3 lifecycle config  (among other checks)

bash -n scripts/apply-s3-lifecycle.sh      → exit 0

python3 -c "import json; d=json.load(open('config/s3/backups-lifecycle.json')); \
  assert any(r.get('Filter',{}).get('Prefix')=='backups/postgres/' for r in d['Rules'])"  → exit 0
```

## Negative Test Results (Success Criteria)

Both tests proved the validator correctly rejects malformed configs:

| Test | Mutation | Expected | Actual |
|------|----------|----------|--------|
| 1 | Remove `AbortIncompleteMultipartUpload` rule | exit 1 | exit 1 — `error: missing AbortIncompleteMultipartUpload rule with DaysAfterInitiation >= 1` |
| 2 | Remove `backups/postgres/` Expiration rule | exit 1 | exit 1 — `error: missing Expiration rule for backups/postgres/ with Days >= 30` |

Original JSON restored after both tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Duplicate "ok: s3 lifecycle config" output**
- **Found during:** Task 3 verification
- **Issue:** `validate_s3_lifecycle_config()` had its own `print("ok: s3 lifecycle config")` while `main()` also prints `ok: {label}` for every check — producing duplicate output
- **Fix:** Removed the `print` inside `validate_s3_lifecycle_config()` to match the pattern used by all other check functions in validate-staging.py
- **Files modified:** scripts/validate-staging.py
- **Commit:** 222acb7

## TDD Gate Compliance

- RED gate commit: e9b8869 `test(10-01): add failing validator...` — validator failed as expected (JSON missing)
- GREEN gate commit: 4814727 `feat(10-01): add S3 lifecycle retention policy JSON...` — validator passed after JSON created
- REFACTOR: not needed

## Known Stubs

None.

## Threat Flags

No new threat surface beyond what the plan's threat model covers (T-10-01 through T-10-SC). The `config/s3/` directory contains no secrets — only prefix strings and day counts, safe to commit.

## Self-Check: PASSED

- config/s3/backups-lifecycle.json: FOUND
- scripts/apply-s3-lifecycle.sh: FOUND
- scripts/validate-s3-lifecycle.py: FOUND
- e9b8869 (RED): FOUND
- 4814727 (JSON): FOUND
- 590b2d7 (apply script): FOUND
- 222acb7 (validate-staging): FOUND
