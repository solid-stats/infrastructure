---
status: complete
phase: 10-s3-lifecycle-retention
source: [10-VERIFICATION.md]
started: 2026-06-13T01:40:00Z
updated: 2026-06-13T06:05:00Z
---

## Current Test

number: 3
name: S3-03 proven + 30-day retention APPLIED to backups/postgres/ (operator-executed 2026-06-13)
expected: |
  Empirical proof recorded (API supported, PUT/GET/x-amz-expiration), then the 30-day retention
  applied to backups/postgres/ with operator confirmation after a backup-inventory review.
result: ✅ DONE 2026-06-13. All three tests resolved; retention live. See per-test results below.

## Tests

### 1. Timeweb lifecycle API support
expected: `aws s3api get-bucket-lifecycle-configuration` returns a config or `NoSuchLifecycleConfiguration` (API implemented), NOT `NotImplemented`.
result: ✅ SUPPORTED (2026-06-13, confirmed via raw `--debug`). `GET /sg-replays?lifecycle` returns the AWS-standard **HTTP 404 `<Code>NoSuchLifecycleConfiguration</Code>`** — API implemented, no config on the bucket. The `argument of type 'NoneType' is not iterable` seen via the high-level CLI is an **aws-cli v2.32.7 client bug** parsing the empty `<Message></Message>` of the 404 — not unsupported. `head-bucket` OK. BUT the probe heuristic AND `apply-s3-lifecycle.sh`'s GET-before-PUT guard both grep the crashing high-level GET → both misclassify a clean bucket as "config found"; **fix the tooling to read the raw response before apply.**

### 2. Observed object expiry (x-amz-expiration)
expected: A test object under the ISOLATED `s3-lifecycle-probe/` prefix returns an `x-amz-expiration` header / `.Expiration` field after a short-expiry rule is applied to that prefix — proving the rule is recognized/applied. (Actual deletion is async ~24h+.)
result: ✅ x-amz-expiration PRESENT (2026-06-13). A reversible PUT→GET round-trip applied a 1-day rule on `s3-lifecycle-probe/`; a probe object's `head-object` returned `Expiration: expiry-date="Mon, 15 Jun 2026 00:00:00 GMT", rule-id="probe-roundtrip"`. PUT→GET round-tripped (200 + rule). Endpoint recognizes lifecycle rules and computes expiry. Never touched `backups/postgres/`. NOTE: `delete-bucket-lifecycle` is a NO-OP on Timeweb — the probe rule could not be deleted (only replaceable via PUT); it is harmless (empty prefix) and the real apply will replace it.

### 3. Apply real retention to backups/postgres/ (consequential)
expected: `bash scripts/apply-s3-lifecycle.sh` applies config/s3/backups-lifecycle.json (30-day expiration on backups/postgres/ + abort-incomplete-multipart 7d). GET-before-PUT aborts if a different config exists unless FORCE_OVERWRITE=1. `get-bucket-lifecycle-configuration` round-trips the applied policy.
result: ✅ APPLIED 2026-06-13 (operator-confirmed). `FORCE_OVERWRITE=1 bash scripts/apply-s3-lifecycle.sh` → `lifecycle configuration applied successfully`. The guard WARNed on the leftover `probe-roundtrip` rule, FORCE_OVERWRITE=1 replaced it with config/s3/backups-lifecycle.json (30-day expire on backups/postgres/ + abort-incomplete-multipart 7d). Pre-apply inventory: 37 backups / 111 objects, 2026-05-10 → 2026-06-13, ~904 MB; 30-day cutoff 2026-05-14 → the 6 oldest backups (05-10..05-13, 18 objects) will async-expire within ~24h; 31 recent backups (incl. today's 06-13) retained. Async deletion observable via `aws s3 ls backups/postgres/ --recursive | wc -l` dropping from 111.

## Summary

total: 3
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0

note: 2026-06-13 — PHASE 10 COMPLETE. S3-03 proven (Timeweb supports GET/PUT/x-amz-expiration; reversible round-trip) and the 30-day retention APPLIED to backups/postgres/ after a backup-inventory review + operator confirmation. 6 oldest backups (>30d) will async-expire; 31 retained. CRITICAL caveat carried forward: delete-bucket-lifecycle is a NO-OP on Timeweb — a config can only be REPLACED via PUT, never removed (rollback = PUT new config); documented in docs/s3-lifecycle.md §7. Latent follow-up (non-blocking, v2.x): the apply guard + probe heuristic crash on a CLEAN bucket via the aws-cli NoneType bug — fix to classify from the raw <Code>; does not affect this already-non-clean bucket.

## Gaps

### Why operator-gated (not done in the autonomous run)
Applying the lifecycle policy to the production `backups/postgres/` prefix is a consequential, retention-affecting
change (it deletes old backups), and the empirical probe writes to shared S3 + needs a cluster `kubectl apply`.
The autonomous run built and offline-verified all artifacts (S3-01, S3-02) and made the live proof turnkey, but
deliberately did NOT apply retention to production backups or write to shared S3 unattended (per the project risk
policy). The Cloud-side classifier also guards such shared-infra writes. See docs/s3-lifecycle.md for the runbook.
