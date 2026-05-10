# Backup Gate

The backup gate blocks any controlled full-run until a current PostgreSQL
backup point is verified.

## Gate Checklist

- [ ] A one-off Job was created from `cronjob/postgres-backup`.
- [ ] The Job completed successfully.
- [ ] Job logs include `backup_id=`, `dump_object=`, and `dump_size_bytes=`.
- [ ] The Job ran `pg_restore --list` before upload.
- [ ] S3 contains the dump, restore-list output, and manifest under
  `backups/postgres/<backup-id>/`.

## Latest verified backup

Status: verified

| Field | Value |
|-------|-------|
| Backup ID | `20260510T073635Z` |
| Dump object | `s3://sg-replays/backups/postgres/20260510T073635Z/solid_stats.dump` |
| Restore-list object | `s3://sg-replays/backups/postgres/20260510T073635Z/solid_stats.dump.list` |
| Manifest object | `s3://sg-replays/backups/postgres/20260510T073635Z/manifest.json` |
| Dump size bytes | `61286` |
| Verified at | `2026-05-10T07:36:35Z` |
| Verified by | `postgres-backup-manual-20260510073632` |
| Evidence | Job completed; logs emitted backup id, dump object, list object, manifest object, and dump size. |

## Full-run remains blocked

Full-run may proceed only while this latest verified backup remains acceptable
for the planned ingest window.
