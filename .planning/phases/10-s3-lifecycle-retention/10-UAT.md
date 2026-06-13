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
result: ✅ SUPPORTED (2026-06-13, confirmed via raw `--debug`). `GET /sg-replays?lifecycle` returns the AWS-standard **HTTP 404 `<Code>NoSuchLifecycleConfiguration</Code>`** — API implemented, no config on the bucket. The `argument of type 'NoneType' is not iterable` seen via the high-level CLI is an **aws-cli v2.32.7 client bug** parsing the empty `<Message></Message>` of the 404 — not unsupported. `head-bucket` OK. BUT the probe heuristic AND `apply-s3-lifecycle.sh`'s GET-before-PUT guard both grep the crashing high-level GET → both misclassify a clean bucket as "config found"; **fix the tooling to read the raw response before apply.**

### 2. Observed object expiry (x-amz-expiration)
expected: A test object under the ISOLATED `s3-lifecycle-probe/` prefix returns an `x-amz-expiration` header / `.Expiration` field after a short-expiry rule is applied to that prefix — proving the rule is recognized/applied. (Actual deletion is async ~24h+.)
result: ✅ x-amz-expiration PRESENT (2026-06-13). A reversible PUT→GET round-trip applied a 1-day rule on `s3-lifecycle-probe/`; a probe object's `head-object` returned `Expiration: expiry-date="Mon, 15 Jun 2026 00:00:00 GMT", rule-id="probe-roundtrip"`. PUT→GET round-tripped (200 + rule). Endpoint recognizes lifecycle rules and computes expiry. Never touched `backups/postgres/`. NOTE: `delete-bucket-lifecycle` is a NO-OP on Timeweb — the probe rule could not be deleted (only replaceable via PUT); it is harmless (empty prefix) and the real apply will replace it.

### 3. Apply real retention to backups/postgres/ (consequential)
expected: `bash scripts/apply-s3-lifecycle.sh` applies config/s3/backups-lifecycle.json (30-day expiration on backups/postgres/ + abort-incomplete-multipart 7d). GET-before-PUT aborts if a different config exists unless FORCE_OVERWRITE=1. `get-bucket-lifecycle-configuration` round-trips the applied policy.
result: [pending — operator] Run ONLY after tests 1-2 pass and evidence is recorded in docs/s3-lifecycle.md. This DELETES backup objects older than 30 days — confirm the retention window is intended first.

## Summary

total: 3
passed: 0
issues: 1
pending: 1
skipped: 0
blocked: 1

note: 2026-06-13 — S3-03 PROVEN. Timeweb fully supports the lifecycle API: PUT→GET round-trip OK + x-amz-expiration computed (reversible test on isolated s3-lifecycle-probe/). CRITICAL caveat: delete-bucket-lifecycle is a NO-OP — a config can only be REPLACED via PUT, never removed (rollback = PUT new config). Test 3 (destructive apply to backups/postgres/) now only gated on: (a) backup-inventory review (blast radius), (b) operator confirmation. The apply runs with FORCE_OVERWRITE=1 (a harmless leftover probe rule is present; the apply PUT replaces it). Latent follow-up (non-blocking): the apply guard + probe heuristic crash on a CLEAN bucket via the aws-cli NoneType bug — fix to read raw <Code>; does not affect this already-non-clean bucket.

## Gaps

### Why operator-gated (not done in the autonomous run)
Applying the lifecycle policy to the production `backups/postgres/` prefix is a consequential, retention-affecting
change (it deletes old backups), and the empirical probe writes to shared S3 + needs a cluster `kubectl apply`.
The autonomous run built and offline-verified all artifacts (S3-01, S3-02) and made the live proof turnkey, but
deliberately did NOT apply retention to production backups or write to shared S3 unattended (per the project risk
policy). The Cloud-side classifier also guards such shared-infra writes. See docs/s3-lifecycle.md for the runbook.
