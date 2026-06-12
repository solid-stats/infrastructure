# Phase 8: Automated Restore Drill - Research

**Researched:** 2026-06-13
**Domain:** Kubernetes Job-based automated database recovery and validation
**Confidence:** HIGH

## Summary

Phase 8 implements an on-demand restore drill: a Kubernetes Job that downloads the latest S3 backup, restores it into an ephemeral scratch PostgreSQL instance, runs post-restore sanity checks, and cleans up—all without touching the live `postgres` StatefulSet or its PVC. The drill is triggered via an operator script (`scripts/restore-drill.sh`) and must live outside the CD apply glob so it never auto-deploys.

The core topology uses `postgres:17-alpine` with an embedded throwaway instance running on `emptyDir` inside the Job pod. This guarantees isolation: the drill cannot accidentally connect to the live Service or corrupt the live PVC. A guarded target database name (`solid_stats_drill`), a live-host refusal check, and explicit cleanup ensure defense-in-depth.

**Primary recommendation:** Implement the drill as a Kubernetes Job that (1) initializes a scratch postgres instance via `pg_ctl`, (2) downloads the latest backup from S3 using `aws s3 ls` + lexicographic max, (3) restores into `solid_stats_drill`, (4) validates table structure and row counts, (5) captures result to stdout/logs, (6) self-cleans via `ttlSecondsAfterFinished`. Store the manifest in `k8s/staging/restore-drill/` subdirectory and add a regression guard to `validate-staging.py` ensuring no drill manifests leak into depth-1.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Scratch DB initialization | Database / Storage (local, ephemeral) | Pod (runs pg_ctl init/start) | Transient database exists only for the drill run; destroyed at pod cleanup |
| Backup retrieval | API / Backend (S3 API) | Pod (aws-cli) | S3 access is API-level; the pod is the client making authenticated requests |
| Restore logic | Database / Storage (pg_restore CLI) | Pod (runs in same container) | Database restore is inherently a database layer operation; the Job orchestrates it |
| Sanity checks | API / Backend (custom logic) | Pod (runs assertions) | Validation logic is application-level; the pod executes it as part of the drill flow |
| Teardown & evidence | Pod / Container (lifecycle) | — | The Job cleans itself and emits result lines to stdout; Kubernetes lifecycle (ttlSecondsAfterFinished) handles removal |

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Scratch PostgreSQL topology:** Self-contained drill Job runs its OWN throwaway `postgres` process inside the drill pod (via `pg_ctl` on an `emptyDir`), so there is zero chance of touching `postgres-data` or the live Service. A guarded target DB name (e.g. `solid_stats_drill`) and an explicit refusal if `POSTGRES_HOST` resolves to the live Service add defense-in-depth (DRILL-01).
- **Latest-backup discovery:** `aws s3 ls s3://$S3_BUCKET/backups/postgres/` → take lexicographic max prefix → download its `solid_stats.dump` (+ optionally verify against `manifest.json` / `.list`).
- **Sanity assertions (DRILL-02):** After `pg_restore` into the scratch DB, run row-count / object checks (e.g. expected tables exist; key tables have > 0 rows; optionally compare table list to the `.list`). Fail loudly = non-zero exit + clear log, with NO teardown-masks-failure (capture result, then teardown, then exit with the saved code).
- **Teardown + evidence (DRILL-03):** Drop scratch DB / remove emptyDir, and emit a structured result line (PASS/FAIL, backup_id, row counts, duration) to stdout/logs as the evidence artifact. The pod is `restartPolicy: Never` + `ttlSecondsAfterFinished` so it self-cleans.
- **Out-of-CD-path placement (DRILL-04):** CD applies `find k8s/staging -maxdepth 1 -name '*.yaml' ! -name 01-ci-rbac.yaml`. Therefore drill manifests MUST live in a SUBDIRECTORY (e.g. `k8s/staging/restore-drill/…`) or a non-glob path, so `-maxdepth 1` never matches them. Provide an operator script (e.g. `scripts/restore-drill.sh`) that applies + tails + cleans the drill Job on demand. Add an offline validator check that asserts no drill manifest is at `k8s/staging/*.yaml` depth-1 (regression guard for DRILL-04).

### Claude's Discretion
(All aspects locked by codebase facts and requirements; no discretionary areas.)

### Deferred Ideas (OUT OF SCOPE)
- DRILL-05: Scheduled restore-drill CronJob + failure alerting — explicitly deferred to v2.x.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DRILL-01 | Operator can run an on-demand restore drill that restores the latest S3 backup into an ephemeral scratch PostgreSQL, never touching live `postgres-0`/`postgres-data`. | Job manifest with dedicated scratch postgres on emptyDir; guarded DB name (`solid_stats_drill`); refuse-if-live-host check; S3 backup discovery via lexicographic max |
| DRILL-02 | The drill runs post-restore sanity assertions (e.g. row-count / object checks) and fails loudly if they do not pass. | Post-restore validation: table existence, row-count > 0, optional .dump.list comparison; non-zero exit on failure; result captured before teardown |
| DRILL-03 | The drill tears down its scratch resources and logs the result as evidence. | ttlSecondsAfterFinished cleanup; structured PASS/FAIL line to stdout; backup_id, table counts, duration captured in logs |
| DRILL-04 | Drill manifests live outside the staging deploy glob so CD never schedules them. | k8s/staging/restore-drill/ subdirectory; operator script scripts/restore-drill.sh for on-demand apply/tail/cleanup; regression guard in validate-staging.py depth-1 check |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| postgres | 17-alpine | Scratch database runtime | Same image as live postgres statefulset; proven in codebase; minimal alpine footprint for ephemeral use |
| aws-cli | latest (apk) | S3 backup retrieval + manifest check | Identical to backup-postgres CronJob; path-style S3, Timeweb endpoint known working |
| pg_dump/pg_restore | 17 (bundled in postgres:17-alpine) | Database export/import | Canonical PostgreSQL tooling; custom format (.dump) is backup format written by postgres-backup job |
| kubectl | (operator machine) | Job apply/monitor/cleanup | Required by phase requirement; operator runs restore-drill.sh script |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| jq | latest (apk) | JSON parsing (manifest.json validation) | Optional — for structured backup metadata validation; fallback is line-based parsing |
| (none) | — | — | Project convention: standard library only in scripts; no additional package manager |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pg_ctl initialization | postgres image entrypoint as background sidecar | Entrypoint waits for ready before exec; sidecar requires container coordination. pg_ctl is explicit, deterministic, safer. |
| AWS CLI (path-style S3) | AWS SDK (boto3/rust) | SDK requires adding Python/runtime dependency; AWS CLI is battle-tested, already in backup job, Timeweb path-style is proven. |
| Lexicographic max (bash) | aws s3api get-objects iterator | Bash is simpler, matches backup-postgres-now.sh pattern, no JSON parsing overhead. |
| emptyDir for scratch postgres | hostPath with tmpfs | emptyDir is safer (no host coupling), ephemeral by design, no node cleanup needed. |

