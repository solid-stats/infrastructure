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

Record the result in `docs/backup-gate.md`. Full-run work must remain blocked
until that gate records a successful backup Job and restore-list validation.

## Validate a Backup Object

Download the dump and list it:

```bash
aws --endpoint-url=https://s3.twcstorage.ru \
  s3 cp s3://<bucket>/backups/postgres/<backup-id>/solid_stats.dump ./solid_stats.dump

pg_restore --list ./solid_stats.dump >/tmp/solid_stats.dump.list
```

The command must exit `0`.

## Restore Drill

The restore drill is an automated Kubernetes Job that downloads the latest S3 backup, restores
it into an ephemeral scratch PostgreSQL instance (never the live `postgres-0` pod or
`postgres-data` PVC), runs sanity checks, and tears down — all in one command.

### Run the drill

From a machine with `kubectl` access to the cluster (WireGuard tunnel must be up):

```bash
K8S_NAMESPACE=solid-stats-staging bash scripts/restore-drill.sh
```

The script:
1. Deletes any prior `restore-drill` Job (idempotent).
2. Applies `k8s/staging/restore-drill/70-restore-drill.yaml`.
3. Waits up to 900 s for the Job to complete.
4. Prints the full Job logs and extracts the evidence line.
5. Deletes the Job object (the pod self-cleans via `ttlSecondsAfterFinished: 3600`).

### Expected output

```text
backup_id=20260613T060000Z
DRILL_RESULT=PASS backup_id=20260613T060000Z table_count=12 total_rows=48231 duration_s=73
=== Restore Drill Evidence ===
DRILL_RESULT=PASS backup_id=20260613T060000Z table_count=12 total_rows=48231 duration_s=73
RESTORE DRILL PASSED
```

A `DRILL_RESULT=FAIL` line means one or more sanity assertions failed (table count < 5,
total row count = 0, or empty dump list). The Job exits non-zero and the script exits 1.
Check `kubectl -n solid-stats-staging logs job/restore-drill` for the `FAIL:` lines.

### What the drill does NOT do

- It does **not** connect to the live `postgres` Service. The drill pod uses `PGHOST=localhost`
  and refuses to run if it detects the live Service host. The scratch postgres runs entirely on
  an `emptyDir` volume, isolated from `postgres-data`.
- It does **not** write to S3. S3 credentials are read-only for backup retrieval only.
- It does **not** auto-schedule. The manifest lives in `k8s/staging/restore-drill/` (a
  subdirectory) so the CD apply glob (`find k8s/staging -maxdepth 1 -name '*.yaml'`) never
  matches it. Drill manifests at depth-1 trigger a CI failure via `scripts/validate-staging.py`.

### Recommended cadence

Run the drill:
- Before any production cutover (Phase 11 gate).
- After restoring a manual backup to confirm the backup file is valid.
- Monthly as a recoverability confidence check.

Record the `DRILL_RESULT=PASS` evidence line (backup_id, table_count, total_rows, duration_s)
in the operations log when using the drill as a cutover gate.

### Live drill evidence (operator-captured)

<!-- PLACEHOLDER: To be filled by the operator after running the live drill on the staging cluster.
     Run: K8S_NAMESPACE=solid-stats-staging bash scripts/restore-drill.sh
     Paste the DRILL_RESULT= line here and confirm postgres-0 is untouched.

Example format:
  DRILL_RESULT=PASS backup_id=<timestamp> table_count=<n> total_rows=<n> duration_s=<n>
  Date run: <YYYY-MM-DD>
  Operator: <name>
-->

### Scheduled drill (future)

Automated scheduling and alerting (DRILL-05) are deferred to v2.x. The drill is on-demand only
in this version.
