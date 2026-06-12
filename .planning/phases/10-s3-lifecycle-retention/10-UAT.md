---
status: testing
phase: 10-s3-lifecycle-retention
source: [10-VERIFICATION.md]
started: 2026-06-13T01:40:00Z
updated: 2026-06-13T01:40:00Z
---

## Current Test

number: 1
name: S3-03 — Timeweb S3 lifecycle support proven empirically (operator-gated)
expected: |
  Operator runs the probe Job and (after review) the apply script against live Timeweb S3,
  records the API-support result + an observed x-amz-expiration as evidence in docs/s3-lifecycle.md,
  THEN applies the 30-day retention to backups/postgres/. Retention is not relied upon until proven.
awaiting: operator execution (consequential: applying retention DELETES old backups; not run unattended)

## Tests

### 1. Timeweb lifecycle API support
expected: `aws s3api get-bucket-lifecycle-configuration` returns a config or `NoSuchLifecycleConfiguration` (API implemented), NOT `NotImplemented`.
result: [pending — operator] Run the probe Job: `kubectl apply -f k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml -n solid-stats-staging`, then `kubectl logs job/s3-lifecycle-probe -n solid-stats-staging`. Record implemented vs not-implemented.

### 2. Observed object expiry (x-amz-expiration)
expected: A test object under the ISOLATED `s3-lifecycle-probe/` prefix returns an `x-amz-expiration` header / `.Expiration` field after a short-expiry rule is applied to that prefix — proving the rule is recognized/applied. (Actual deletion is async ~24h+.)
result: [pending — operator] From the probe Job logs. Never touches `backups/postgres/`.

### 3. Apply real retention to backups/postgres/ (consequential)
expected: `bash scripts/apply-s3-lifecycle.sh` applies config/s3/backups-lifecycle.json (30-day expiration on backups/postgres/ + abort-incomplete-multipart 7d). GET-before-PUT aborts if a different config exists unless FORCE_OVERWRITE=1. `get-bucket-lifecycle-configuration` round-trips the applied policy.
result: [pending — operator] Run ONLY after tests 1-2 pass and evidence is recorded in docs/s3-lifecycle.md. This DELETES backup objects older than 30 days — confirm the retention window is intended first.

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps

### Why operator-gated (not done in the autonomous run)
Applying the lifecycle policy to the production `backups/postgres/` prefix is a consequential, retention-affecting
change (it deletes old backups), and the empirical probe writes to shared S3 + needs a cluster `kubectl apply`.
The autonomous run built and offline-verified all artifacts (S3-01, S3-02) and made the live proof turnkey, but
deliberately did NOT apply retention to production backups or write to shared S3 unattended (per the project risk
policy). The Cloud-side classifier also guards such shared-infra writes. See docs/s3-lifecycle.md for the runbook.
