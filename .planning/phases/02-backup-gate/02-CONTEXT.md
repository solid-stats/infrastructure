# Phase 2: Backup Gate - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 2 establishes a verified PostgreSQL backup point before any controlled
full ingest run begins. It covers the nightly backup CronJob, the manual
one-off backup command, S3 object evidence for dump/list/manifest uploads, and
operator-facing gate documentation. It does not execute the full ingest run,
does not enable `replays-fetcher`, and does not require production cutover or
automated restore-drill validation.

</domain>

<decisions>
## Implementation Decisions

### Backup Gate Evidence
- A valid backup point is a manual Job created from `cronjob/postgres-backup`
  that completes and logs `backup_id`, `dump_object`, and `dump_size_bytes`.
- The backup Job itself must run `pg_restore --list` successfully before upload,
  and upload dump, restore-list output, and manifest metadata to S3 under
  `backups/postgres/<backup-id>/`.
- S3 evidence should be checked with object listing or backup logs for the dump,
  `.list`, and `manifest.json`; do not write secret values into docs or
  planning artifacts.
- A repo-visible gate file or runbook section should record the latest verified
  `backup_id`, checklist status, and operator/timestamp before Phase 4 full-run
  commands are allowed.

### Restore and Storage Safety
- Phase 2 requires restore-list validation and clear isolated restore-drill
  instructions; a full restore drill can remain manual unless cheap and safe in
  the current cluster.
- PostgreSQL and RabbitMQ PVC changes must be avoided unless explicitly
  documented and verified; backup-related changes should not mutate durable
  database or broker storage.
- Backup verification should prove storage prefixes and object names without
  exposing S3 credentials.

### Operational Scope
- Keep `replays-fetcher` suspended.
- Keep backup scheduling under `postgres-backup` with `concurrencyPolicy:
  Forbid`.
- Prefer repository-local scripts and standard shell/Python tooling over adding
  a package manager or Helm/Kustomize layer.

### the agent's Discretion
Implementation details are at the agent's discretion as long as they preserve
the backup-before-full-run safety gate and avoid secret leakage.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `k8s/staging/60-postgres-backup.yaml` already defines a PostgreSQL custom
  dump backup CronJob that runs `pg_dump`, `pg_restore --list`, and uploads a
  dump, list, and manifest to S3.
- `scripts/backup-postgres-now.sh` already creates a one-off Job from the
  CronJob, waits for completion, and prints logs on success/failure.
- `docs/backup-restore.md` already documents backup schedule, manual backup,
  restore-list validation, and isolated restore drill steps.
- `scripts/validate-staging.py` already checks staging manifest structure and
  workload safety.

### Established Patterns
- Bash scripts use `set -euo pipefail`, explicit environment defaults, and
  direct `kubectl` commands.
- Manifests are plain YAML under `k8s/staging/` with numeric apply ordering.
- Secrets are read from Kubernetes Secrets and GitHub environment secrets; no
  secret values belong in git or planning docs.

### Integration Points
- The backup CronJob uses `server-2-runtime` S3 keys and `postgres-auth` for the
  database password.
- Phase 4 full-run work must consult the backup gate before starting ingest.
- Live verification can run over SSH against `deploy@89.223.124.200` with the
  staging deploy key when available.

</code_context>

<specifics>
## Specific Ideas

Add a backup gate artifact or documented checklist that records the latest
verified backup id, object paths, restore-list status, and whether full-run is
still blocked. Strengthen the manual backup script and docs so the operator can
create the Job, wait for it, and check S3 evidence without guessing.

</specifics>

<deferred>
## Deferred Ideas

- Phase 4 starts and monitors the controlled full run after this backup gate is
  satisfied.
- v2 can automate restore-drill validation beyond the documented manual path.
- S3 lifecycle/retention policy enforcement remains deferred to v2.

</deferred>
