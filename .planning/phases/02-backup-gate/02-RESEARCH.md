# Phase 2: Backup Gate - Research

## Findings

`k8s/staging/60-postgres-backup.yaml` already performs the core backup work:
`pg_dump --format=custom`, `pg_restore --list`, and S3 uploads for dump, list,
and manifest under `backups/postgres/<backup-id>/`.

`scripts/backup-postgres-now.sh` can create a one-off Job from the CronJob and
wait for completion, but it does not parse or persist gate evidence. The
operator needs a visible record that a backup point exists before Phase 4 can
start a full ingest.

## Validation Architecture

Phase 2 should verify:

- `python3 scripts/validate-staging.py`
- `bash -n scripts/backup-postgres-now.sh`
- manual Job completion from `cronjob/postgres-backup`
- backup logs include `backup_id=`, `dump_object=`, and `dump_size_bytes=`
- gate documentation records the verified backup id and states full-run remains
  blocked unless the gate is current

## Research Complete
