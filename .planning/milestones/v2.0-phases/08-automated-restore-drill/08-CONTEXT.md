# Phase 8: Automated Restore Drill - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss); enriched with codebase facts by the orchestrator

<domain>
## Phase Boundary

Operator can prove on demand that the latest S3 backup restores into an ephemeral scratch
PostgreSQL with passing sanity checks, never touching live data, with the drill kept out of
the CD deploy path.

Requirements: DRILL-01, DRILL-02, DRILL-03, DRILL-04.
Depends on: Phase 6 (kubectl-native CD). DRILL-05 (scheduled CronJob + alerting) is DEFERRED to v2.x — this phase is ON-DEMAND only.
</domain>

<decisions>
## Implementation Decisions

### Locked by codebase facts (verified 2026-06-13)
- **Backup source of truth** is the existing `postgres-backup` CronJob (`k8s/staging/60-postgres-backup.yaml`).
  It writes, per run, to S3:
  - `s3://${S3_BUCKET}/backups/postgres/<backup_id>/solid_stats.dump`  (pg_dump custom format, `--no-owner --no-privileges`)
  - `…/<backup_id>/solid_stats.dump.list`  (pg_restore --list output)
  - `…/<backup_id>/manifest.json`  (backup_id, created_at, database, dump_object, list_object, dump_size_bytes)
  - `backup_id = date -u +%Y%m%dT%H%M%SZ` — so lexicographic max under `backups/postgres/` == latest.
  - S3: endpoint `https://s3.twcstorage.ru`, region `ru-1`, **path-style addressing**, `AWS_EC2_METADATA_DISABLED=true`.
- **Secrets to reuse (live k8s Secrets, never in git):** `postgres-auth` → `POSTGRES_PASSWORD`;
  `server-2-runtime` → `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`.
- **Image:** `postgres:17-alpine` (same as backup job; pinned, `imagePullPolicy: IfNotPresent`).
- **Live DB identity (must NOT be touched):** StatefulSet `postgres`, Service `postgres:5432`, PVC `postgres-data`,
  db `solid_stats`, user `solid`. The drill MUST NOT connect to the live `postgres` Service for restore — it
  restores into its OWN scratch postgres.

### Claude's discretion (decide during planning, justify in PLAN)
- **Scratch PostgreSQL topology:** prefer a self-contained drill Job that runs its OWN throwaway
  `postgres` process inside the drill pod (sidecar container or `pg_ctl` in the same container on an
  `emptyDir`), so there is zero chance of touching `postgres-data` or the live Service. A guarded target
  DB name (e.g. `solid_stats_drill`) and an explicit refusal if `POSTGRES_HOST` resolves to the live
  Service add defense-in-depth (DRILL-01).
- **Latest-backup discovery:** `aws s3 ls s3://$S3_BUCKET/backups/postgres/` → take lexicographic max
  prefix → download its `solid_stats.dump` (+ optionally verify against `manifest.json` / `.list`).
- **Sanity assertions (DRILL-02):** after `pg_restore` into the scratch DB, run row-count / object checks
  (e.g. expected tables exist; key tables have > 0 rows; optionally compare table list to the `.list`).
  Fail loudly = non-zero exit + clear log, with NO teardown-masks-failure (capture result, then teardown,
  then exit with the saved code).
- **Teardown + evidence (DRILL-03):** drop scratch DB / remove emptyDir, and emit a structured result line
  (PASS/FAIL, backup_id, row counts, duration) to stdout/logs as the evidence artifact. The pod is
  `restartPolicy: Never` + `ttlSecondsAfterFinished` so it self-cleans.
- **Out-of-CD-path placement (DRILL-04):** CD applies `find k8s/staging -maxdepth 1 -name '*.yaml' ! -name 01-ci-rbac.yaml`.
  Therefore drill manifests MUST live in a SUBDIRECTORY (e.g. `k8s/staging/restore-drill/…`) or a non-glob
  path, so `-maxdepth 1` never matches them. Provide an operator script (e.g. `scripts/restore-drill.sh`)
  that applies + tails + cleans the drill Job on demand. Add an offline validator check that asserts no
  drill manifest is at `k8s/staging/*.yaml` depth-1 (regression guard for DRILL-04).
</decisions>

<code_context>
## Existing Code Insights
- `k8s/staging/60-postgres-backup.yaml` — backup CronJob; copy its env/secret wiring + S3 config verbatim.
- `scripts/backup-postgres-now.sh` — manual backup trigger; mirror its style for `scripts/restore-drill.sh`.
- `scripts/validate-staging.py` — offline manifest/safety validator; extend with a DRILL-04 depth-1 guard.
- `.github/workflows/deploy-staging.yml` lines 69/124 — the exact apply glob the drill must avoid.
- Kubernetes safety rules (AGENTS.md): no default ServiceAccount, drop tokens (`automountServiceAccountToken: false`),
  securityContext, resource requests/limits, explicit namespace.
</code_context>

<specifics>
## Specific Ideas
- Mirror the backup job's hardened pod spec (dedicated SA, `automountServiceAccountToken: false`,
  `allowPrivilegeEscalation: false`, requests/limits).
- The drill must be SAFE BY CONSTRUCTION: its own scratch postgres, never the live Service; guarded DB name;
  refuse-if-live-host check.
</specifics>

<deferred>
## Deferred Ideas
- DRILL-05: scheduled restore-drill CronJob + failure alerting — explicitly deferred to v2.x.
</deferred>