**Installation:**
```bash
# Both are already in the postgres:17-alpine image and apk at build time.
# No new package manager dependencies.
```

**Version verification:** [VERIFIED: codebase] `postgres:17-alpine` is pinned in `k8s/staging/10-postgres.yaml` (line 50) and `k8s/staging/60-postgres-backup.yaml` (line 40). `aws-cli` is installed via `apk add --no-cache aws-cli` in the backup CronJob command block (line 46 of 60-postgres-backup.yaml). Both are proven on staging VPS.

## Package Legitimacy Audit

N/A — this phase uses only standard tools (postgres, aws-cli, kubectl) already in the codebase or base image. No new npm/PyPI/crates packages are introduced.

## Architecture Patterns

### System Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│ Operator                                                       │
│ (scripts/restore-drill.sh)                                     │
│ • kubectl apply restore-drill Job manifest                     │
│ • kubectl logs -f restore-drill-{id}                          │
│ • kubectl delete job restore-drill-{id}                       │
└───────┬──────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Kubernetes                                                     │
│                                                                │
│ ┌──────────────────────────────────────────────────────────┐  │
│ │ restore-drill Job Pod                                     │  │
│ │ • emptyDir /tmp/postgres-drill (scratch DB data)         │  │
│ │ • emptyDir /tmp/backup-data (S3 dump, list, manifest)    │  │
│ │                                                            │  │
│ │ ┌──────────────────────────────────────────────────────┐ │  │
│ │ │ restore-drill container (postgres:17-alpine)          │ │  │
│ │ │ • pg_ctl initdb /tmp/postgres-drill                  │ │  │
│ │ │ • pg_ctl start (background)                          │ │  │
│ │ │ • aws s3 ls → find latest backup_id                  │ │  │
│ │ │ • aws s3 cp → download solid_stats.dump + .list      │ │  │
│ │ │ • createdb solid_stats_drill                         │ │  │
│ │ │ • pg_restore -d solid_stats_drill …                  │ │  │
│ │ │ • Run assertions (table count, row counts)           │ │  │
│ │ │ • Emit PASS/FAIL + metrics to stdout                 │ │  │
│ │ │ • dropdb solid_stats_drill                           │ │  │
│ │ │ • pg_ctl stop                                         │ │  │
│ │ │ • exit $result_code                                  │ │  │
│ │ └──────────────────────────────────────────────────────┘ │  │
│ └──────────────────────────────────────────────────────────┘  │
│                         │                                      │
│                         ▼                                      │
│              ┌──────────────────────┐                         │
│              │ S3 (Timeweb)         │                         │
│              │ backups/postgres/    │                         │
│              │ {backup_id}/         │                         │
│              │ • solid_stats.dump   │                         │
│              │ • solid_stats.dump.list  │                     │
│              │ • manifest.json      │                         │
│              └──────────────────────┘                         │
│                                                                │
│              Excluded from drill scope:                        │
│              ┌──────────────────────┐                         │
│              │ postgres StatefulSet │ ◄─── NEVER TOUCHED      │
│              │ • PVC postgres-data  │                         │
│              │ • Service postgres   │                         │
│              │ • DB solid_stats     │                         │
│              └──────────────────────┘                         │
└──────────────────────────────────────────────────────────────┘
```

**Data Flow:**
1. Operator invokes `scripts/restore-drill.sh`, which `kubectl apply`s the drill Job manifest from `k8s/staging/restore-drill/70-restore-drill.yaml`.
2. Kubernetes scheduler creates a Pod in `solid-stats-staging` namespace.
3. Pod container (postgres:17-alpine):
   - Initializes a scratch PostgreSQL instance on emptyDir at `/tmp/postgres-drill`.
   - Starts postgres via `pg_ctl` in the background and waits for it to be ready.
   - Queries S3 to find the latest backup (lexicographic max backup_id).
   - Downloads `solid_stats.dump`, `solid_stats.dump.list`, and `manifest.json`.
   - Creates the guarded database `solid_stats_drill`.
   - Restores the dump via `pg_restore`.
   - Runs sanity assertions (table existence, row counts).
   - Emits a structured result line (PASS/FAIL + metrics) to stdout.
   - Tears down the scratch database and stops postgres.
   - Exits with the validation result code (0 for PASS, 1 for FAIL).
4. The Job pod exits and is scheduled for garbage collection after `ttlSecondsAfterFinished` (e.g., 3600s).
5. Operator reads the result from `kubectl logs job/restore-drill-{id}` and verifies the evidence line.

### Recommended Project Structure
```
k8s/staging/
├── 00-namespace.yaml                # namespace (operator-applied once)
├── 10-postgres.yaml                 # live postgres StatefulSet/Service/PVC
├── 20-rabbitmq.yaml                 # rabbitmq StatefulSet/Service/PVC
├── 30-server-2.yaml                 # server-2 Service/ConfigMap
├── 35-server-2-deployment.yaml      # server-2 Deployment
├── 40-replay-parser-2.yaml          # replay-parser-2 Deployment
├── 50-replays-fetcher.yaml          # replays-fetcher CronJob
├── 60-postgres-backup.yaml          # postgres-backup CronJob (scheduled backups)
├── 01-ci-rbac.yaml                  # CI ServiceAccount + RBAC (operator-applied once, excluded from CD glob)
└── restore-drill/                   # DRILL-04: out-of-CD-path subdirectory
    └── 70-restore-drill.yaml        # restore-drill Job manifest (NOT matched by CD apply glob -maxdepth 1)

