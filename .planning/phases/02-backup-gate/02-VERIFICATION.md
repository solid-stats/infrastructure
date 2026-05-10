---
phase: "02"
status: passed
verified_at: 2026-05-10
---

# Phase 02 Verification - Backup Gate

## Status

status: passed

## Evidence

- `python3 scripts/validate-staging.py` passed.
- `bash -n scripts/backup-postgres-now.sh` passed.
- Applied updated `postgres-backup` CronJob to staging.
- Created and waited for live Job `postgres-backup-manual-20260510073632`.
- Job completed successfully.
- Job logs emitted:
  - `backup_id=20260510T073635Z`
  - `dump_object=s3://sg-replays/backups/postgres/20260510T073635Z/solid_stats.dump`
  - `list_object=s3://sg-replays/backups/postgres/20260510T073635Z/solid_stats.dump.list`
  - `manifest_object=s3://sg-replays/backups/postgres/20260510T073635Z/manifest.json`
  - `dump_size_bytes=61286`

## Success Criteria Review

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Nightly PostgreSQL backups write custom-format dumps to Timeweb S3 under `backups/postgres/`. | passed | CronJob remains scheduled at `0 6 * * *`; live manual Job from the CronJob wrote under `backups/postgres/20260510T073635Z/`. |
| Operator can launch a one-off backup Job from the CronJob and wait for it to complete. | passed | Job `postgres-backup-manual-20260510073632` was created from `cronjob/postgres-backup` and reached `condition=complete`. |
| Each backup upload includes a dump, `pg_restore --list` output, and manifest metadata in S3. | passed | Job logs emitted dump, list, and manifest object paths after successful upload commands. |
| The backup gate blocks full ingest until the backup Job completed, S3 upload succeeded, and `pg_restore --list` succeeded. | passed | `docs/backup-gate.md` records the verified backup point and gate checklist. |
| Operator can verify backup-related storage and PVC changes without risking PostgreSQL or RabbitMQ persistent state. | passed | Phase 2 changed backup CronJob/script/docs only; no PostgreSQL or RabbitMQ PVC spec changes were made. |

## Gaps

No Phase 2 gaps remain.
