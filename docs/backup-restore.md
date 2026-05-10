# PostgreSQL Backup and Restore

This runbook covers the staging k3s PostgreSQL database. Raw replay files and
parser artifacts live in S3-compatible object storage. The PostgreSQL backup
protects database metadata, ingest state, parser job state, statistics, and
request/audit data.

## Backup Schedule

The `postgres-backup` CronJob runs daily at `06:00` in `Europe/Moscow`.

Each run writes three objects to the configured S3 bucket:

- `backups/postgres/<backup-id>/solid_stats.dump`
- `backups/postgres/<backup-id>/solid_stats.dump.list`
- `backups/postgres/<backup-id>/manifest.json`

The dump format is PostgreSQL custom format and is intended for `pg_restore`.

## Manual Backup

Run from a machine with `kubectl` access to the cluster:

```bash
K8S_NAMESPACE=solid-stats-staging ./scripts/backup-postgres-now.sh
```

Expected output includes:

```text
backup_id=<timestamp>
dump_object=s3://<bucket>/backups/postgres/<timestamp>/solid_stats.dump
dump_size_bytes=<bytes>
```

## Validate a Backup Object

Download the dump and list it:

```bash
aws --endpoint-url=https://s3.twcstorage.ru \
  s3 cp s3://<bucket>/backups/postgres/<backup-id>/solid_stats.dump ./solid_stats.dump

pg_restore --list ./solid_stats.dump >/tmp/solid_stats.dump.list
```

The command must exit `0`.

## Restore Drill

Do not restore over the active staging database during a drill. Restore into an
isolated database first.

1. Create an isolated database in the running PostgreSQL pod:

   ```bash
   kubectl -n solid-stats-staging exec postgres-0 -- \
     createdb --username=solid solid_stats_restore_drill
   ```

2. Copy the dump into the pod:

   ```bash
   kubectl -n solid-stats-staging cp ./solid_stats.dump \
     postgres-0:/tmp/solid_stats.dump
   ```

3. Restore into the drill database:

   ```bash
   kubectl -n solid-stats-staging exec postgres-0 -- \
     pg_restore --clean --if-exists --no-owner --no-privileges \
       --username=solid --dbname=solid_stats_restore_drill \
       /tmp/solid_stats.dump
   ```

4. Run smoke checks:

   ```bash
   kubectl -n solid-stats-staging exec postgres-0 -- \
     psql --username=solid --dbname=solid_stats_restore_drill \
       --command='select current_database();'
   ```

5. Drop the drill database after validation:

   ```bash
   kubectl -n solid-stats-staging exec postgres-0 -- \
     dropdb --username=solid solid_stats_restore_drill
   ```

Record the backup id, dump size, operator, timestamp, and validation result in
the operations log before relying on the backup for a full ingest run.
