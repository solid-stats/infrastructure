# Phase 10: S3 Lifecycle & Retention - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss); enriched with codebase facts by the orchestrator

<domain>
## Phase Boundary

Backup-prefix retention is enforced through a repo-stored, script-applied expiration policy, with
Timeweb S3 lifecycle support proven empirically before retention is relied upon.

Requirements: S3-01, S3-02, S3-03. Depends on: Phase 8.
S3-04 (distinct shorter windows for replay/ and artifact/ prefixes) is DEFERRED to v2.x — this phase
is the `backups/postgres/` prefix only.
</domain>

<decisions>
## Implementation Decisions

### Locked by codebase facts (verified 2026-06-13)
- **S3 target:** endpoint `https://s3.twcstorage.ru`, **path-style** addressing
  (`aws configure set default.s3.addressing_style path`), region `ru-1`, `AWS_EC2_METADATA_DISABLED=true`.
  Bucket name + creds come from the live k8s Secret `server-2-runtime` (`S3_BUCKET`, `S3_ACCESS_KEY_ID`,
  `S3_SECRET_ACCESS_KEY`) — NEVER hardcode or log secret values.
- **Backup layout (the prefix to expire):** `s3://$S3_BUCKET/backups/postgres/<backup_id>/{solid_stats.dump,.list,manifest.json}`,
  written daily by the `postgres-backup` CronJob (`k8s/staging/60-postgres-backup.yaml`). `backup_id` is a UTC timestamp.
- **In-cluster-creds pattern:** `scripts/backup-postgres-now.sh` runs S3 work as a one-shot k8s Job
  (`kubectl create job --from=cronjob/...`) so credentials stay in-cluster. Prefer the same approach for the
  lifecycle apply + the empirical probe (a small Job that mounts `server-2-runtime` and runs `aws s3api ...`)
  rather than pulling S3 creds onto an operator machine.

### Claude's discretion (decide during planning, justify in PLAN)
- **Lifecycle policy file (S3-01, S3-02):** store as `config/s3/backups-lifecycle.json` in
  `PutBucketLifecycleConfiguration` JSON shape, containing:
  - An **Expiration** rule scoped to `Filter.Prefix = backups/postgres/` with a sensible retention window.
    Default suggestion: **30 days** (≈30 daily backups retained) — consequential (it will DELETE older backup
    objects once applied), so 30d is a safe conservative default; justify the chosen number in the PLAN.
  - An **AbortIncompleteMultipartUpload** rule (DaysAfterInitiation, e.g. 7) — S3-02.
- **Apply mechanism (S3-01):** a script (e.g. `scripts/apply-s3-lifecycle.sh`) that applies the JSON via
  `aws s3api put-bucket-lifecycle-configuration --endpoint-url … --bucket … --lifecycle-configuration file://config/s3/backups-lifecycle.json`,
  run as an in-cluster Job (creds from `server-2-runtime`). It should GET the current config first and warn if
  it would overwrite an existing one. Idempotent.
- **Empirical proof (S3-03) — design SAFE, default to operator-gated:** Timeweb S3 lifecycle parity is MEDIUM
  confidence. The proof has two parts:
  1. **API support probe (safe, can be read-mostly):** `aws s3api get-bucket-lifecycle-configuration` returns the
     policy or `NoSuchLifecycleConfiguration` (→ API implemented) vs `NotImplemented` (→ unsupported). After apply,
     a PUT-then-GET round-trip of the lifecycle config proves Timeweb accepts and persists it.
  2. **Observed object expiry:** put a tiny TEST object under an ISOLATED test prefix (e.g. `s3-lifecycle-probe/`),
     apply a short-expiry rule on THAT prefix, and read the object's `x-amz-expiration` header (via
     `aws s3api head-object`) which reports the computed expiry date — this is observable immediately and proves the
     rule is recognized/applied. Actual deletion is async (~24h+), so full deletion observation is a longer-running
     operator check. The probe MUST use an isolated test prefix and clean up after itself; it must NOT touch
     `backups/postgres/` real objects.
  - **CAUTION / operator gate:** applying the real expiration policy to `backups/postgres/` is a consequential,
    retention-affecting change to the production backup bucket. Per project risk policy this live apply is
    operator-run (the script makes it one command), not done blind. Provide a runbook + record evidence.
- **Offline validation:** add a `validate-staging.py` (or a dedicated validator) check that asserts
  `config/s3/backups-lifecycle.json` parses, has an Expiration rule on `backups/postgres/` and an
  AbortIncompleteMultipartUpload rule (S3-01, S3-02 regression guard). Keep stdlib-only (json).
- **Docs:** add an S3 retention/lifecycle runbook (e.g. in `docs/backup-restore.md` or a new `docs/s3-lifecycle.md`)
  covering apply, the empirical proof procedure, and the async-expiry caveat.
</decisions>

<code_context>
## Existing Code Insights
- `k8s/staging/60-postgres-backup.yaml` — S3 endpoint/secret/prefix wiring to mirror for any lifecycle Job.
- `scripts/backup-postgres-now.sh` — the `kubectl create job --from=cronjob` in-cluster-creds pattern + log-parsing style.
- `scripts/validate-staging.py` / `scripts/validate-edge.py` — stdlib-only validators to extend or mirror.
- AGENTS.md — Kubernetes safety + manifest conventions + script style (`#!/usr/bin/env bash`, `set -euo pipefail`, required() env checks, exit 64).
</code_context>

<specifics>
## Specific Ideas
- Real retention window is conservative (30d) and clearly documented; the empirical PROBE uses a short window on
  an isolated test prefix only.
- Lifecycle apply + probe keep S3 creds in-cluster (Job + secret), never on disk or in logs.
</specifics>

<deferred>
## Deferred Ideas
- S3-04: distinct shorter expiration windows for replay/ and artifact/ prefixes — deferred to v2.x.
- Full async-deletion observation (objects actually removed ~24h+ after expiry) is a longer-running operator check.
</deferred>
