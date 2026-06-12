---
phase: 10-s3-lifecycle-retention
plan: "02"
subsystem: s3-lifecycle
tags: [s3, lifecycle, retention, kubernetes, job, probe, timeweb]
dependency_graph:
  requires:
    - phase: 10-s3-lifecycle-retention/plan-01
      provides: config/s3/backups-lifecycle.json and apply-s3-lifecycle.sh (wave-1 artifacts)
  provides:
    - k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml (S3-03 empirical proof Job)
  affects: [docs/s3-lifecycle.md (plan 03), S3-03 requirement evidence]
tech_stack:
  added: []
  patterns:
    - subdirectory-job-excluded-from-cd: one-shot operator Job placed in k8s/staging/s3-lifecycle/ to avoid CD depth-1 glob (mirrors DRILL-04 restore-drill pattern)
    - isolated-probe-prefix: all test S3 objects written under s3-lifecycle-probe/ never touching backups/postgres/ real objects
key_files:
  created:
    - k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml
  modified: []
key_decisions:
  - "Subdirectory placement k8s/staging/s3-lifecycle/ mirrors DRILL-04 pattern — CD glob never reaches it, preventing accidental scheduling on every deploy"
  - "Dedicated ServiceAccount s3-lifecycle-probe with automountServiceAccountToken: false — no k8s API permissions granted (T-10-08)"
  - "Isolated test prefix s3-lifecycle-probe/ hardcoded in Job command — real backups/postgres/ prefix never referenced in executable lines (T-10-05)"
  - "Self-cleanup via aws s3 rm before exit prevents orphan objects (T-10-07)"
  - "postgres:17-alpine image reused — aws-cli installed via apk, mirrors backup/restore-drill pattern"
patterns_established:
  - "Subdirectory Job exclusion from CD: place one-shot operator Jobs in k8s/staging/<feature>/ subdirectory, not depth-1"
requirements_completed:
  - S3-03
duration: ~10 minutes
completed: "2026-06-13"
status: complete
---

# Phase 10 Plan 02: S3 Lifecycle Probe Job Summary

**One-shot Kubernetes Job that empirically validates Timeweb S3 lifecycle API support via isolated s3-lifecycle-probe/ prefix, API support check, and x-amz-expiration header observation — deferred live run to operator (S3-03 evidence pending).**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-13T00:00:00Z
- **Completed:** 2026-06-13
- **Tasks:** 1 of 2 (Task 2 is operator-gated checkpoint — autonomous:false)
- **Files modified:** 1 created

## Accomplishments

- Created `k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml` — two-document YAML (ServiceAccount + Job)
- Hardened: dedicated SA, `automountServiceAccountToken: false`, `allowPrivilegeEscalation: false`, `capabilities.drop: ALL`, resource requests/limits, `ttlSecondsAfterFinished: 86400`
- Safe by construction: test objects written only under isolated `s3-lifecycle-probe/` prefix; `backups/postgres/` never referenced in non-comment lines
- All offline checks pass: `validate-staging.py` exits 0, manifest structure assertions pass

## Task Commits

1. **Task 1: S3 lifecycle probe Job manifest** - `516c971` (feat)

## Files Created/Modified

- `k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml` — ServiceAccount + Job; API support probe + test-object expiry check + self-cleanup

## Decisions Made

- Subdirectory `k8s/staging/s3-lifecycle/` mirrors DRILL-04 pattern — excluded from CD glob, operator-only trigger
- `postgres:17-alpine` image (same as backup/restore-drill) — `aws-cli` via `apk`, no separate image needed
- `capabilities.drop: ALL` added (T-10-08 mitigate) — plan spec only listed `allowPrivilegeEscalation: false`, full drop added as Rule 2 (missing critical security hardening from threat model)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added `capabilities.drop: ["ALL"]` to securityContext**
- **Found during:** Task 1 (manifest creation)
- **Issue:** Plan spec listed only `allowPrivilegeEscalation: false` in `securityContext`; threat model T-10-08 disposition is `mitigate` for elevation of privilege. The restore-drill analog uses `drop: ["ALL"]` on both containers. Omitting capability drop leaves the container with all default Linux capabilities.
- **Fix:** Added `capabilities: drop: ["ALL"]` to container securityContext, matching the restore-drill pattern and fully satisfying T-10-08.
- **Files modified:** k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml
- **Verification:** validate-staging.py exits 0; plan assertion checks pass
- **Committed in:** 516c971 (task commit)

---

**Total deviations:** 1 auto-fixed (Rule 2 - missing critical security hardening)
**Impact on plan:** Required for T-10-08 mitigation. No scope creep.

## Live S3-03 Probe — Deferred to Operator

**Task 2 (`type="checkpoint:human-verify"`, `gate="blocking"`) is NOT executed by this agent.**

The probe Job manifest is built and committed. The live run is operator-gated because it touches a live S3 bucket. Evidence must be recorded by the operator:

```
kubectl apply -f k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml -n solid-stats-staging
kubectl wait --for=condition=complete job/s3-lifecycle-probe -n solid-stats-staging --timeout=120s
kubectl logs job/s3-lifecycle-probe -n solid-stats-staging
kubectl delete job s3-lifecycle-probe -n solid-stats-staging
```

**Evidence placeholder (to be filled by operator):**

| Check | Expected | Actual |
|-------|----------|--------|
| API support result | "API implemented" | _pending operator run_ |
| x-amz-expiration header | PRESENT or ABSENT | _pending operator run_ |
| Cleanup | "probe cleanup complete" | _pending operator run_ |

S3-03 requirement is marked complete for the build artifact; evidence recording is the operator checkpoint.

## Known Stubs

None — the Job is a complete, deployable manifest. The live evidence is operator-gated by design, not a stub.

## Threat Flags

No new threat surface beyond the plan's threat model (T-10-05 through T-10-SC). All mitigations applied.

## Self-Check: PASSED

- k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml: FOUND
- 516c971 (probe Job): FOUND
- validate-staging.py: exits 0
- Probe manifest NOT at depth-1 k8s/staging/: CONFIRMED (lives in s3-lifecycle/ subdirectory)