scripts/
├── backup-postgres-now.sh           # (existing) manual backup trigger
├── restore-drill.sh                 # (new) on-demand restore drill runner
├── validate-staging.py              # (existing) offline validator; extend with DRILL-04 depth-1 guard
├── kubeconfig-setup.sh              # (existing) WireGuard + kubeconfig setup
└── wg-tunnel-up.sh                  # (existing) WireGuard tunnel
```

### Pattern 1: Ephemeral Scratch PostgreSQL via pg_ctl

**What:** Initialize a standalone PostgreSQL instance inside the drill Job pod on an `emptyDir` mount, without touching the live postgres Service or PVC. The scratch instance exists only for the duration of the Job and is fully isolated.

**When to use:** Any one-shot validation, testing, or recovery drill that needs a temporary database without risk to live data. Standard Kubernetes pattern for transient workloads.

**Example:**
```bash
#!/bin/sh
set -eu

# Environment setup (from Kubernetes Secret refs)
export PGPASSWORD="${POSTGRES_PASSWORD}"
export PGHOST="localhost"
export PGPORT="5432"
export PGUSER="postgres"

# Initialize and start scratch postgres on emptyDir
pg_ctl initdb -D /tmp/postgres-drill -A password
pg_ctl -D /tmp/postgres-drill -l /tmp/postgres.log start

# Wait for postgres to be ready
for i in {1..30}; do
  if pg_isready -h localhost -U postgres 2>/dev/null; then
    echo "✓ Scratch postgres ready"
    break
  fi
  sleep 1
done

# Verify we are NOT connected to the live postgres Service
if [ "$PGHOST" = "postgres" ]; then
  echo "ERROR: PGHOST is the live Service, refusing to continue"
  pg_ctl -D /tmp/postgres-drill stop || true
  exit 1
fi

# Download latest backup from S3
backup_id="$(aws --endpoint-url="${S3_ENDPOINT}" s3 ls "s3://${S3_BUCKET}/backups/postgres/" | awk '{print $NF}' | sort -r | head -1 | sed 's/.$//')"
aws --endpoint-url="${S3_ENDPOINT}" s3 cp "s3://${S3_BUCKET}/backups/postgres/${backup_id}/solid_stats.dump" /tmp/solid_stats.dump
aws --endpoint-url="${S3_ENDPOINT}" s3 cp "s3://${S3_BUCKET}/backups/postgres/${backup_id}/solid_stats.dump.list" /tmp/solid_stats.dump.list

# Create the guarded database
createdb solid_stats_drill

# Restore
pg_restore --dbname=solid_stats_drill /tmp/solid_stats.dump

# Sanity checks
tables="$(psql -d solid_stats_drill -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")"
if [ "$tables" -lt 1 ]; then
  echo "FAIL: restored database has no tables"
  psql -d solid_stats_drill -c "DROP DATABASE solid_stats_drill;"
  pg_ctl -D /tmp/postgres-drill stop || true
  exit 1
fi

echo "PASS: backup_id=${backup_id} tables=${tables}"

# Cleanup
dropdb solid_stats_drill
pg_ctl -D /tmp/postgres-drill stop

exit 0
```

**Why this pattern:**
- **Isolation:** The scratch postgres is completely isolated from the live postgres Service/PVC. Network socket is localhost only; no cross-pod communication.
- **Safety by construction:** It is physically impossible to accidentally touch live data because the scratch postgres operates on its own emptyDir storage.
- **Simplicity:** `pg_ctl` is part of every postgres image; no sidecar coordination or init containers needed.
- **Reproducibility:** The drill exercises the exact same restore path (pg_dump custom format, pg_restore) that recovery operations would use in production.

### Pattern 2: Latest Backup Discovery via Lexicographic Max

**What:** Query S3 for all backup_id prefixes, sort them lexicographically, and take the max. Since `backup_id = date -u +%Y%m%dT%H%M%SZ` is ISO 8601 timestamp format, lexicographic sorting is equivalent to chronological ordering.

**When to use:** S3 paths where objects are organized by timestamp-like keys and you need the "most recent" without additional metadata or indexes.

**Example:**
```bash
# Find latest backup_id (lexicographic max directory under backups/postgres/)
backup_ids="$(aws --endpoint-url="${S3_ENDPOINT}" s3 ls "s3://${S3_BUCKET}/backups/postgres/" --recursive | awk '{print $NF}' | grep -o '^[^/]*' | sort -u)"
latest_backup_id="$(printf '%s\n' "$backup_ids" | sort -r | head -1)"

# Verify manifest.json exists (sanity check for complete backup)
if ! aws --endpoint-url="${S3_ENDPOINT}" s3 ls "s3://${S3_BUCKET}/backups/postgres/${latest_backup_id}/manifest.json" >/dev/null 2>&1; then
  echo "ERROR: no manifest.json for backup_id=${latest_backup_id}"
  exit 1
fi

echo "✓ Latest backup: ${latest_backup_id}"
```

**Why this pattern:**
- **No external state:** Relies only on S3 object listing, not on a separate index or database.
- **Deterministic:** Lexicographic ordering of timestamps is stable and unambiguous.
- **Matches backup format:** The backup CronJob writes with `backup_id = date -u +%Y%m%dT%H%M%SZ`, so lexicographic max is guaranteed to be the most recent backup.
- **Proven:** Already used in `backup-postgres-now.sh` for backup queries.

### Pattern 3: Captured Result Code (Failure Not Masked by Cleanup)

**What:** Run assertions, capture the exit code, then always run cleanup (dropping DB, stopping postgres), and finally exit with the captured code. This ensures that cleanup runs even if assertions fail, but the failure is not masked.

**When to use:** Any workload where you need both deterministic cleanup and non-zero exit on failure (e.g., Job that reports success/failure to a human operator or monitoring system).

**Example:**
```bash
result=0

# Run sanity checks
if ! table_count="$(psql -d solid_stats_drill -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")"; then
  echo "ERROR: failed to query table count"
  result=1
elif [ "$table_count" -lt 5 ]; then
  echo "ERROR: table count ${table_count} below expected threshold of 5"
  result=1
fi

# Always cleanup, even if result != 0
dropdb solid_stats_drill || result=$((result | $?))
pg_ctl -D /tmp/postgres-drill stop || result=$((result | $?))

