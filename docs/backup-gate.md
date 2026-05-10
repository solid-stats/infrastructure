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

Status: pending

| Field | Value |
|-------|-------|
| Backup ID | pending |
| Dump object | pending |
| Dump size bytes | pending |
| Verified at | pending |
| Verified by | pending |
| Evidence | pending |

## Full-run remains blocked

Full-run remains blocked until the latest verified backup section is updated
with a successful backup Job result.
