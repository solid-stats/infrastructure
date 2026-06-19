# Deploy Model and v1 Scope

This repository owns how the Solid Stats application images are composed into a
working staging runtime. Application repositories own application source code and
container image builds; this repository owns the runtime wiring in staging.

See [staging.md](./staging.md) for staging operations, the deploy host, required
GitHub environment secrets, and the Staging Handoff Matrix (the boundary between
the app repositories that build images and this repository that deploys staging
runtime wiring). For remote `kubectl` from a workstation, see
[k3s-api-access.md](./k3s-api-access.md).

## CI deploy flow

The GitHub Actions workflow (`.github/workflows/deploy-staging.yml`) deploys on
pushes to `master`, and can be run manually with `workflow_dispatch`.

On merge to `master` the workflow:

1. Opens an SSH local-forward to the closed k3s API (`scripts/ssh-tunnel-up.sh`,
   `127.0.0.1:16443` -> k3s API `6443`), fail-closed gating on the forwarded port
   being reachable before any `kubectl`.
2. Builds a kubeconfig from the `ci-deployer` ServiceAccount token and k3s CA
   (`scripts/kubeconfig-setup.sh`).
3. Applies `k8s/staging/`, excluding the operator-managed `01-ci-rbac.yaml`.
4. Waits for `statefulset/postgres`, `statefulset/rabbitmq`,
   `deployment/server-2`, and `deployment/replay-parser-2`.
5. Lists the `postgres`, `rabbitmq`, and `server-2` Services plus the
   `replays-fetcher` and `postgres-backup` CronJobs.

Validate the staging manifests, scripts, and rendered Secret structure before
deploy:

```bash
python3 scripts/validate-staging.py
```

## v1 scope (Phase 1)

Phase 1 owns the namespace, PostgreSQL, RabbitMQ, `server-2`, `replay-parser-2`,
the suspended `replays-fetcher`, and `postgres-backup`.

Out of this phase: production cutover, host edge automation, application
source/image builds, immediate legacy deploy removal, scheduled replay fetching,
backup gate execution, full run, diff readiness, and the future `web` runtime.

## Manual backup

After the staging manifests are applied:

```bash
K8S_NAMESPACE=solid-stats-staging ./scripts/backup-postgres-now.sh
```

The job creates and waits for a one-off backup from the deployed backup CronJob,
writing a PostgreSQL custom-format dump, restore list, and JSON manifest under
the configured S3 bucket prefix `backups/postgres/`. See
[backup-restore.md](./backup-restore.md) for the full backup and restore runbook.