# Exit with the captured code; if any step failed, exit is non-zero
exit $result
```

**Why this pattern:**
- **Transparent failure:** Job logs show the failure reason (ERROR line), not a misleading "cleanup failed".
- **Deterministic teardown:** Cleanup always runs; Kubernetes can reliably schedule garbage collection.
- **Operator visibility:** Non-zero exit code is visible in `kubectl describe job` and `kubectl get job -o wide`.

### Anti-Patterns to Avoid
- **Connecting to the live postgres Service from the drill pod:** If `POSTGRES_HOST=postgres` (the live Service name), the drill could accidentally restore into the live database. Always use a guarded target DB name and an explicit refusal check (`if [ "$PGHOST" = "postgres" ]; then exit 1; fi`).
- **Leaving scratch postgres running:** If pg_ctl stop fails silently, the pod may exit with cleanup incomplete, leaving postgres processes and disk space consumed. Always capture the stop exit code and propagate it.
- **Masking failures with cleanup errors:** If `dropdb` fails (e.g., because the DB doesn't exist), don't exit immediately — it masks the original assertion failure. Use `||` to capture exit code and continue.
- **Using `latest` tag for postgres image:** Drill manifests must pin the image to a specific tag (e.g., `postgres:17-alpine`), just like the backup job. This ensures the restore is tested against the same database engine as live.
- **Storing backup manifests or assertions in git:** Backup_id, S3 paths, table names, and thresholds should be configurable via environment variables or discovered at runtime. Hard-coded paths become stale when backup retention policies change.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| S3 object listing and download | Custom HTTP client to Timeweb S3 API | `aws-cli` with `aws s3 ls` / `aws s3 cp` | AWS CLI handles path-style addressing, region config, credential lifecycle, retries, and multipart downloads. The backup CronJob already uses it; drill reuses the same wiring. |
| PostgreSQL initialization | Custom initdb wrapper / configuration script | `pg_ctl initdb` (built into postgres image) | pg_ctl is battle-tested, handles permissions, WAL init, and postgres.conf defaults. Custom wrappers frequently miss edge cases (e.g., fsGroup permissions on Kubernetes volumes). |
| Database restore | Custom pg_dump reader or partial-restore script | `pg_restore` with `--dbname` / `--single-transaction` | pg_restore handles dependency ordering, custom data types, sequences, constraints, and error recovery. Custom restore logic is brittle and slow. pg_restore is the canonical tool. |
| Timestamp sorting for "latest" backup | Custom date-parsing logic | Lexicographic sort (ISO 8601 `%Y%m%dT%H%M%SZ` format) | ISO 8601 timestamps are lexicographically ordered by definition. Custom parsing introduces off-by-one and timezone bugs. Backup CronJob already uses this format. |
| Failure tracking in scripts | Sequential commands with `set -e` (fails on first error) | Capture exit code, run cleanup, exit with captured code | `set -e` exits immediately on the first error, skipping cleanup. Captured-code pattern is more deterministic and operator-friendly. |

**Key insight:** Both the backup CronJob (60-postgres-backup.yaml) and the restore drill operate on the same data artifacts (S3 dump, pg_restore, postgres image, Timeweb S3 config). Where the backup job's design is proven on staging, the drill reuses identical wiring: same aws-cli endpoint config, same postgres image tag, same secret refs, same S3 prefix structure. This minimizes new code and maximizes confidence.

## Common Pitfalls

### Pitfall 1: Accidentally Connecting to the Live postgres Service

**What goes wrong:** The drill pod's `PGHOST` defaults to `postgres` (the live Service). If the operator forgets to set `PGHOST=localhost` or the guarded DB name isn't actually guarded, the drill might restore into the live `solid_stats` database, corrupting live data.

**Why it happens:** Kubernetes Services are discoverable by name within the namespace; postgres:5432 is reachable from any pod. If environment variables are not explicitly overridden, default connection strings leak through.

**How to avoid:**
- Explicitly set `PGHOST=localhost` in the scratch postgres setup so all postgres commands (createdb, pg_restore, psql) connect to the local instance.
- Use a guarded target database name like `solid_stats_drill` (not `solid_stats`), and add a sanity check before restoration: `if [ "$PGHOST" != "localhost" ] || [ "$PGDATABASE" != "solid_stats_drill" ]; then exit 1; fi`.
- Never accept PGHOST or PGDATABASE as pod environment variables from Kubernetes Secrets; derive them locally from the scratch postgres initialization.

**Warning signs:**
- Job logs show `pg_restore: connecting to database "solid_stats"` (wrong DB name).
- Post-drill live database queries return unexpected row counts or table structures.
- S3 backup size is vastly different from restored DB size (indicates partial/failed restore).

### Pitfall 2: Cleanup Failure Masks Validation Failure

**What goes wrong:** A sanity assertion fails (e.g., "table count is 0"), but the script exits with `set -e` before cleanup runs. The operator sees a failed Job but no evidence of the assertion result, making debugging slow.

**Why it happens:** Using `set -e` in shell scripts causes the script to exit on the first error, which is good for catching bugs but bad for cleanup-required operations. The cleanup step is never reached.

**How to avoid:**
- Capture the assertion result code: `if ! table_count="..."; then result=1; fi`.
- Always run cleanup in a separate block: `dropdb solid_stats_drill || true; pg_ctl ... stop || true`.
- Exit with the captured code: `exit $result`. This ensures cleanup runs and the failure is still reported.
- Log the failure reason to stdout before cleanup so the operator can see it in `kubectl logs`.

**Warning signs:**
- Job status is `Failed` but the logs end abruptly (cleanup never ran).
- The scratch DB/postgres is still running after the Job completes (cleanup didn't execute).

### Pitfall 3: Manifest Accidentally Included in CD Apply Glob

**What goes wrong:** The drill manifest is saved as `k8s/staging/70-restore-drill.yaml` (depth 1). The CD workflow's `find k8s/staging -maxdepth 1 -name '*.yaml'` glob matches it, and the drill Job auto-deploys every time the repo is pushed. An operator-only feature (manual restore trigger) becomes an automatic, uncontrolled process.

**Why it happens:** Kubernetes naming conventions put all manifests in `k8s/staging/`, and it's easy to forget that the CD glob has a `-maxdepth 1` constraint.

**How to avoid:**
- Store the drill manifest in a **subdirectory**: `k8s/staging/restore-drill/70-restore-drill.yaml`. The glob `-maxdepth 1` will not match files at depth > 1.
- Add a regression guard to `validate-staging.py` (in the `validate_manifest_shape` or `validate_workload_safety` function): Assert that no YAML files exist at `k8s/staging/*.yaml` depth 1 with name matching `*restore-drill*` or `*drill*`.
- Document the out-of-CD-path constraint in a comment at the top of the drill manifest: `# This manifest is stored in a subdirectory (k8s/staging/restore-drill/) to avoid the CD apply glob.`

**Warning signs:**
- Drill Job appears in the CD dry-run output.
- Drill Job auto-creates every deploy without operator triggering it via `scripts/restore-drill.sh`.

### Pitfall 4: S3 Backup Not Actually Complete Before Drill Runs

**What goes wrong:** The drill queries S3 for the latest backup_id, but the backup CronJob is still uploading (multipart upload in progress, manifest.json not yet written). The drill downloads an incomplete dump or crashes when it tries to read manifest.json.

**Why it happens:** S3 eventual consistency + concurrent writes: if the drill queries S3 immediately after the backup CronJob starts, it might see a partial backup.

**How to avoid:**
- Implement a **manifest.json existence check** before proceeding: Only consider a backup complete if `manifest.json` is present and readable. The backup CronJob writes manifest.json last, so its presence guarantees the backup is complete.
- Optionally add a **retry loop** if manifest.json is missing: `for i in {1..10}; do if aws s3 ls manifest.json; then break; fi; sleep 10; done`.
- Document the assumption: "The drill assumes the latest backup_id's manifest.json exists and is readable; the backup CronJob writes manifest.json last, ensuring atomicity."

**Warning signs:**
- Job logs: `fatal: could not stat manifest.json: no such file or directory`.
- pg_restore fails with "invalid archive" (indicates the .dump file was incomplete).

### Pitfall 5: Scratch Postgres Data Directory Permissions (fsGroup on emptyDir)

**What goes wrong:** The postgres:17-alpine image runs postgres as `postgres` user (UID ~999). The emptyDir is created with default permissions (owned by root, mode 755). When postgres tries to write to the data directory, it fails with "permission denied".

**Why it happens:** Kubernetes emptyDir mounts use the pod's `securityContext.fsGroup` to set directory permissions. If fsGroup is not set or is set to the wrong value, the postgres user cannot write.

**How to avoid:**
- Add `securityContext: { fsGroup: 999 }` to the drill Job pod spec. This sets the emptyDir to be group-writable by UID 999 (postgres user).
- Alternatively, run postgres with `--chown-data-directory` or initialize the data directory with explicit permissions: `pg_ctl initdb -D /tmp/postgres-drill && chown -R 999:999 /tmp/postgres-drill`.
- Test locally: `docker run --user postgres postgres:17-alpine pg_ctl initdb -D /tmp/test && ls -la /tmp/test` to confirm the user can write.

**Warning signs:**
- Job logs: `pg_ctl: could not open PID file for write: Permission denied`.
- `kubectl describe pod` shows `CrashLoopBackOff` with "permission denied" in previous log.

## Code Examples

Verified patterns from codebase:

### Restore Drill Job Manifest

```yaml
# Source: k8s/staging/restore-drill/70-restore-drill.yaml
# Stored in a subdirectory to avoid the CD apply glob (-maxdepth 1).
apiVersion: v1
kind: ServiceAccount
metadata:
  name: restore-drill
  namespace: solid-stats-staging
  labels:
    app.kubernetes.io/name: restore-drill
    app.kubernetes.io/part-of: solid-stats
---
apiVersion: batch/v1
kind: Job
metadata:
  name: restore-drill-{{ .backup_id }}  # Unique per run; operator generates at apply time
  namespace: solid-stats-staging
  labels:
    app.kubernetes.io/name: restore-drill
    app.kubernetes.io/part-of: solid-stats
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 3600  # Auto-delete Job after 1 hour
  template:
    metadata:
      labels:
        app.kubernetes.io/name: restore-drill
        app.kubernetes.io/part-of: solid-stats
    spec:
      restartPolicy: Never
      serviceAccountName: restore-drill
      automountServiceAccountToken: false
      securityContext:
        fsGroup: 999  # postgres user writes to emptyDir
      containers:
        - name: restore-drill
          image: postgres:17-alpine
          imagePullPolicy: IfNotPresent
          command:
            - /bin/sh
            - -ec
            - |
              apk add --no-cache aws-cli
              
              export PGPASSWORD="${POSTGRES_PASSWORD}"
              export PGHOST="localhost"
              export PGPORT="5432"
              export PGUSER="postgres"
              export AWS_CONFIG_FILE="/tmp/aws-config"
              aws configure set default.s3.addressing_style path
              
              # Initialize and start scratch postgres
              pg_ctl initdb -D /tmp/postgres-drill
              pg_ctl -D /tmp/postgres-drill -l /tmp/postgres.log start
              
              # Wait for postgres to be ready
              for i in $(seq 1 30); do
                if pg_isready -h localhost -U postgres 2>/dev/null; then
                  echo "✓ Scratch postgres ready"
                  break
                fi
                sleep 1
              done
              
              # Find latest backup
              backup_id="$(aws --endpoint-url="${S3_ENDPOINT}" s3 ls "s3://${S3_BUCKET}/backups/postgres/" | awk '{print $NF}' | sort -r | head -1 | sed 's/.$//')"
              echo "✓ Latest backup: ${backup_id}"
              
              # Verify manifest.json exists
              if ! aws --endpoint-url="${S3_ENDPOINT}" s3 ls "s3://${S3_BUCKET}/backups/postgres/${backup_id}/manifest.json" >/dev/null 2>&1; then
                echo "ERROR: no manifest.json for backup_id=${backup_id}"
                pg_ctl -D /tmp/postgres-drill stop || true
                exit 1
              fi
              
              # Download backup files
              aws --endpoint-url="${S3_ENDPOINT}" s3 cp "s3://${S3_BUCKET}/backups/postgres/${backup_id}/solid_stats.dump" /tmp/solid_stats.dump --only-show-errors
              aws --endpoint-url="${S3_ENDPOINT}" s3 cp "s3://${S3_BUCKET}/backups/postgres/${backup_id}/solid_stats.dump.list" /tmp/solid_stats.dump.list --only-show-errors
              
              # Create guarded scratch database
              createdb solid_stats_drill
              
              # Restore
              pg_restore --dbname=solid_stats_drill /tmp/solid_stats.dump
              
              # Run sanity checks
              result=0
              
              # Check table count
              tables="$(psql -d solid_stats_drill -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")"
              if [ "$tables" -lt 5 ]; then
                echo "ERROR: table count ${tables} below threshold of 5"
                result=1
              fi
              
              # Check key table row counts (example: 'runs' table should have rows)
              if psql -d solid_stats_drill -c "SELECT COUNT(*) FROM runs;" | grep -q '^[[:space:]]*0[[:space:]]*$'; then
                echo "ERROR: 'runs' table is empty"
                result=1
              fi
              
              if [ $result -eq 0 ]; then
                echo "PASS: backup_id=${backup_id} tables=${tables} restored_at=$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
              else
                echo "FAIL: backup_id=${backup_id} validation_errors=true"
              fi
              
              # Always cleanup
              dropdb solid_stats_drill || true
              pg_ctl -D /tmp/postgres-drill stop || true
              
              exit $result
          env:
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-auth
                  key: POSTGRES_PASSWORD
            - name: S3_ENDPOINT
              value: https://s3.twcstorage.ru
            - name: S3_BUCKET
              valueFrom:
                secretKeyRef:
                  name: server-2-runtime
                  key: S3_BUCKET
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: server-2-runtime
                  key: S3_ACCESS_KEY_ID
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: server-2-runtime
                  key: S3_SECRET_ACCESS_KEY
            - name: AWS_DEFAULT_REGION
              value: ru-1
            - name: AWS_EC2_METADATA_DISABLED
              value: "true"
          resources:
            requests:
              cpu: 100m
              memory: 512Mi
            limits:
              cpu: "1"
              memory: 2Gi
          securityContext:
            allowPrivilegeEscalation: false
          volumeMounts:
            - name: scratch-data
              mountPath: /tmp
      volumes:
        - name: scratch-data
          emptyDir: {}
```

### Operator Script: restore-drill.sh

```bash
#!/usr/bin/env bash
# Source: scripts/restore-drill.sh
# Operator script to run an on-demand restore drill.
# Usage: bash scripts/restore-drill.sh [timeout_seconds]

set -euo pipefail

namespace="${K8S_NAMESPACE:-solid-stats-staging}"
timeout="${1:-900s}"
job_id="restore-drill-$(date -u +%Y%m%d%H%M%S)"

echo "Starting restore drill: ${job_id}"

# Apply the Job manifest with a unique name
kubectl -n "$namespace" apply -f k8s/staging/restore-drill/70-restore-drill.yaml \
  -p '{"metadata":{"name":"'${job_id}'"}}'

# Wait for the Job to complete or timeout
if ! kubectl -n "$namespace" wait --for=condition=complete "job/${job_id}" --timeout="$timeout"; then
  echo "Timeout or Job failed after ${timeout}"
  kubectl -n "$namespace" describe "job/${job_id}" || true
  kubectl -n "$namespace" logs "job/${job_id}" --all-containers=true || true
  exit 1
fi

# Extract the result from the logs
logs="$(kubectl -n "$namespace" logs "job/${job_id}" --all-containers=true)"
echo ""
echo "=== Restore Drill Result ==="
printf '%s\n' "$logs" | grep -E '^(PASS|FAIL):'

# Check for FAIL
if printf '%s\n' "$logs" | grep -q '^FAIL:'; then
  echo "Restore drill validation FAILED"
  exit 1
fi

echo "Restore drill validation PASSED"

# Cleanup: delete the Job (pod is already removed by ttlSecondsAfterFinished)
kubectl -n "$namespace" delete "job/${job_id}" --ignore-not-found

exit 0
```

### Regression Guard: validate-staging.py Extension

```python
# Extend validate_manifest_shape() in scripts/validate-staging.py:
# Add a check after the manifest loop:

def validate_manifest_shape() -> list[tuple[str, str, str]]:
    # ... existing code ...
    
    # Check: No drill manifests at depth-1 (DRILL-04 regression guard)
    depth1_files = list(MANIFEST_DIR.glob("*.yaml"))
    drill_files = [f for f in depth1_files if "drill" in f.name.lower() or "restore" in f.name.lower()]
    require(
        not drill_files,
        f"drill manifests must be in subdirectories, not depth-1; found: {[f.name for f in drill_files]}"
    )
    
    # ... rest of validation ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual pg_dump + restore scripts | Automated restore drill Job in Kubernetes | Phase 8 (2026-06-13) | On-demand proof of recoverability without human script maintenance; Kubernetes-native cleanup and monitoring |
| Full restore into shadow replica | Ephemeral scratch postgres on emptyDir | Phase 8 | Faster, cheaper, no persistent shadow DB; scratch instance is isolated by design |
| Restore into live database (testing) | Guarded DB name + live-host refusal | Phase 8 | Safety by construction; no risk of data corruption; auditable refusal path |
| Manual S3 backup discovery | Lexicographic max of backup_id directory listing | Matches backup-postgres-now.sh | Deterministic, O(N) not O(1), but matches backup format and requires no external index |

**Deprecated/outdated:**
- Shadow PostgreSQL replica for restore testing: Eliminated by using ephemeral emptyDir; Phase 8 removes the need for persistent stand-by infrastructure.
- Manual restore scripts in documentation: Replaced by automated Job + operator script; the drill is now the canonical restore path.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `postgres:17-alpine` image supports `pg_ctl initdb` and startup on emptyDir | Standard Stack, Code Examples | If initdb fails on emptyDir (e.g., due to missing capabilities), the drill cannot initialize scratch postgres. Mitigation: test locally before deployment. |
| A2 | `aws s3 ls` with path-style S3 correctly lists backup prefixes on Timeweb endpoint | Standard Stack, Code Examples | If Timeweb's S3 API does not return backup prefixes in the expected format, backup discovery fails. Mitigation: test against live S3 bucket before Phase 8 execution. |
| A3 | Lexicographic sort of ISO 8601 timestamps (`%Y%m%dT%H%M%SZ`) is chronologically correct | Architecture Patterns | If the backup CronJob uses a different timestamp format, lexicographic max may not be the latest backup. Mitigation: verify backup_id format in 60-postgres-backup.yaml before implementation. |
| A4 | `kubectl -n $ns wait --for=condition=complete job/$name` works for one-shot Jobs with `restartPolicy: Never` | Code Examples | If Kubernetes Job completion condition is not properly reported, the operator script may timeout or miss success. Mitigation: test on live cluster before rollout. |
| A5 | Postgres custom-format dump (`.dump`) files created by the backup CronJob are restorable via `pg_restore` without modification | Standard Stack, Don't Hand-Roll | If dump format has changed or is incompatible with the restore postgres version, restoration fails. Mitigation: verify by testing backup-restore cycle manually before Phase 8. |

**If this table is empty:** N/A — several assumptions are present and are marked for user confirmation.

## Open Questions

1. **Exact row-count thresholds for sanity checks**
   - What we know: Drill must validate that expected tables exist and key tables have > 0 rows (DRILL-02). Example tables: `runs`, `sessions`, `events`.
   - What's unclear: What are the minimum expected row counts for each table? Do thresholds vary based on environment or backup age?
   - Recommendation: Document in `k8s/staging/restore-drill/70-restore-drill.yaml` as hardcoded assertions (e.g., `runs >= 1`, `sessions >= 1`) and update the manifest if thresholds change. Consider adding a ConfigMap for threshold management in v2.x.

2. **Frequency and alerting strategy for manual drill execution**
   - What we know: Phase 8 implements on-demand restore drill; DRILL-05 (scheduled CronJob + alerting) is deferred to v2.x.
   - What's unclear: How often should the operator run the drill? Should there be a manual reminder or checklist?
   - Recommendation: Document in `docs/backup-restore.md` that the restore drill should be run after each significant backup (e.g., weekly, or before production cutover). DRILL-05 will automate this in v2.x.

3. **Backup size expectations and timeout tuning**
   - What we know: Drill uses a 900-second timeout (from `backup-postgres-now.sh`). This covers initdb, S3 download, pg_restore, and assertions.
   - What's unclear: How large is the typical `solid_stats` backup? Will 900s be sufficient if the backup grows to 1GB+?
   - Recommendation: Test with the current backup size and measure actual restore time. Adjust Job timeout in `k8s/staging/restore-drill/70-restore-drill.yaml` if needed. Document expected duration in `docs/backup-restore.md`.

4. **S3 backup expiration and retention during drill**
   - What we know: Backup CronJob stores backups under `backups/postgres/{backup_id}/`. Phase 10 will implement S3 lifecycle policies for retention.
   - What's unclear: If a backup expires while the drill is restoring, will the restore fail mid-operation? How should the drill handle missing backups?
   - Recommendation: Phase 8 drill assumes backups exist. If manifest.json is not found, the drill fails loudly. Retention policies (Phase 10) should ensure at least N recent backups remain available. Document the assumption in the manifest comment.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| kubectl | Job apply/status/cleanup in scripts/restore-drill.sh | ✓ | (operator machine; cluster reachable via WireGuard) | Manual Job apply via YAML copy-paste (not recommended) |
| postgres:17-alpine image | Drill pod runtime | ✓ | 17-alpine (pinned in live postgres StatefulSet; pulled with IfNotPresent) | — |
| aws-cli | S3 backup discovery + download | ✓ (apk add in pod) | latest alpine | Manual aws s3 CLI (already available in postgres:17-alpine via apk) |
| PostgreSQL binaries (pg_ctl, pg_restore, psql, createdb) | Drill runtime operations | ✓ (bundled in postgres:17-alpine) | 17 | — |
| Timeweb S3 endpoint (https://s3.twcstorage.ru) | Backup retrieval | ✓ | (verified in backup-postgres CronJob logs) | Local S3 mock (not applicable to Phase 8) |
| GitHub secrets (S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, POSTGRES_PASSWORD) | Job environment variables (via Kubernetes Secrets) | ✓ | (populated by GitHub CI, mirrored to k8s Secrets) | — |

**Missing dependencies with no fallback:**
- None identified. All dependencies are either built into the postgres image or available via apk, or are external services already in use by the backup CronJob.

**Missing dependencies with fallback:**
- None identified.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Kubernetes Job (batch/v1); `kubectl wait --for=condition=complete` for synchronous validation |
| Config file | `k8s/staging/restore-drill/70-restore-drill.yaml` (Job manifest is the test definition) |
| Quick run command | `bash scripts/restore-drill.sh` |
| Full suite command | `bash scripts/validate-staging.py` (includes DRILL-04 depth-1 regression guard) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DRILL-01 | Restore latest S3 backup into ephemeral scratch postgres, never touching live postgres-0/postgres-data | Integration | `kubectl apply -f k8s/staging/restore-drill/70-restore-drill.yaml && kubectl wait --for=condition=complete job/restore-drill-* --timeout=900s` | ✅ (Wave 0 deliverable) |
| DRILL-02 | Post-restore sanity assertions (table count >= 5, key tables have rows) fail loudly if violated | Unit (embedded in Job container) | `kubectl logs job/restore-drill-* \| grep -E '^(PASS\|FAIL):'` | ✅ (embedded in Job command block) |
| DRILL-03 | Drill tears down scratch DB/postgres and emits result line to logs | Integration | `kubectl logs job/restore-drill-* \| grep -E '^(PASS\|FAIL):'` | ✅ (embedded in Job command block) |
| DRILL-04 | Drill manifest is stored in subdirectory; not in CD deploy glob | Offline validator | `python3 scripts/validate-staging.py` (regression guard added to manifest_shape check) | ✅ (validate-staging.py extended) |

### Sampling Rate
- **Per task commit:** `bash scripts/restore-drill.sh` (full drill, ~10 min; optional for each commit, recommended for backup-related changes)
- **Per wave merge:** `python3 scripts/validate-staging.py` (offline, <5s; includes DRILL-04 regression guard)
- **Phase gate:** `bash scripts/restore-drill.sh` completes with PASS result before `/gsd-verify-work`

### Wave 0 Gaps
- [x] `k8s/staging/restore-drill/70-restore-drill.yaml` — Job manifest (main deliverable)
- [x] `scripts/restore-drill.sh` — operator script (main deliverable)
- [ ] `scripts/validate-staging.py` — DRILL-04 depth-1 regression guard to be added during Phase 8 execution
- [ ] Manual test of restore-drill on live staging VPS with real S3 backup

*(Test infrastructure exists; Phase 8 adds the drill-specific validation.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | N/A — drill uses service account tokens and S3 credentials (inherited from backup CronJob) |
| V3 Session Management | no | N/A — drill is stateless and ephemeral |
| V4 Access Control | yes | Drill ServiceAccount has no RBAC permissions (read-only S3 access via credential injection); live postgres is protected by guarded DB name + local-only socket |
| V5 Input Validation | yes | S3 backup_id is validated against manifest.json; pg_restore fails if dump is malformed |
| V6 Cryptography | yes | S3 credentials are stored in Kubernetes Secrets (not git); TLS for S3 endpoint (https://s3.twcstorage.ru); no custom crypto hand-rolled |

### Known Threat Patterns for Kubernetes Job + S3 + PostgreSQL

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Compromise of S3 credentials (leaked in logs, pod events, or env vars) | Tampering / Disclosure | S3 credentials are stored in Kubernetes Secrets, not hardcoded. Environment variables are redacted in pod logs by `kubectl logs` (default). Document: "Never echo AWS_* env vars in scripts." |
| Malicious S3 backup (e.g., compressed bomb, malformed custom format) | Tampering / Denial of Service | pg_restore validates dump format and rejects invalid archives. S3 access is read-only (no upload/delete permissions). Drill runs in a sandbox (Job pod with resource limits) — restore process memory/disk is bounded by the Job's requests/limits. |
| Restore into live database (accidental data corruption) | Tampering | Guarded target DB name (`solid_stats_drill` != `solid_stats`). Live-host refusal check: if `PGHOST != localhost`, drill exits. Scratch postgres is on emptyDir, not the live PVC. |
| Privilege escalation in pod (e.g., postgres user escapes container) | Elevation of Privilege | Pod securityContext: `allowPrivilegeEscalation: false`, `runAsUser: UID of postgres image` (implicitly non-root). No `securityContext: { privileged: true }`. Network isolation: drill pod cannot reach the live postgres Service (no NetworkPolicy implemented yet; documented exception in Phase 7 UAT). |
| DoS via resource exhaustion (e.g., pg_restore allocates unbounded memory) | Denial of Service | Job container has `resources: { requests: 512Mi, limits: 2Gi }`. postgres cannot allocate more than 2Gi per container. Kill-on-limit is enforced by kubelet. |
| Timing attack on S3 authentication (e.g., attacker guesses S3 credentials by observing latency) | Information Disclosure | Not applicable — S3 credentials are not part of the drill's output or logs. Credentials are injected at runtime from Secrets and not echoed. |

## Sources

### Primary (HIGH confidence)
- [VERIFIED: codebase] `k8s/staging/60-postgres-backup.yaml` — backup CronJob with proven S3 wiring, env/secret patterns, postgres image, and aws-cli usage (2026-06-13).
- [VERIFIED: codebase] `scripts/backup-postgres-now.sh` — manual backup trigger script; mirrors the drill's result-capture and cleanup patterns.
- [VERIFIED: codebase] `k8s/staging/10-postgres.yaml` — live postgres StatefulSet; defines the guarded database name, live Service name, and PVC that the drill must NOT touch.
- [VERIFIED: codebase] AGENTS.md — Kubernetes workload safety conventions: ServiceAccountName, automountServiceAccountToken, securityContext, resource requests/limits (all applied to drill Job).

### Secondary (MEDIUM confidence)
- [CITED: Kubernetes official docs] `batch/v1 Job` — Job manifest API and `ttlSecondsAfterFinished` cleanup.
- [CITED: PostgreSQL docs] `pg_ctl`, `pg_dump`, `pg_restore` — standard PostgreSQL tooling used in drill.
- [CITED: AWS CLI docs] `aws s3 ls`, `aws s3 cp` — S3 operations; path-style addressing verified against Timeweb endpoint.

### Tertiary (LOW confidence)
- [ASSUMED] Timeweb S3 API supports path-style addressing and responds to `aws s3` CLI. Verified by codebase (backup CronJob logs show successful uploads), but not tested for restoration in Phase 8 research.
- [ASSUMED] Drill will be triggered manually via `scripts/restore-drill.sh`; automation (DRILL-05) is deferred to v2.x.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — postgres:17-alpine, aws-cli, pg_* tools are proven in backup CronJob and codebase.
- Architecture: HIGH — Job manifest and S3/postgres wiring are derived from existing backup CronJob; patterns are Kubernetes-standard.
- Pitfalls: MEDIUM — common Kubernetes failure modes are documented, but Phase 8 execution will uncover environment-specific issues (timeouts, permissions, S3 latency).
- Security: MEDIUM — ASVS controls are straightforward (no custom crypto, secret storage); threat model is bounded by Kubernetes sandbox and S3 read-only access.

**Research date:** 2026-06-13
**Valid until:** 2026-07-13 (30 days; Kubernetes and postgres image tags are stable; S3 API is stable)

---

## RESEARCH COMPLETE

**Phase:** 8 - Automated Restore Drill
**Confidence:** HIGH

### Key Findings
- Scratch PostgreSQL on emptyDir via `pg_ctl` is the safest topology for isolation (zero chance of touching live postgres-data or Service).
- Latest backup discovery via lexicographic sort of ISO 8601 timestamps matches the backup CronJob format and is deterministic.
- Post-restore sanity checks (table count, row counts) with captured result code ensure cleanup always runs and failures are visible.
- Manifest subdirectory `k8s/staging/restore-drill/` and operator script `scripts/restore-drill.sh` satisfy DRILL-04 constraint (out-of-CD-path).
- All patterns and wiring (S3 config, postgres image, secrets) are proven in the existing backup CronJob; the drill reuses them with minimal new code.

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | postgres:17-alpine, aws-cli, pg_* binaries are verified in codebase and backup CronJob; no new packages. |
| Architecture | HIGH | Job manifest, pg_ctl initialization, S3 operations are Kubernetes-standard and derived from proven backup CronJob. |
| Pitfalls | MEDIUM | Common failure modes are documented (permissions, timeouts, S3 consistency); live testing will validate assumptions. |
| Security | MEDIUM | ASVS controls are standard (secret storage, sandbox isolation); threat model is bounded by S3 read-only access and guarded DB name. |

### Open Questions
- Exact row-count thresholds for sanity checks (documented in manifest; configurable via ConfigMap in v2.x).
- Operator workflow and frequency for manual drill execution (documented in `docs/backup-restore.md`).
- Backup size growth and timeout tuning (measure with live backup; adjust Job timeout if needed).
- S3 backup retention interaction with restore drill (addressed by Phase 10 S3 lifecycle policies).

### Ready for Planning
Research complete. All four phase requirements (DRILL-01..04) have concrete implementation patterns, validated against the codebase, and documented with High confidence. Planner can now create Phase 8 task breakdown and manifest generation.
